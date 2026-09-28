import base64
import io

import numpy as np
from flask import Blueprint, current_app, jsonify, request
from PIL import Image

from app.auth.decorators import token_required
from app.services.lipsync import score_lip_frames, score_mouth
from app.services.voice_detector import combine_voice, read_wav, score_wave
from app.services.verification_profiles import get_profile, score_quality_voice
from app.services import uploads

bp = Blueprint("voice", __name__)


@bp.post("/api/voice/score")
@token_required
def score():
    profile = get_profile(current_app.config["VERIFICATION_PROFILE"])
    if profile.name == "v2":
        try:
            data = uploads.payload(request.get_json(silent=True))
            samples, rate = uploads.wav(data)
            frames = uploads.frames(data)
            audio_start_ms = uploads.audio_start_ms(data)
        except uploads.UploadError as exc:
            return jsonify(ok=False, reason=exc.reason), 400
        scored = score_quality_voice(frames, samples, rate, audio_start_ms)
        if not scored["ok"]:
            status = 503 if scored["reason"] in ("model_missing", "landmark_model_missing", "landmark_model_invalid") else 422
            return jsonify(ok=False, reason=scored["reason"]), status
        # Retain this standalone route's existing response structure.
        return jsonify(ok=True, voiceScore=scored["voiceScore"], acoustic=scored["acoustic"], lip=scored["lip"])
    data = request.get_json(silent=True) or {}
    raw = data.get("wav") or ""
    if not isinstance(raw, str):
        return jsonify(ok=False, reason="bad_wav"), 400
    if "," in raw:
        raw = raw.split(",", 1)[1]
    if not raw:
        return jsonify(ok=False, reason="bad_wav"), 400
    try:
        blob = base64.b64decode(raw)
        samples, rate = read_wav(blob)
    except Exception:
        return jsonify(ok=False, reason="bad_wav"), 400
    acoustic = score_wave(samples, rate)
    frames = data.get("frames") or []
    if not isinstance(frames, list):
        frames = []
    if frames:
        lip = score_lip_frames(_pairs(frames), samples, rate)
    else:
        lip = score_mouth([], [])
    if not lip.get("ok", True):
        status = 503 if lip.get("reason") == "model_missing" else 422
        return jsonify(ok=False, reason=lip.get("reason") or "lip_failed"), status
    voice = combine_voice(acoustic["acousticScore"], lip["lipScore"])
    return jsonify(ok=True, voiceScore=voice, acoustic=acoustic, lip=lip)


def _pairs(frames):
    pairs = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        image = _image(frame.get("image") or "")
        if image is None:
            continue
        try:
            stamp = float(frame.get("tMs") or 0)
        except (TypeError, ValueError):
            continue
        pairs.append((stamp, image))
    return pairs


def _image(raw):
    if not isinstance(raw, str):
        return None
    if "," in raw:
        raw = raw.split(",", 1)[1]
    if not raw:
        return None
    try:
        picture = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
    except Exception:
        return None
    array = np.asarray(picture)
    return array[:, :, ::-1].copy()
