import contextlib
import io
import sys
import tempfile
import uuid
from pathlib import Path

import bcrypt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Config

_TMP = tempfile.NamedTemporaryFile(prefix="authx-smoke-", suffix=".db", delete=False)
_TMP.close()
Config.DATABASE_PATH = Path(_TMP.name)

from app import create_app
from app.models import save_face_embedding, save_look, save_voice
from app.services.face_detector import cosine_to_score, enroll_image, models_ready, score_vectors
from app.services.flash import score_brightness
from app.services.liveness import score_openness
from app.services.lipsync import score_mouth
from app.services.risk_engine import fuse
from app.services.voice_detector import combine_voice, score_wave


def main():
    hidden = io.StringIO()
    with contextlib.redirect_stdout(hidden):
        app = create_app()
    try:
        _scores(app)
        _http(app)
    finally:
        Path(_TMP.name).unlink(missing_ok=True)
    print("smoke ok")


def _scores(app):
    with app.app_context():
        same = np.zeros(128, dtype=np.float32)
        same[0] = 1
        other = np.zeros(128, dtype=np.float32)
        other[1] = 1
        _check(score_vectors(same, same) == 95, "identical vectors score 95")
        _check(score_vectors(same, other) < 20, "different vectors score under 20")
        _check(cosine_to_score(0) == 0, "zero cosine scores 0")
        _check(models_ready(), "both model files load")
        reason, feature = enroll_image(np.zeros((120, 120, 3), dtype=np.uint8))
        _check(reason == "no_face" and feature is None, "blank image returns no_face")
        saved = app.config["YUNET_PATH"]
        app.config["YUNET_PATH"] = ROOT / "models" / "missing.onnx"
        try:
            missing, _ = enroll_image(np.zeros((120, 120, 3), dtype=np.uint8))
        finally:
            app.config["YUNET_PATH"] = saved
        _check(missing == "model_missing", "missing model returns model_missing")

        flat = score_openness([80.0] * 12)
        _check(flat["ok"] is False and flat["reason"] == "no_blink", "flat eyes return no_blink")
        valley = score_openness([100.0] * 8 + [40.0] * 4 + [100.0] * 8)
        _check(valley["ok"] is True and valley["blinkScore"] == 90, "one blink valley scores 90")

        jump = score_brightness([(1700, 100), (1900, 100), (2100, 108), (2300, 108)], 2000)
        still = score_brightness([(1700, 100), (1900, 100), (2100, 100), (2300, 100)], 2000)
        early = score_brightness(
            [(1000, 50), (1200, 200), (1700, 100), (1900, 100), (2100, 100), (2300, 100)],
            2000,
        )
        _check(jump["flashScore"] == 90, "8 percent flash jump scores 90")
        _check(still["flashScore"] == 25, "flat flash scores 25")
        _check(early["flashScore"] == 25, "jump before the window scores 25")

        rate = 16000
        silence = score_wave(np.zeros(rate), rate)
        hum = 0.2 * np.sin(2 * np.pi * 100 * np.arange(rate) / rate)
        quiet = score_wave(hum, rate)
        constant = 0.2 * np.sin(2 * np.pi * 1000 * np.arange(rate) / rate)
        chunks = []
        for freq in (400, 800, 1200, 1800, 600, 2000, 900, 1500, 500, 2200):
            count = rate // 10
            chunks.append(0.2 * np.sin(2 * np.pi * freq * np.arange(count) / rate))
        varied = score_wave(np.concatenate(chunks), rate)
        steady = score_wave(constant, rate)
        _check(silence["acousticScore"] == 10 and silence["detail"] == "silence", "silence scores 10")
        _check(quiet["acousticScore"] == 10 and quiet["detail"] == "not_speech", "low speech band scores 10")
        _check(varied["acousticScore"] > steady["acousticScore"], "a varying tone scores above a constant tone")

        still_mouth = score_mouth([5.0] * 8, list(range(8)))
        moving = [0.0, 8.0, 1.0, 9.0, 0.5, 8.5, 0.2, 9.2]
        matched = score_mouth(moving, moving)
        _check(still_mouth["lipScore"] == 20, "a still mouth scores 20")
        _check(matched["lipScore"] == 90, "mouth motion that follows the envelope scores 90")
        _check(combine_voice(80, 40) == 70.0, "combined voice is 0.75 acoustic plus 0.25 lip")

        safe = fuse(95, 90, 90, 50)
        capped = fuse(40, 90, 90, 90)
        fake = fuse(15, 70, 10, 25)
        _check(safe["trustScore"] == 92 and safe["riskLabel"] == "SAFE", "safe fixture")
        _check(capped["trustScore"] == 74 and capped["riskLabel"] == "SUSPICIOUS", "face cap fixture")
        _check(fake["trustScore"] == 22 and fake["riskLabel"] == "DEEPFAKE", "deepfake fixture")


