import cv2
import numpy as np
from flask import current_app

from app.services.face_detector import detect_faces


def score_v2_brightness(samples, flash_start_ms):
    """Missing observations request retry; measured weak response earns 25."""
    cfg = current_app.config
    window = cfg["FLASH_DURATION_MS"]
    groups = [[], []]
    for stamp, brightness in samples:
        if not np.isfinite(stamp) or not np.isfinite(brightness) or not 0 <= brightness <= 255:
            return _missing_flash("invalid_flash_evidence")
        if flash_start_ms - window <= stamp < flash_start_ms:
            groups[0].append((stamp, brightness))
        elif flash_start_ms <= stamp < flash_start_ms + window:
            groups[1].append((stamp, brightness))
    for group in groups:
        if (len(group) < cfg["V2_FLASH_MIN_SAMPLES"]
                or group[-1][0] - group[0][0] < cfg["V2_FLASH_MIN_SPAN_MS"]
                or any(b[0] <= a[0] or b[0] - a[0] > cfg["V2_LANDMARK_MAX_GAP_MS"] for a, b in zip(group, group[1:]))):
            return _missing_flash("insufficient_flash_evidence")
    if groups[1][0][0] - groups[0][-1][0] > cfg["V2_LANDMARK_MAX_GAP_MS"]:
        return _missing_flash("insufficient_flash_evidence")
    # Near-black/fully saturated observations cannot measure a reliable response.
    if any(not 5 < float(np.mean([v for _, v in group])) < 250 for group in groups):
        return _missing_flash("invalid_flash_evidence")
    result = score_brightness(samples, flash_start_ms)
    result["evidenceFrames"] = sum(map(len, groups))
    result['gateEvidence'] = {'measured': True, 'beforeSamples': len(groups[0]), 'duringSamples': len(groups[1]),
                              'beforeSpanMs': groups[0][-1][0] - groups[0][0][0],
                              'duringSpanMs': groups[1][-1][0] - groups[1][0][0],
                              'maxGapMs': max(b[0] - a[0] for a, b in zip(groups[0] + groups[1], (groups[0] + groups[1])[1:])),
                              'delta': result['reflectionDelta'], 'correlation': result['reflectionR']}
    return result


def _missing_flash(reason):
    return {"ok": False, "reason": reason, "flashScore": None,
            "reflectionDelta": None, "reflectionR": None, "detail": reason}


def score_v2_flash(frames, flash_start_ms):
    samples = []
    window = current_app.config["FLASH_DURATION_MS"]
    for stamp, image in frames:
        if not flash_start_ms - window <= stamp < flash_start_ms + window:
            continue
        reason, face = detect_faces(image)
        if reason == "model_missing":
            return _missing_flash(reason)
        if reason or face is None:
            continue
        crop = _crop(image, face)
        if crop is not None:
            samples.append((stamp, _luminance(crop)))
    return score_v2_brightness(samples, flash_start_ms)


def score_brightness(samples, flash_start_ms, duration_ms=None, high=None, mid=None):
    if duration_ms is None:
        duration_ms = current_app.config["FLASH_DURATION_MS"]
    if high is None:
        high = current_app.config["FLASH_DELTA_HIGH"]
    if mid is None:
        mid = current_app.config["FLASH_DELTA_MID"]
    before = []
    during = []
    for stamp, brightness in samples:
        if flash_start_ms - duration_ms <= stamp < flash_start_ms:
            before.append(float(brightness))
        elif flash_start_ms <= stamp < flash_start_ms + duration_ms:
            during.append(float(brightness))
    if len(before) < 2 or len(during) < 2:
        return {
            "ok": True,
            "flashScore": 50,
            "reflectionDelta": None,
            "reflectionR": None,
            "detail": "too_few_flash_frames",
        }
    mean_before = float(np.mean(before))
    mean_during = float(np.mean(during))
    if mean_before <= 1e-6:
        delta = 0.0 if mean_during <= mean_before else 1.0
    else:
        delta = (mean_during - mean_before) / mean_before
    paired = before + during
    gate = [0.0] * len(before) + [1.0] * len(during)
    if delta >= high:
        score = 90
    elif delta >= mid:
        score = 60
    else:
        score = 25
    return {
        "ok": True,
        "flashScore": score,
        "reflectionDelta": round(delta, 4),
        "reflectionR": round(_pearson(paired, gate), 4),
        "detail": None,
    }


def score_flash_frames(frames, flash_start_ms):
    samples = []
    window = current_app.config["FLASH_DURATION_MS"]
    start = flash_start_ms - window
    end = flash_start_ms + window
    for stamp, image in frames:
        if stamp < start or stamp >= end:
            continue
        reason, face = detect_faces(image)
        if reason == "model_missing":
            return {
                "ok": False,
                "reason": "model_missing",
                "flashScore": None,
                "reflectionDelta": None,
                "reflectionR": None,
                "detail": "model_missing",
            }
        if reason or face is None:
            continue
        crop = _crop(image, face)
        if crop is None:
            continue
        samples.append((stamp, _luminance(crop)))
    return score_brightness(samples, flash_start_ms)


def _luminance(face_crop):
    gray = face_crop if face_crop.ndim == 2 else cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
    return float(gray.mean())


def _pearson(left, right):
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.sqrt(np.dot(a, a) * np.dot(b, b)))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _crop(image, face_row):
    row = np.asarray(face_row, dtype=np.float32).reshape(-1)
    x, y, width, height = [int(v) for v in row[:4]]
    x = max(0, x)
    y = max(0, y)
    crop = image[y : y + max(1, height), x : x + max(1, width)]
    if crop.size == 0:
        return None
    return crop
