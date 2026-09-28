"""Offline, checksum-verified MediaPipe landmarks, isolated between captures."""

import atexit
import hashlib
from dataclasses import dataclass
from importlib.metadata import version
from threading import RLock

import numpy as np
from flask import current_app

_lock = RLock()
_model = None
_key = None
_verified = None


@dataclass(frozen=True)
class LandmarkFrame:
    t_ms: float
    image: np.ndarray
    points: np.ndarray | None
    reason: str | None = None


def close():
    global _model, _key, _verified
    with _lock:
        if _model is not None:
            _model.close()
        _model = _key = _verified = None


atexit.register(close)


def _load():
    global _model, _key, _verified
    cfg = current_app.config
    path = cfg["LANDMARK_PATH"]
    if not path.is_file():
        return "landmark_model_missing", None
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, cfg["LANDMARK_SHA256"], cfg["MEDIAPIPE_VERSION"])
    if _verified != key:
        if hashlib.sha256(path.read_bytes()).hexdigest() != cfg["LANDMARK_SHA256"]:
            return "landmark_model_invalid", None
        _verified = key
    if _model is None or _key != key:
        close()
        if version("mediapipe") != cfg["MEDIAPIPE_VERSION"]:
            return "landmark_model_invalid", None
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        # IMAGE mode has no cross-user tracking state or global video timestamps.
        options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_buffer=path.read_bytes(), delegate=python.BaseOptions.Delegate.CPU),
            running_mode=vision.RunningMode.IMAGE, num_faces=2,
            min_face_detection_confidence=.5, min_face_presence_confidence=.5,
            output_face_blendshapes=False, output_facial_transformation_matrixes=False,
        )
        _model = vision.FaceLandmarker.create_from_options(options)
        _key = _verified = key
    return None, _model


def measure_clip(frames):
    """One inference per frame; consumers share the returned pixel coordinates."""
    measured = []
    try:
        with _lock:
            reason, model = _load()
            if reason:
                return reason, []
            import mediapipe as mp
            for stamp, image in frames:
                rgb = np.ascontiguousarray(image[:, :, ::-1])
                result = model.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
                if len(result.face_landmarks) > 1:
                    return "multiple_faces", []
                if len(result.face_landmarks) != 1:
                    why = "multiple_faces" if len(result.face_landmarks) > 1 else "no_landmarks"
                    measured.append(LandmarkFrame(stamp, image, None, why))
                    continue
                points = np.array([(p.x * image.shape[1], p.y * image.shape[0], p.z * image.shape[1])
                                   for p in result.face_landmarks[0]], dtype=np.float64)
                if points.shape[0] < 468 or not np.isfinite(points).all():
                    measured.append(LandmarkFrame(stamp, image, None, "invalid_landmarks"))
                else:
                    points.setflags(write=False)
                    measured.append(LandmarkFrame(stamp, image, points))
    except (ImportError, OSError, RuntimeError, ValueError, AttributeError):
        return "landmark_model_missing", []
    return None, measured