def _http(app):
    _set_password(app)
    client = app.test_client()
    health = client.get("/api/health")
    _check(health.status_code == 200 and health.get_json()["name"] == "AuthX", "health")

    bad = client.post("/api/auth/login", json={"username": "avinash", "password": "wrong-password"})
    _check(bad.status_code == 401, "wrong password rejected")
    signed = client.post("/api/auth/login", json={"username": "avinash", "password": _PASSWORD})
    body = signed.get_json()
    _check(signed.status_code == 200 and body["role"] == "student" and body.get("token"), "student login")
    token = body["token"]
    faculty_block = client.get("/api/faculty/sessions", headers=_auth(token))
    _check(faculty_block.status_code == 403, "student token rejected on a faculty route")

    hidden = io.StringIO()
    with contextlib.redirect_stdout(hidden):
        otp = client.post("/api/auth/login", json={"username": "sriram", "password": _PASSWORD})
    _check(otp.status_code == 200 and otp.get_json().get("otp_required") is True, "faculty login waits for OTP")

    started = client.post("/api/session/start", headers=_auth(token))
    _check(started.status_code == 422 and started.get_json()["reason"] == "not_enrolled", "start without a face")

    with app.app_context():
        save_face_embedding(_user_id("avinash"), "[0.1]")
    started = client.post("/api/session/start", headers=_auth(token))
    payload = started.get_json()
    _check(started.status_code == 200, "session start")
    uuid.UUID(payload["sessionId"])
    _check(payload["word"] in app.config["CHALLENGE_WORDS"], "session word")
    _check(1900 <= payload["flashStartMs"] <= 2400, "flash start window")

    first = _finish(client, token, payload, 95, 90, 90, 50, 92, "SAFE")
    second_start = client.post("/api/session/start", headers=_auth(token))
    second_payload = second_start.get_json()
    second = _finish(client, token, second_payload, 40, 90, 90, 90, 74, "SUSPICIOUS")
    _check(second["prevHash"] == first["blockHash"], "second certificate links to the first block")
    _check(first["prevHash"] == "GENESIS", "first previous hash is GENESIS")

    page = client.get("/certificate/" + first["certId"])
    html = page.get_data(as_text=True)
    _check(page.status_code == 200, "certificate page")
    _check(payload["word"] in html and str(payload["flashStartMs"]) in html, "certificate shows word and flash time")
    _check("intact" in html, "certificate chain is intact")

    bad_image = client.post("/api/face/enroll", json={"image": 1}, headers=_auth(token))
    _check(bad_image.status_code == 400 and bad_image.get_json()["reason"] == "bad_image", "bad enroll image")
    bad_wav = client.post("/api/voice/score", json={"wav": 1}, headers=_auth(token))
    _check(bad_wav.status_code == 400 and bad_wav.get_json()["reason"] == "bad_wav", "bad voice upload")

    page = client.get("/faculty/session/" + payload["sessionId"])
    leaked = page.get_data(as_text=True)
    _check(page.status_code == 200 and "0.7" not in leaked and "Checking sign-in" in leaked, "faculty page hides scores")
    student_detail = client.get("/api/faculty/sessions/" + payload["sessionId"], headers=_auth(token))
    _check(student_detail.status_code == 403, "student cannot read a faculty session")


def _finish(client, token, payload, face, blink, voice, flash, trust, label):
    session_id = payload["sessionId"]
    save_look(
        session_id,
        {
            "faceScore": face,
            "cosine": 0.7,
            "blinkScore": blink,
            "blinkCount": 1,
            "flashScore": flash,
            "reflectionDelta": 0.1,
            "reflectionR": 0.4,
            "detailJson": "{}",
        },
    )
    save_voice(
        session_id,
        {
            "acousticScore": voice,
            "lipScore": voice,
            "lipR": 0.5,
            "voiceScore": voice,
            "detail": {"rms": 0.05, "speechRatio": 0.6, "mfccVariation": 40},
        },
    )
    scored = client.post(f"/api/session/{session_id}/trust", headers=_auth(token))
    data = scored.get_json()
    _check(
        scored.status_code == 200 and data["trustScore"] == trust and data["riskLabel"] == label,
        f"fusion {label}",
    )
    issued = client.post(f"/api/session/{session_id}/certificate", headers=_auth(token))
    cert = issued.get_json()
    _check(issued.status_code == 200 and cert["certId"].startswith("AX-"), f"certificate {label}")
    return cert


def _set_password(app):
    conn_path = app.config["DATABASE_PATH"]
    digest = bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt()).decode()
    from app.models import connect

    conn = connect(conn_path)
    try:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username IN ('avinash', 'sriram', 'vaibhav')",
            (digest,),
        )
        conn.commit()
    finally:
        conn.close()


def _user_id(username):
    from app.models import get_user_by_username

    return get_user_by_username(username)["id"]


def _auth(token):
    return {"Authorization": "Bearer " + token, "Content-Type": "application/json"}


def _check(condition, name):
    if not condition:
        print("FAIL", name)
        raise SystemExit(1)
    print("ok", name)


_PASSWORD = "smoke-pass"


if __name__ == "__main__":
    main()
