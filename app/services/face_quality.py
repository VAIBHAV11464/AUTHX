"""v2 capture readiness checks, without changing identity or liveness scoring."""

import json
import math
from collections import Counter

import cv2
import numpy as np
from flask import current_app

from app.services.face_detector import detect_all_faces, embed_row, enroll_gate


def face_quality(image, faces):
    if faces is None or len(faces) == 0:
        return "no_face", None
    if len(faces) > 1:
        return "multiple_faces", None
    row = np.asarray(faces[0], dtype=np.float32).reshape(-1)
    if row.size != 15 or not np.isfinite(row).all():
        return "no_face", None
    cfg = current_app.config
    x, y, width, height = map(float, row[:4])
    image_height, image_width = image.shape[:2]
    if (min(width, height) < cfg["V2_FACE_MIN_PX"]
            or width * height / (image_width * image_height) < cfg["V2_FACE_MIN_AREA_RATIO"]):
        return "face_too_small", None
    if row[-1] < cfg["V2_FACE_MIN_CONFIDENCE"]:
        return "weak_face", None
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(image_width, x + width), min(image_height, y + height)
    if max(0, x1 - x0) * max(0, y1 - y0) / (width * height) < cfg["V2_FACE_MIN_VISIBLE_RATIO"]:
        return "face_cut_off", None
    crop = image[math.floor(y0):math.ceil(y1), math.floor(x0):math.ceil(x1)]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    mean = float(gray.mean())
    if mean < cfg["V2_FACE_MIN_BRIGHTNESS"]:
        return "face_too_dark", None
    if mean > cfg["V2_FACE_MAX_BRIGHTNESS"]:
        return "face_too_bright", None
    clipped = float(np.mean((gray <= 15) | (gray >= 245)))
    if clipped > cfg["V2_FACE_MAX_CLIPPED_RATIO"]:
        return "uneven_face_lighting", None
    # A fixed ROI size makes this threshold less dependent on camera resolution.
    normalized = cv2.resize(gray, (128, 128), interpolation=cv2.INTER_AREA)
    sharpness = float(cv2.Laplacian(normalized, cv2.CV_64F).var())
    if sharpness < cfg["V2_FACE_MIN_SHARPNESS"]:
        return "face_blurry", None
    return None, row


def enroll_image(image):
    reason, faces = detect_all_faces(image)
    if reason:
        return reason, None
    reason, row = face_quality(image, faces)
    if reason:
        return reason, None
    reason = enroll_gate(row)
    if reason:
        return reason, None
    try:
        feature = embed_row(image, row)
    except cv2.error:
        return "model_missing", None
    except ValueError:
        return "no_face", None
    # Retain the existing single-image enrollment representation.
    return None, json.dumps([float(value) for value in feature])


def inspect_clip(frames, flash_start_ms=None):
    """Return quality-approved frames and their already detected face rows.

    Look readiness is measured before the deliberate flash. All frames are
    checked for multiple faces, including flash/post-flash frames. This gate
    does not alter blink, flash or lip scoring.
    """
    cfg = current_app.config
    eligible = usable = 0
    approved = []
    failures = Counter()
    for stamp, image in frames:
        reason, faces = detect_all_faces(image)
        if reason == "model_missing":
            return reason, []
        if faces is not None and len(faces) > 1:
            return "multiple_faces", []
        if flash_start_ms is not None and stamp >= flash_start_ms:
            continue
        eligible += 1
        if not reason:
            reason, row = face_quality(image, faces)
        if reason:
            failures[reason] += 1
        else:
            usable += 1
            approved.append((stamp, image, row))
    minimum = max(cfg["V2_FRAME_MIN_COUNT"], math.ceil(eligible * cfg["V2_FACE_QUALITY_MIN_RATIO"]))
    if usable < minimum:
        reason = failures.most_common(1)[0][0] if failures else "too_few_usable_face_frames"
        return reason, []
    return None, approved


def clip_quality(frames, flash_start_ms=None):
    return inspect_clip(frames, flash_start_ms)[0]
