import base64
import io
import json
import secrets
import sqlite3

import numpy as np
from flask import Blueprint, current_app, g, jsonify, request
from PIL import Image

from app.auth.decorators import role_required, token_required
from app.models import (
    clear_attempt,
    create_session,
    get_certificate,
    get_certificate_for_session,
    get_result,
    get_session,
    label_counts,
    list_admin_certificates,
    list_sessions,
    save_look,
    save_trust,
    save_voice,
    reserve_speak,
    finish_speak,
    session_detail,
    set_risk_label,
    get_active_override,
)
from app.services.session_lifecycle import LifecycleError, expired, require_live, failure_fields
from app.services.face_detector import models_ready
from app.services.verification_profiles import get_profile
from app.services.certificate import issue_certificate, revoke
from app.services.voice_detector import read_wav
from app.services import uploads
from app.services.speech import availability as speech_availability, stored_word_verified
from app.services.decision_evidence import evaluate_gates, decision_snapshot, stored_decision, object_json
from app.services.evidence_summary import session_fields, certificate_fields, display_lines

SETUP_REASONS = frozenset(('model_missing', 'landmark_model_missing', 'landmark_model_invalid',
                           'speech_model_missing', 'speech_model_invalid', 'speech_runtime_unavailable',
                           'speech_configuration_invalid', 'verification_unavailable'))
NON_CONSUMING_REASONS = SETUP_REASONS | {'not_enrolled', 'invalid_face_embedding'}

bp = Blueprint("verification", __name__)


@bp.errorhandler(LifecycleError)
def lifecycle_error(error):
    status = (404 if error.reason == 'not_found' else 403 if error.reason == 'forbidden'
              else 422 if error.reason in ('word_required', 'evidence_required', 'incomplete') else 409)
    fields = failure_fields(error.reason)
    if error.reason == 'word_required':
        fields['freshSessionRequired'] = True
    return jsonify(**fields), status


@bp.after_request
def add_evidence_fields(response):
    # Optional additions only after successful authentication/ownership checks.
    endpoints = {'verification.start', 'verification.look', 'verification.speak', 'verification.trust',
                 'verification.certificate', 'verification.faculty_session_api'}
    if request.endpoint not in endpoints or not response.is_json or response.status_code in (401, 403, 404):
        return response
    user = getattr(g, 'user', None)
    if user is None:
        return response
    data = response.get_json()
    session_id = (request.view_args or {}).get('session_id') or data.get('sessionId')
    session = get_session(session_id) if session_id else None
    if session is None or (request.endpoint != 'verification.faculty_session_api' and session['user_id'] != user['id']):
        return response
    issued = get_certificate_for_session(session_id) if request.endpoint == 'verification.certificate' and data.get('ok') else None
    fields = certificate_fields(issued['score_json']) if issued is not None else session_fields(session, get_result(session_id))
    fields['evidence']['lines'] = display_lines(fields)
    for key, value in fields.items():
        data.setdefault(key, value)
    response.set_data(current_app.json.dumps(data))
    return response


@bp.post("/api/session/start")
@token_required
def start():
    if not g.user["face_embedding"]:
        return jsonify(ok=False, reason="not_enrolled"), 422
    cfg = current_app.config
    span = cfg["FLASH_START_MAX_MS"] - cfg["FLASH_START_MIN_MS"]
    flash_start = cfg["FLASH_START_MIN_MS"] + secrets.randbelow(span + 1)
    word = secrets.choice(cfg["CHALLENGE_WORDS"])
    profile = get_profile(cfg["VERIFICATION_PROFILE"])
    session_id = create_session(
        g.user["id"], word, flash_start, verification_profile=profile.name
    )
    options = {"captureFrameMs": cfg["V2_CAPTURE_FRAME_MS"]} if profile.name == "v2" else {}
    return jsonify(ok=True, sessionId=session_id, word=word, flashStartMs=flash_start, **options)


