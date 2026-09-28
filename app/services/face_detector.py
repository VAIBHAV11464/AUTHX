import json
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock

import cv2
import numpy as np
from flask import current_app

_detector = None
_recognizer = None
_detector_key = _recognizer_key = None
_model_lock = RLock()
_detections = ContextVar("authx_detections", default=None)


@contextmanager
def detection_cache():
    """Cache v2 detections only within the current scoring call."""
    token = _detections.set({})
    try:
        yield
    finally:
        _detections.reset(token)


def models_ready():
    cfg = current_app.config
    return cfg["YUNET_PATH"].is_file() and cfg["SFACE_PATH"].is_file()


def cosine_to_score(similarity):
    sim = float(similarity)
    if sim < 0:
        sim = 0.0
    if sim > 1:
        sim = 1.0
    high = 0.60
    match = float(current_app.config["COSINE_MATCH"])
    low = 0.20
    if sim >= high:
        return 95.0
    if sim >= match:
        return 60.0 + (sim - match) / (high - match) * 35.0
    if sim >= low:
        return 20.0 + (sim - low) / (match - low) * 40.0
    return sim / low * 20.0


def score_vectors(left, right):
    a = np.asarray(left, dtype=np.float32).reshape(-1)
    b = np.asarray(right, dtype=np.float32).reshape(-1)
    if a.size == 0 or a.shape != b.shape:
        return cosine_to_score(0)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return cosine_to_score(0)
    return cosine_to_score(float(np.dot(a, b) / denom))


def detect_faces(image):
    cache = _detections.get()
    if cache is not None:
        reason, faces = detect_all_faces(image)
        if reason:
            return reason, None
        return None, faces[int(np.argmax(faces[:, 2] * faces[:, 3]))]
    if not models_ready():
        return "model_missing", None
    image = _as_bgr(image)
    if image is None:
        return "no_face", None
    try:
        with _model_lock:
            detector = _yunet(image.shape[1], image.shape[0], current_app.config["YUNET_SCORE"])
            faces = _run_detect(detector, image)
            if faces is None:
                detector = _yunet(image.shape[1], image.shape[0], current_app.config["YUNET_SCORE_RETRY"])
                faces = _run_detect(detector, image)
    except cv2.error:
        return "model_missing", None
    if faces is None:
        return "no_face", None
    areas = faces[:, 2] * faces[:, 3]
    return None, faces[int(np.argmax(areas))]


def _detect_all_faces(image):
    """Return every YuNet face for the v2 quality gate; legacy keeps its API."""
    if not models_ready():
        return "model_missing", None
    image = _as_bgr(image)
    if image is None:
        return "no_face", None
    try:
        # Use the existing lower threshold to notice other people in the frame.
        with _model_lock:
            detector = _yunet(image.shape[1], image.shape[0], current_app.config["YUNET_SCORE_RETRY"])
            faces = _run_detect(detector, image)
    except cv2.error:
        return "model_missing", None
    if faces is None:
        return "no_face", None
    return None, faces


def detect_all_faces(image):
    cache = _detections.get()
    if cache is None:
        return _detect_all_faces(image)
    key = id(image)
    if key not in cache:
        cache[key] = _detect_all_faces(image)
    return cache[key]


def enroll_gate(face_row):
    row = np.asarray(face_row, dtype=np.float32).reshape(-1)
    width, height, score = float(row[2]), float(row[3]), float(row[-1])
    cfg = current_app.config
    if width < cfg["ENROLL_MIN_FACE_PX"] or height < cfg["ENROLL_MIN_FACE_PX"]:
        return "weak_face"
    if score < cfg["ENROLL_YUNET_SCORE"]:
        return "weak_face"
    return None


def embed_row(image, face_row):
    row = np.asarray(face_row, dtype=np.float32).reshape(-1)
    if row.size < 15:
        raise ValueError("full_yunet_row_required")
    with _model_lock:
        recognizer = _sface()
        aligned = recognizer.alignCrop(image, row.reshape(1, 15))
        feature = recognizer.feature(aligned).reshape(-1).copy()
    return feature


def enroll_image(image):
    reason, face = detect_faces(image)
    if reason:
        return reason, None
    weak = enroll_gate(face)
    if weak:
        return weak, None
    try:
        feature = embed_row(image, face)
    except cv2.error:
        return "model_missing", None
    except ValueError:
        return "no_face", None
    return None, json.dumps([float(v) for v in feature])


def match_pre_flash(frames, flash_start_ms, embedding):
    try:
        enrolled = np.asarray(json.loads(embedding), dtype=np.float32)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {"ok": False, "reason": "not_enrolled"}
    min_px = float(current_app.config["MIN_FACE_PX"])
    found = []
    for stamp, image in frames:
        if stamp >= flash_start_ms:
            continue
        reason, face = detect_faces(image)
        if reason == "model_missing":
            return {"ok": False, "reason": "model_missing"}
        if reason or face is None:
            continue
        row = np.asarray(face, dtype=np.float32).reshape(-1)
        if float(row[2]) < min_px or float(row[3]) < min_px:
            continue
        found.append((float(row[-1]), image, row))
    if len(found) < 8:
        return {"ok": False, "reason": "no_face"}
    found.sort(key=lambda item: item[0], reverse=True)
    cosines = []
    for _, image, row in found[:3]:
        try:
            feature = embed_row(image, row)
        except cv2.error:
            return {"ok": False, "reason": "model_missing"}
        except ValueError:
            continue
        cosines.append(_cosine(enrolled, feature))
    if not cosines:
        return {"ok": False, "reason": "no_face"}
    cosine = float(np.median(np.asarray(cosines, dtype=np.float64)))
    return {
        "ok": True,
        "faceScore": round(cosine_to_score(cosine), 2),
        "cosine": round(cosine, 4),
    }


def _cosine(left, right):
    a = np.asarray(left, dtype=np.float32).reshape(-1)
    b = np.asarray(right, dtype=np.float32).reshape(-1)
    if a.size == 0 or a.shape != b.shape:
        return 0.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _yunet(width, height, score):
    global _detector, _detector_key
    path = str(current_app.config["YUNET_PATH"])
    if _detector is None or _detector_key != path:
        _detector = cv2.FaceDetectorYN.create(path, "", (width, height), score)
        _detector_key = path
    _detector.setInputSize((width, height))
    _detector.setScoreThreshold(score)
    return _detector


def _sface():
    global _recognizer, _recognizer_key
    path = str(current_app.config["SFACE_PATH"])
    if _recognizer is None or _recognizer_key != path:
        _recognizer = cv2.FaceRecognizerSF.create(path, "")
        _recognizer_key = path
    return _recognizer


def _as_bgr(image):
    if image is None or not hasattr(image, "shape") or image.ndim != 3 or image.shape[2] != 3:
        return None
    if image.shape[0] < 2 or image.shape[1] < 2:
        return None
    frame = np.ascontiguousarray(image)
    if frame.dtype != np.uint8:
        frame = np.clip(frame, 0, 255).astype(np.uint8)
    return frame


def _run_detect(detector, image):
    try:
        _, faces = detector.detect(image)
    except cv2.error:
        return None
    if faces is None or len(faces) == 0:
        return None
    faces = np.asarray(faces)
    if faces.ndim == 1:
        faces = faces.reshape(1, -1)
    if faces.shape[1] < 15:
        return None
    return faces.copy()
