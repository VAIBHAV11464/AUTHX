"""Session-selected verification; v2 checks face identity in both steps."""

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable

from flask import current_app

from app.services.face_detector import match_pre_flash, detection_cache
from app.services.flash import score_flash_frames, score_v2_flash
from app.services.lipsync import score_lip_frames, score_mouth, score_landmark_lips
from app.services.liveness import score_pre_flash, score_landmark_blink
from app.services.landmarks import measure_clip as measure_landmarks, LandmarkFrame
from app.services.risk_engine import fuse, fuse_v2
from app.services.voice_detector import combine_voice, score_wave
from app.services.face_quality import inspect_clip
from app.services.face_matching import match_quality_frames
from app.services.speech import verify_word
from app.services.decision_evidence import capture_evidence, step_record


def _legacy_look(frames, flash_start_ms, embedding, *, face_result=None, blink_result=None, flash_result=None):
    face = match_pre_flash(frames, flash_start_ms, embedding) if face_result is None else face_result
    if not face["ok"]:
        return face
    blink = score_pre_flash(frames, flash_start_ms) if blink_result is None else blink_result
    if not blink["ok"]:
        return blink
    flash = score_flash_frames(frames, flash_start_ms) if flash_result is None else flash_result
    if not flash.get("ok", True):
        return {"ok": False, "reason": flash.get("reason") or "model_missing"}
    detail = {
        "dipPercent": blink["dipPercent"],
        "flashDetail": flash["detail"],
    }
    return {
        "ok": True,
        "faceScore": face["faceScore"],
        "cosine": face["cosine"],
        "blinkScore": blink["blinkScore"],
        "blinkCount": blink["blinkCount"],
        "dipPercent": blink["dipPercent"],
        "flashScore": flash["flashScore"],
        "reflectionDelta": flash["reflectionDelta"],
        "reflectionR": flash["reflectionR"],
        "detailJson": json.dumps(detail),
    }


def _legacy_speak(frames, samples, rate, *, lip_result=None):
    acoustic = score_wave(samples, rate)
    if lip_result is not None:
        lip = lip_result
    elif frames:
        lip = score_lip_frames(frames, samples, rate)
    else:
        lip = score_mouth([], [])
    if not lip.get("ok", True):
        return {"ok": False, "reason": lip.get("reason") or "lip_failed"}
    voice = combine_voice(acoustic["acousticScore"], lip["lipScore"])
    return {
        "ok": True,
        "acousticScore": acoustic["acousticScore"],
        "lipScore": lip["lipScore"],
        "lipR": lip["lipR"],
        "voiceScore": voice,
        "acoustic": acoustic,
        "lip": lip,
        "detail": {
            "rms": acoustic["rms"],
            "speechRatio": acoustic["speechRatio"],
            "mfccVariation": acoustic["mfccVariation"],
            "acousticDetail": acoustic["detail"],
            "mouthVar": lip["mouthVar"],
            "lipDetail": lip["detail"],
        },
    }


@dataclass(frozen=True)
class VerificationProfile:
    name: str
    score_look: Callable
    score_speak: Callable
    fuse: Callable


def _v2_look(frames, flash_start_ms, embedding):
    with detection_cache():
        face = match_quality_frames(frames, flash_start_ms, embedding)
        if not face["ok"]:
            return face
        reason, measured = _measure_approved([(stamp, image) for stamp, image in frames if stamp < flash_start_ms], face)
        if reason:
            return {"ok": False, "reason": reason}
        blink = score_landmark_blink(measured, flash_start_ms)
        if not blink["ok"]:
            return blink
        flash = score_v2_flash(frames, flash_start_ms)
        if not flash["ok"]:
            return flash
        result = _legacy_look(frames, flash_start_ms, embedding, face_result=face, blink_result=blink, flash_result=flash)
        if result["ok"]:
            detail = json.loads(result["detailJson"])
            detail.update(_measurement_versions())
            detail["lookMeasurement"] = _measurement_versions()
            detail.update(blinkEvidenceFrames=blink.get("evidenceFrames"), flashEvidenceFrames=flash.get("evidenceFrames"))
            detail['lookGateEvidence'] = step_record(capture_evidence(frames, face, flash_start_ms),
                                                      blink=blink.get('gateEvidence'), flash=flash.get('gateEvidence'))
            result["detailJson"] = json.dumps(detail)
        return result


