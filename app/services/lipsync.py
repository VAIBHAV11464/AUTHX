import cv2
import numpy as np
from flask import current_app

from app.services.face_detector import detect_faces
from app.services.landmark_geometry import mouth_ratio


def score_landmark_lips(measured, samples, sample_rate, audio_start_ms=0):
    cfg = current_app.config
    audio = np.asarray(samples, dtype=np.float64).reshape(-1)
    failure = {"ok": False, "reason": "insufficient_lip_evidence", "lipScore": None,
               "lipR": None, "mouthVar": None, "detail": "insufficient_lip_evidence"}
    if sample_rate <= 0 or audio.size == 0 or not np.isfinite(audio).all():
        return failure
    mouth, energy, stamps = [], [], []
    half_ms = 40
    duration_ms = audio.size * 1000 / sample_rate
    for frame in measured:
        value = mouth_ratio(frame.points)
        audio_ms = frame.t_ms - audio_start_ms
        if value is None or not half_ms <= audio_ms <= duration_ms - half_ms:
            continue
        mouth.append(value)
        energy.append(frame_energy(audio, sample_rate, audio_ms, window_ms=2 * half_ms))
        stamps.append(frame.t_ms)
    if (len(mouth) < cfg["V2_LIP_MIN_SAMPLES"] or len(mouth) < len(measured) * cfg["V2_LANDMARK_MIN_RATIO"]
            or any(b - a > cfg["V2_LANDMARK_MAX_GAP_MS"] for a, b in zip(stamps, stamps[1:]))):
        return failure
    if float(np.max(energy)) < cfg["SILENCE_RMS"] or float(np.var(energy)) < cfg["V2_AUDIO_ENERGY_VAR_FLOOR"]:
        return failure
    variance = float(np.var(mouth))
    correlation = _pearson(mouth, energy)
    if variance < cfg["V2_MOUTH_VAR_FLOOR"]:
        result = _lip(20, round(correlation, 4), round(variance, 8), "still_mouth")
    else:
        score = 90 if correlation >= cfg["LIP_CORR_HIGH"] else 60 if correlation >= cfg["LIP_CORR_MID"] else 25
        result = _lip(score, round(correlation, 4), round(variance, 8), None)
    result["evidenceFrames"] = len(mouth)
    result['gateEvidence'] = {'usable': True, 'samples': len(mouth), 'totalFrames': len(measured),
                              'maxGapMs': max(b - a for a, b in zip(stamps, stamps[1:])),
                              'correlation': result['lipR'], 'mouthVariance': result['mouthVar']}
    return result


def score_mouth(openness, energy):
    cfg = current_app.config
    mouth = np.asarray(openness, dtype=np.float64).reshape(-1)
    loud = np.asarray(energy, dtype=np.float64).reshape(-1)
    if mouth.size < 8 or loud.size != mouth.size:
        return _lip(50, None, None, "too_few_lip_frames")
    variance = float(np.var(mouth))
    if variance < cfg["MOUTH_VAR_FLOOR"]:
        return _lip(20, round(_pearson(mouth, loud), 4), round(variance, 4), "still_mouth")
    correlation = _pearson(mouth, loud)
    if correlation >= cfg["LIP_CORR_HIGH"]:
        score = 90
    elif correlation >= cfg["LIP_CORR_MID"]:
        score = 60
    else:
        score = 25
    return _lip(score, round(correlation, 4), round(variance, 4), None)


def score_lip_frames(frames, samples, sample_rate):
    openness = []
    energy = []
    for stamp, image in frames:
        reason, face = detect_faces(image)
        if reason == "model_missing":
            return {
                "ok": False,
                "reason": "model_missing",
                "lipScore": None,
                "lipR": None,
                "mouthVar": None,
                "detail": "model_missing",
            }
        if reason or face is None:
            continue
        crop = _crop(image, face)
        if crop is None:
            continue
        openness.append(mouth_openness(crop))
        energy.append(frame_energy(samples, sample_rate, stamp))
    if len(openness) < 8:
        return _lip(50, None, None, "too_few_lip_frames")
    return score_mouth(openness, energy)


def mouth_openness(face_crop):
    height = face_crop.shape[0]
    top = int(height * 0.62)
    bottom = max(top + 2, int(height * 0.88))
    band = face_crop[top:bottom]
    gray = band if band.ndim == 2 else cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    gradient = np.abs(np.diff(gray.astype(np.float32), axis=0))
    if gradient.size == 0:
        return 0.0
    return float(gradient.mean())


def frame_energy(samples, sample_rate, t_ms, window_ms=25):
    audio = np.asarray(samples, dtype=np.float64).reshape(-1)
    center = int(t_ms / 1000 * sample_rate)
    half = max(1, int(window_ms / 1000 * sample_rate / 2))
    window = audio[max(0, center - half) : center + half]
    if window.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(window ** 2)))


def _lip(score, correlation, variance, detail):
    return {
        "ok": True,
        "lipScore": score,
        "lipR": correlation,
        "mouthVar": variance,
        "detail": detail,
    }


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