@bp.post("/api/session/<session_id>/look")
@token_required
def look(session_id):
    session = get_session(session_id)
    if session is None:
        return jsonify(ok=False, reason="not_found"), 404
    if session["user_id"] != g.user["id"]:
        return jsonify(ok=False, error="forbidden"), 403
    require_live(session)
    if get_certificate_for_session(session_id) is not None:
        return jsonify(ok=False, reason='look_locked'), 409
    if not models_ready():
        return jsonify(ok=False, reason="model_missing"), 503
    if get_result(session_id) is not None:
        return jsonify(ok=False, reason="look_locked"), 409
    profile = get_profile(session["verification_profile"])
    if profile.name == "v2":
        try:
            frames = uploads.frames(request.get_json(silent=True))
        except uploads.UploadError as exc:
            return jsonify(ok=False, reason=exc.reason), 400
    else:
        frames = _frames_from_request()
    if frames is None:
        return jsonify(ok=False, reason="bad_frames"), 400
    scored = profile.score_look(frames, session["flash_start_ms"], g.user["face_embedding"])
    if not scored["ok"]:
        print(
            f"AuthX look {scored.get('reason')} dip={scored.get('dipPercent')} "
            f"blinks={scored.get('blinkCount')}",
            flush=True,
        )
        status = 503 if scored["reason"] in ("model_missing", "landmark_model_missing", "landmark_model_invalid") else 422
        return jsonify(ok=False, reason=scored["reason"]), status
    try:
        save_look(session_id, scored, generation=session['attempt_generation'])
    except sqlite3.IntegrityError:
        return jsonify(ok=False, reason="look_locked"), 409
    return jsonify(
        ok=True,
        faceScore=scored["faceScore"],
        cosine=scored["cosine"],
        blinkScore=scored["blinkScore"],
        blinkCount=scored["blinkCount"],
        dipPercent=scored["dipPercent"],
        flashScore=scored["flashScore"],
        reflectionDelta=scored["reflectionDelta"],
        reflectionR=scored["reflectionR"],
    )


@bp.post("/api/session/<session_id>/reopen")
@role_required("faculty", "admin")
def reopen(session_id):
    session = get_session(session_id)
    if session is None:
        return jsonify(ok=False, reason="not_found"), 404
    outcome = clear_attempt(session_id)
    if isinstance(outcome, str):
        return jsonify(ok=False, reason=outcome, retryable=False,
                       freshSessionRequired=outcome in ('speak_attempts_exhausted', 'session_expired')), 409
    if isinstance(outcome, dict):
        successor = get_session(outcome['sessionId'])
        return jsonify(ok=True, **outcome, word=successor['challenge_word'],
                       flashStartMs=successor['flash_start_ms'], verificationVersion=successor['verification_profile'])
    return jsonify(ok=True, sessionId=session_id, newSession=False)


@bp.get("/api/faculty/sessions")
@role_required("faculty", "admin")
def faculty_sessions():
    rows = []
    for row in list_sessions():
        rows.append(
            {
                "sessionId": row["id"],
                "username": row["username"],
                "word": row["challenge_word"],
                "flashStartMs": row["flash_start_ms"],
                "status": 'expired' if expired(row) else row["status"],
                "trustScore": row["trust_score"],
                "riskLabel": row["risk_label"],
                "startedAt": row["started_at"],
            }
        )
    return jsonify(ok=True, sessions=rows)


@bp.get("/api/faculty/sessions/<session_id>")
@role_required("faculty", "admin")
def faculty_session_api(session_id):
    detail = session_detail(session_id)
    if detail is None:
        return jsonify(ok=False, reason="not_found"), 404
    return jsonify(ok=True, **detail)


@bp.post("/api/faculty/sessions/<session_id>/override")
@role_required("faculty", "admin")
def override_label(session_id):
    if get_session(session_id) is None:
        return jsonify(ok=False, reason="not_found"), 404
    data = request.get_json(silent=True) or {}
    label = data.get("label")
    if label not in ("SAFE", "SUSPICIOUS", "DEEPFAKE"):
        return jsonify(ok=False, reason="bad_label"), 400
    set_risk_label(session_id, label, actor_id=g.user['id'])
    session = get_session(session_id)
    fields = session_fields(session, get_result(session_id))
    fields['evidence']['lines'] = display_lines(fields)
    return jsonify(ok=True, riskLabel=label, **fields)


@bp.get("/api/admin/summary")
@role_required("admin")
def admin_summary():
    certificates = []
    for row in list_admin_certificates():
        certificates.append(
            {
                "certId": row["cert_id"],
                "username": row["username"],
                "word": row["challenge_word"],
                "riskLabel": row["risk_label"],
                "revoked": bool(row["revoked"]),
            }
        )
    return jsonify(ok=True, counts=label_counts(), certificates=certificates)


