import hashlib
import json
import secrets

from flask import current_app
from app.services.decision_evidence import stored_decision
from app.services.speech import stored_word_verified
from app.services.evidence_summary import session_fields, display_lines
from app.services.session_lifecycle import LifecycleError, require_live

from app.models import (
    _utc_now,
    get_certificate,
    connect,
    get_active_override,
    insert_certificate,
    list_certificates,
    revoke_certificate,
)

GENESIS = "GENESIS"


def issue_certificate(session_id, *, explain_failure=False):
    """One writer lock covers eligibility, immutable snapshot and chain append."""
    conn = connect()
    try:
        conn.execute('BEGIN IMMEDIATE')
        existing = conn.execute('SELECT * FROM certificates WHERE session_id = ?', (session_id,)).fetchone()
        if existing is not None:
            return existing  # Including revoked/old records; no new prerequisites or writes.
        session = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
        if session is None:
            return None
        require_live(session)
        result = conn.execute('SELECT * FROM results WHERE session_id = ?', (session_id,)).fetchone()
        if (session['status'] != 'scored' or result is None or session['trust_score'] is None
                or any(result[name] is None for name in ('face_score', 'blink_score', 'flash_score', 'voice_score'))):
            return None
        if session['verification_profile'] == 'v2':
            if not stored_word_verified(result['detail_json'], session['challenge_word']):
                if explain_failure:
                    raise LifecycleError('word_required')
                return None
            if stored_decision(result['detail_json']) is None:
                if explain_failure:
                    raise LifecycleError('evidence_required')
                return None
        previous = conn.execute('SELECT block_hash FROM certificates ORDER BY id DESC LIMIT 1').fetchone()
        prev_hash = previous['block_hash'] if previous is not None else GENESIS
        created_at = _utc_now()
        score_json = _score_json(session, result, override=get_active_override(session, connection=conn))
        digest = block_hash(prev_hash, session_id, session['trust_score'], created_at, score_json)
        cert_id = _new_id(conn)
        insert_certificate(session_id, cert_id, digest, prev_hash, score_json, created_at,
                           generation=session['attempt_generation'], connection=conn)
        issued = conn.execute('SELECT * FROM certificates WHERE cert_id = ?', (cert_id,)).fetchone()
        conn.commit()
        return issued
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def chain_status(cert_id):
    rows = list_certificates()
    expected = GENESIS
    status = {}
    intact = True
    for row in rows:
        digest = block_hash(
            row["prev_hash"],
            row["session_id"],
            _trust_text(row),
            row["created_at"],
            row["score_json"],
        )
        linked = row["prev_hash"] == expected and row["block_hash"] == digest
        intact = intact and linked
        status[row["cert_id"]] = "intact" if intact else "broken"
        expected = row["block_hash"]
    return status.get(cert_id, "broken")


def block_hash(prev_hash, session_id, trust_score, created_at, score_json):
    payload = f"{prev_hash}{session_id}{trust_score}{created_at}{score_json}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def revoke(cert_id):
    before = revoke_certificate(cert_id)
    if before is None:
        return None
    row = get_certificate(cert_id)
    return {
        "revoked": bool(row["revoked"]),
        "hashUnchanged": (row["block_hash"], row["prev_hash"]) == before,
    }


_UNSET = object()


def _score_json(session, result, *, override=_UNSET):
    detail = {}
    if result["detail_json"]:
        detail = json.loads(result["detail_json"])
    payload = {
        "word": session["challenge_word"],
        "flashStartMs": session["flash_start_ms"],
        "faceScore": result["face_score"],
        "cosine": result["cosine"],
        "blinkCount": result["blink_count"],
        "blinkScore": result["blink_score"],
        "lipR": result["lip_r"],
        "acousticScore": result["acoustic_score"],
        "lipScore": result["lip_score"],
        "voiceScore": result["voice_score"],
        "rms": detail.get("rms"),
        "speechRatio": detail.get("speechRatio"),
        "mfccVariation": detail.get("mfccVariation"),
        "riskLabel": session["risk_label"],
        "trustScore": session["trust_score"],
        "reflectionDelta": result["reflection_delta"],
        "reflectionR": result["reflection_r"],
    }
    if session['verification_profile'] == 'v2':
        fields = session_fields(session, result) if override is _UNSET else session_fields(session, result, override=override)
        fields['evidence']['lines'] = display_lines(fields)
        payload.update(verificationVersion=fields['verificationVersion'], evidence=fields['evidence'])
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _trust_text(row):
    try:
        payload = json.loads(row["score_json"])
        return payload["trustScore"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _new_id(connection):
    prefix = current_app.config["CERT_PREFIX"]
    for _ in range(5):
        cert_id = prefix + secrets.token_hex(4)
        if connection.execute('SELECT 1 FROM certificates WHERE cert_id = ?', (cert_id,)).fetchone() is None:
            return cert_id
    raise RuntimeError("cert_id_collision")