def _measure_approved(frames, face):
    approved = face.get("approvedFrames")
    if approved is None:
        return measure_landmarks(frames)
    stamps = {stamp for stamp, _, _ in approved}
    reason, measured = measure_landmarks([(stamp, image) for stamp, image in frames if stamp in stamps])
    if reason:
        return reason, []
    by_stamp = {frame.t_ms: frame for frame in measured}
    # Preserve missing positions so a blink cannot bridge a rejected frame.
    return None, [by_stamp.get(stamp, LandmarkFrame(stamp, image, None, "face_quality")) for stamp, image in frames]


def score_quality_voice(frames, samples, rate, audio_start_ms=0):
    """Standalone v2 voice has quality/landmark checks, with no identity gate."""
    with detection_cache():
        reason, approved = inspect_clip(frames)
        if reason:
            return {"ok": False, "reason": reason}
        return _landmark_voice(frames, samples, rate, audio_start_ms, {"approvedFrames": approved})


def _measurement_versions():
    cfg = current_app.config
    return {"measurementVersion": "v2-landmarks-1", "mediapipeVersion": cfg["MEDIAPIPE_VERSION"],
            "landmarkModelSha256": cfg["LANDMARK_SHA256"],
            'faceDetectorModel': cfg['YUNET_PATH'].name, 'faceIdentityModel': cfg['SFACE_PATH'].name,
            'qualityConfig': {key: cfg[key] for key in cfg if key.startswith('V2_FACE_') or key.startswith('V2_IMAGE_')},
            "measurementConfig": {key: cfg[key] for key in (
                "V2_EAR_OPEN", "V2_EAR_CLOSED", "V2_BLINK_MIN_CLOSED_MS", "V2_BLINK_MAX_CLOSED_MS",
                "V2_LANDMARK_MAX_GAP_MS", "V2_LANDMARK_MIN_RATIO", "V2_LIP_MIN_SAMPLES", "V2_MOUTH_VAR_FLOOR",
                "V2_AUDIO_ENERGY_VAR_FLOOR", "V2_FLASH_MIN_SAMPLES", "V2_FLASH_MIN_SPAN_MS",
                "LIP_CORR_HIGH", "LIP_CORR_MID", "SILENCE_RMS", "FLASH_DELTA_HIGH", "FLASH_DELTA_MID",
                "FLASH_DURATION_MS", "V2_CAPTURE_FRAME_MS",
            )}}


def _landmark_voice(frames, samples, rate, audio_start_ms, face=None):
    reason, measured = _measure_approved(frames, face) if face is not None else measure_landmarks(frames)
    if reason:
        return {"ok": False, "reason": reason}
    lip = score_landmark_lips(measured, samples, rate, audio_start_ms)
    if not lip["ok"]:
        return lip
    scored = _legacy_speak(frames, samples, rate, lip_result=lip)
    if scored["ok"]:
        scored["detail"].update(_measurement_versions())
        scored["detail"]["speakMeasurement"] = _measurement_versions()
        scored["detail"].update(audioStartMs=audio_start_ms, lipEvidenceFrames=lip.get("evidenceFrames"))
        if face is not None:
            scored['detail']['speakGateEvidence'] = step_record(
                capture_evidence(frames, face, samples=samples, rate=rate, audio_start_ms=audio_start_ms), lip=lip.get('gateEvidence'))
    return scored


def _v2_speak(frames, samples, rate, *, embedding, expected_word, audio_start_ms=0):
    # Speak has no flash: match quality-approved frames from the whole clip.
    with detection_cache():
        face = match_quality_frames(frames, None, embedding)
        if not face["ok"]:
            return face
        scored = _landmark_voice(frames, samples, rate, audio_start_ms, face)
    if scored["ok"]:
        word = verify_word(samples, rate, expected_word)
        if not word['ok']:
            return word
        scored['detail']['speech'] = word['speech']
        scored["speakCosine"] = face["cosine"]
        scored["detail"]["audioStartMs"] = audio_start_ms
    return scored


_PROFILES = MappingProxyType({
    "legacy": VerificationProfile("legacy", _legacy_look, _legacy_speak, fuse),
    # Server-persisted measurement evidence controls machine SAFE eligibility.
    "v2": VerificationProfile("v2", _v2_look, _v2_speak, fuse_v2),
})


def get_profile(name):
    if not isinstance(name, str) or name not in _PROFILES:
        raise ValueError("VERIFICATION_PROFILE must be 'legacy' or 'v2'")
    return _PROFILES[name]