@bp.post("/api/admin/certificates/<cert_id>/revoke")
@role_required("admin")
def admin_revoke(cert_id):
    before = get_certificate(cert_id)
    if before is None:
        return jsonify(ok=False, reason="not_found"), 404
    result = revoke(cert_id)
    return jsonify(
        ok=True,
        revoked=result["revoked"],
        hashUnchanged=result["hashUnchanged"],
    )


@bp.post("/api/session/<session_id>/speak")
@token_required
def speak(session_id):
    session = get_session(session_id)
    if session is None:
        return jsonify(ok=False, reason="not_found"), 404
    if session["user_id"] != g.user["id"]:
        return jsonify(ok=False, error="forbidden"), 403
    require_live(session)
    if get_certificate_for_session(session_id) is not None:
        return jsonify(ok=False, reason='speak_locked'), 409
    row = get_result(session_id)
    if row is None:
        return jsonify(ok=False, reason="look_required"), 422
    if row["voice_score"] is not None:
        return jsonify(ok=False, reason="speak_locked"), 409
    profile = get_profile(session["verification_profile"])
    if profile.name == "v2":
        if session['speak_attempts'] >= 4 and not session['speak_token']:
            return jsonify(ok=False, reason='speak_attempts_exhausted', attemptsUsed=4,
                           attemptsRemaining=0, retryable=False, freshSessionRequired=True), 409
        try:
            data = uploads.payload(request.get_json(silent=True))
            samples, rate = uploads.wav(data)
            frames = uploads.frames(data)
            audio_start_ms = uploads.audio_start_ms(data)
        except uploads.UploadError as exc:
            return jsonify(ok=False, reason=exc.reason), 400
    else:
        samples, rate, wav_error = _wav_from_request()
        if wav_error:
            return jsonify(ok=False, reason=wav_error), 400
        frames = _optional_frames()
    options = {"embedding": g.user["face_embedding"], "audio_start_ms": audio_start_ms,
               "expected_word": session['challenge_word']} if profile.name == "v2" else {}
    if profile.name == 'v2':
        ready = speech_availability()
        if not ready['ok']:
            return jsonify(ok=False, reason=ready['reason'], retryable=True), 503
        reservation = reserve_speak(session_id, g.user['id'])
        if not reservation['ok']:
            return jsonify(**reservation), 409 if reservation['reason'] != 'look_required' else 422
        try:
            scored = profile.score_speak(frames, samples, rate, **options)
            # A profile must supply genuine word evidence before a successful save.
            if scored['ok'] and not stored_word_verified(
                    json.dumps(scored.get('detail', {})), session['challenge_word']):
                scored = {'ok': False, 'reason': 'word_required'}
        except Exception:
            current_app.logger.exception('Speak measurement failed')
            scored = {'ok': False, 'reason': 'verification_unavailable'}
        outcome = finish_speak(session_id, reservation, scored, setup_failure=scored.get('reason') in NON_CONSUMING_REASONS)
        if not outcome['ok']:
            status = 503 if scored.get('reason') in SETUP_REASONS else 422
            if outcome['reason'] in ('speak_attempt_superseded', 'session_expired', 'session_certified'):
                status = 409
            return jsonify(**outcome), status
    else:
        scored = profile.score_speak(frames, samples, rate, **options)
    if not scored["ok"]:
        status = 503 if scored["reason"] in ("model_missing", "landmark_model_missing", "landmark_model_invalid") else 422
        return jsonify(ok=False, reason=scored["reason"]), status
    if profile.name == 'legacy':
        save_voice(session_id, scored, generation=session['attempt_generation'], result_id=row['id'])
    detail = scored["detail"]
    return jsonify(
        ok=True,
        acousticScore=scored["acousticScore"],
        lipScore=scored["lipScore"],
        lipR=scored["lipR"],
        voiceScore=scored["voiceScore"],
        rms=detail["rms"],
        speechRatio=detail["speechRatio"],
        mfccVariation=detail["mfccVariation"],
    )


