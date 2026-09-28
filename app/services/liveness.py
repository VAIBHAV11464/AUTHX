import cv2
import numpy as np
from flask import current_app

from app.services.face_detector import detect_faces
from app.services.landmark_geometry import eye_ratios


def score_landmark_blink(measured, flash_start_ms):
    """Require bilateral open–closed–open, wholly before the flash."""
    cfg = current_app.config
    frames = [frame for frame in measured if frame.t_ms < flash_start_ms]
    values = [(frame.t_ms, eye_ratios(frame.points)) for frame in frames]
    usable = [(stamp, ratios) for stamp, ratios in values if ratios is not None]
    failure = {"ok": False, "reason": "insufficient_blink_evidence", "blinkCount": 0, "dipPercent": 0.0}
    if len(usable) < 8 or len(usable) < len(frames) * cfg["V2_LANDMARK_MIN_RATIO"]:
        return failure
    if any(b[0] - a[0] > cfg["V2_LANDMARK_MAX_GAP_MS"] for a, b in zip(usable, usable[1:])):
        return failure
    state, opened, closed_at, previous = 'waiting', 0, None, None
    count = 0
    for stamp, ratios in values:
        if ratios is None or (previous is not None and stamp - previous > cfg["V2_LANDMARK_MAX_GAP_MS"]):
            state, opened, closed_at = 'waiting', 0, None
        previous = stamp
        if ratios is None:
            continue
        is_open = min(ratios) >= cfg["V2_EAR_OPEN"]
        is_closed = max(ratios) <= cfg["V2_EAR_CLOSED"]
        if state == 'closed' and stamp - closed_at > cfg["V2_BLINK_MAX_CLOSED_MS"]:
            state, opened = 'waiting', 0
        if is_open:
            if state == 'closed':
                if cfg["V2_BLINK_MIN_CLOSED_MS"] <= stamp - closed_at <= cfg["V2_BLINK_MAX_CLOSED_MS"]:
                    count += 1
                state, opened = 'waiting', 0
            opened += 1
            if opened >= 2:
                state = 'open'
        elif is_closed:
            opened = 0
            if state == 'open':
                state, closed_at = 'closed', stamp
        elif state == 'waiting':
            opened = 0
    series = np.array([np.mean(ratios) for _, ratios in usable])
    baseline = float(np.median(series))
    dip = max(0.0, (baseline - float(series.min())) / baseline * 100) if baseline > 0 else 0.0
    if not count:
        return {"ok": False, "reason": "no_blink", "blinkCount": 0, "dipPercent": round(dip, 1)}
    return {"ok": True, "blinkScore": 90 if count <= 2 else 70,
            "blinkCount": count, "dipPercent": round(dip, 1), "evidenceFrames": len(usable),
            'gateEvidence': {'completed': True, 'cycles': count, 'samples': len(usable), 'totalFrames': len(frames),
                             'maxGapMs': max(b[0] - a[0] for a, b in zip(usable, usable[1:]))}}


def score_openness(values, dip_percent=None, return_percent=None):
    if dip_percent is None:
        dip_percent = current_app.config["BLINK_DIP_PERCENT"]
    if return_percent is None:
        return_percent = current_app.config["BLINK_RETURN_PERCENT"]
    series = _smooth(np.asarray(values, dtype=np.float64).reshape(-1))
    if series.size == 0:
        return {"ok": False, "reason": "no_blink", "blinkCount": 0, "dipPercent": 0.0}
    median = float(np.median(series))
    if median <= 0:
        return {"ok": False, "reason": "no_blink", "blinkCount": 0, "dipPercent": 0.0}
    dip_line = median * (1 - dip_percent / 100)
    back_line = median * (1 - return_percent / 100)
    blinks = _count_blinks(series, dip_line, back_line)
    dip_percent_seen = max(0.0, (median - float(series.min())) / median * 100)
    if blinks == 0:
        return {
            "ok": False,
            "reason": "no_blink",
            "blinkCount": 0,
            "dipPercent": round(dip_percent_seen, 1),
        }
    score = 90 if blinks <= 2 else 70
    return {
        "ok": True,
        "blinkScore": score,
        "blinkCount": blinks,
        "dipPercent": round(dip_percent_seen, 1),
    }


def score_pre_flash(frames, flash_start_ms):
    window = current_app.config["FLASH_DURATION_MS"]
    flash_end = flash_start_ms + window
    openness = []
    for stamp, image in frames:
        if flash_start_ms <= stamp < flash_end:
            continue
        reason, face = detect_faces(image)
        if reason == "model_missing":
            return {"ok": False, "reason": "model_missing", "blinkCount": 0, "dipPercent": 0.0}
        if reason or face is None:
            continue
        signal = _eye_signal(image, face)
        if signal is None:
            continue
        openness.append(signal)
    if len(openness) < 8:
        return {"ok": False, "reason": "no_face", "blinkCount": 0, "dipPercent": 0.0}
    return score_openness(openness)


def eye_openness(face_crop):
    height = face_crop.shape[0]
    top = int(height * 0.25)
    bottom = max(top + 2, int(height * 0.45))
    band = face_crop[top:bottom]
    return _gradient(band)


def _eye_signal(image, face_row):
    row = np.asarray(face_row, dtype=np.float32).reshape(-1)
    if row.size >= 8:
        span_x = max(6, int(float(row[2]) * 0.12))
        span_y = max(4, int(float(row[3]) * 0.08))
        samples = []
        for ex, ey in ((float(row[4]), float(row[5])), (float(row[6]), float(row[7]))):
            value = _patch_gradient(image, ex, ey, span_x, span_y)
            if value is not None:
                samples.append(value)
        if samples:
            return float(np.mean(samples))
    crop = _crop(image, row)
    if crop is None:
        return None
    return eye_openness(crop)


def _patch_gradient(image, center_x, center_y, span_x, span_y):
    height, width = image.shape[:2]
    x0 = max(0, int(center_x) - span_x)
    y0 = max(0, int(center_y) - span_y)
    x1 = min(width, int(center_x) + span_x)
    y1 = min(height, int(center_y) + span_y)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return _gradient(image[y0:y1, x0:x1])


def _gradient(band):
    if band is None or band.size == 0:
        return 0.0
    gray = band if band.ndim == 2 else cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    gradient = np.abs(np.diff(gray.astype(np.float32), axis=0))
    if gradient.size == 0:
        return 0.0
    return float(gradient.mean())


def _smooth(values):
    if values.size < 3:
        return values
    smoothed = values.copy()
    smoothed[1:-1] = (values[:-2] + values[1:-1] + values[2:]) / 3
    return smoothed


def _count_blinks(series, dip_line, back_line):
    count = 0
    index = 0
    size = series.size
    while index < size:
        if series[index] <= dip_line:
            end = index + 1
            while end < size and series[end] < back_line:
                end += 1
            count += 1
            if end >= size:
                break
            index = end
        else:
            index += 1
    return count


def _crop(image, face_row):
    row = np.asarray(face_row, dtype=np.float32).reshape(-1)
    x, y, width, height = [int(v) for v in row[:4]]
    x = max(0, x)
    y = max(0, y)
    crop = image[y : y + max(1, height), x : x + max(1, width)]
    if crop.size == 0 or crop.shape[0] < 8:
        return None
    return crop