@bp.post("/api/session/<session_id>/trust")
@token_required
def trust(session_id):
    session = get_session(session_id)
    if session is None:
        return jsonify(ok=False, reason="not_found"), 404
    if session["user_id"] != g.user["id"]:
        return jsonify(ok=False, error="forbidden"), 403
    require_live(session)
    row = get_result(session_id)
    if row is None or any(
        row[name] is None for name in ("face_score", "blink_score", "flash_score", "voice_score")
    ):
        return jsonify(ok=False, reason="incomplete"), 422
    profile = get_profile(session["verification_profile"])
    saved_machine = stored_decision(row['detail_json']) if profile.name == 'v2' else None
    if session['status'] in ('scored', 'certified') and (
            saved_machine or (profile.name == 'legacy' and session['machine_trust_score'] is not None)
            or get_certificate_for_session(session_id)):
        # Completed results are read without rescoring under today's configuration.
        detail = object_json(row['detail_json'])
        prior = saved_machine or (detail.get('legacyMachineDecision') if isinstance(detail, dict) else None) or {}
        return jsonify(ok=True, trustScore=session['trust_score'], riskLabel=session['risk_label'],
                       base=prior.get('base'), flashAdjust=prior.get('flashAdjust'))
    if profile.name == 'v2' and not stored_word_verified(row['detail_json'], session['challenge_word']):
        return jsonify(ok=False, reason='word_required'), 422
    options = {"cosine": row["cosine"], "speak_cosine": row["speak_cosine"],
               'detail_json': row['detail_json'], 'expected_word': session['challenge_word']} if profile.name == "v2" else {}
    scored = profile.fuse(row["face_score"], row["blink_score"], row["voice_score"], row["flash_score"], **options)
    machine = decision_snapshot(scored, evaluate_gates(**options)) if profile.name == 'v2' else None
    saved = save_trust(session_id, scored["trustScore"], scored["riskLabel"], machine_decision=machine,
               legacy_decision=scored if profile.name == 'legacy' else None,
               generation=session['attempt_generation'], result_id=row['id'])
    scored['riskLabel'] = saved['risk_label']
    scored['trustScore'] = saved['trust_score']
    recorded = get_result(session_id)
    detail = object_json(recorded['detail_json']) if recorded else {}
    prior = detail.get('machineDecision' if profile.name == 'v2' else 'legacyMachineDecision')
    if isinstance(prior, dict):
        scored.update(base=prior.get('base'), flashAdjust=prior.get('flashAdjust'))
    return jsonify(ok=True, **scored)


@bp.post("/api/session/<session_id>/certificate")
@token_required
def certificate(session_id):
    session = get_session(session_id)
    if session is None:
        return jsonify(ok=False, reason="not_found"), 404
    if session["user_id"] != g.user["id"]:
        return jsonify(ok=False, error="forbidden"), 403
    # Authoritative lifecycle/eligibility and existing-cert lookup happen under the writer lock.
    issued = issue_certificate(session_id, explain_failure=True)
    if issued is None:
        return jsonify(ok=False, reason="incomplete"), 422
    return jsonify(
        ok=True,
        certId=issued["cert_id"],
        prevHash=issued["prev_hash"],
        blockHash=issued["block_hash"],
    )


def _wav_from_request():
    data = request.get_json(silent=True) or {}
    raw = data.get("wav") or ""
    if not isinstance(raw, str):
        return None, None, "bad_wav"
    if "," in raw:
        raw = raw.split(",", 1)[1]
    if not raw:
        return None, None, "bad_wav"
    try:
        samples, rate = read_wav(base64.b64decode(raw))
    except Exception:
        return None, None, "bad_wav"
    return samples, rate, None


def _optional_frames():
    data = request.get_json(silent=True) or {}
    raw_frames = data.get("frames") or []
    if not isinstance(raw_frames, list):
        return []
    frames = []
    for item in raw_frames:
        if not isinstance(item, dict):
            continue
        image = _image(item.get("image") or "")
        if image is None:
            continue
        try:
            stamp = float(item.get("tMs"))
        except (TypeError, ValueError):
            continue
        frames.append((stamp, image))
    return frames


def _frames_from_request():
    data = request.get_json(silent=True) or {}
    raw_frames = data.get("frames")
    if not isinstance(raw_frames, list) or not raw_frames:
        return None
    frames = []
    for item in raw_frames:
        if not isinstance(item, dict):
            continue
        image = _image(item.get("image") or "")
        if image is None:
            continue
        try:
            stamp = float(item.get("tMs"))
        except (TypeError, ValueError):
            continue
        frames.append((stamp, image))
    if not frames:
        return None
    return frames


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
