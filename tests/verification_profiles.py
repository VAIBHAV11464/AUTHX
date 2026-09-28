"""Task 4 regression checks. All writes use temporary SQLite databases."""

import base64
import contextlib
import hashlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

import jwt
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Config
from app import create_app
from app.models import (
    connect, create_session, get_session, get_user_by_username,
    init_db, save_face_embedding, save_look, save_voice,
)
from app.services import verification_profiles as profiles
from app.services.certificate import chain_status, issue_certificate
from app.services.risk_engine import fuse
import speech_fixture
import gate_fixture


LOOK = {
    "ok": True, "faceScore": 95, "cosine": 0.7, "blinkScore": 90,
    "blinkCount": 1, "dipPercent": 60, "flashScore": 90,
    "reflectionDelta": .1, "reflectionR": .8, "detailJson": json.dumps(gate_fixture.look_detail()),
}
SPEAK = {
    "ok": True, "acousticScore": 90, "lipScore": 90, "lipR": 0.5,
    "voiceScore": 90, "speakCosine": .7,
    "detail": {"rms": 0.05, "speechRatio": 0.6, "mfccVariation": 40},
}


class ProfileTests(unittest.TestCase):
    def setUp(self):
        speech_fixture.install(self)
        self.temp = tempfile.TemporaryDirectory(prefix="authx-profiles-")
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "test.db"
        settings = patch.multiple(Config, DATABASE_PATH=self.db, VERIFICATION_PROFILE="legacy")
        settings.start()
        self.addCleanup(settings.stop)
        with contextlib.redirect_stdout(io.StringIO()):
            self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.user = get_user_by_username("avinash")
        save_face_embedding(self.user["id"], "[0.1]")
        self.headers = self._auth(self.user)

    def _auth(self, user):
        token = jwt.encode({"sub": str(user["id"])}, self.app.config["JWT_SECRET"], algorithm="HS256")
        return {"Authorization": "Bearer " + token}

    def _start(self, **kwargs):
        response = self.client.post("/api/session/start", headers=self.headers, **kwargs)
        self.assertEqual(response.status_code, 200)
        return response.get_json()["sessionId"]

    def _snapshot(self, db_path=None):
        conn = connect(db_path)
        try:
            return {
                table: [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
                for table in ("users", "sessions", "results", "certificates", "otps")
            }
        finally:
            conn.close()

    def test_default_and_server_selected_profile(self):
        session_id = self._start(json={"verification_profile": "v2", "verificationVersion": "v2"})
        self.assertEqual(get_session(session_id)["verification_profile"], "legacy")
        self.app.config["VERIFICATION_PROFILE"] = "v2"
        second = self._start(json={"verification_profile": "legacy"})
        self.assertEqual(get_session(second)["verification_profile"], "v2")
        self.assertEqual(get_session(session_id)["verification_profile"], "legacy")

    def test_direct_creation_preserves_old_signature_and_default(self):
        Config.VERIFICATION_PROFILE = "v2"
        session_id = create_session(self.user["id"], "amber", 2000, self.db)
        self.assertEqual(get_session(session_id)["verification_profile"], "legacy")
        second = create_session(self.user["id"], "amber", 2000, self.db, verification_profile="v2")
        self.assertEqual(get_session(second)["verification_profile"], "v2")

    def test_invalid_profile_rejected_before_startup_database_access(self):
        for value in ("V2", "unknown", "", None, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                profiles.get_profile(value)
        with patch.object(Config, "VERIFICATION_PROFILE", "unknown"), patch("app.init_db") as initialize:
            with self.assertRaises(ValueError):
                create_app()
            initialize.assert_not_called()
        with self.assertRaises(ValueError):
            create_session(self.user["id"], "amber", 2000, verification_profile="unknown")
        self.assertEqual(self._snapshot()["sessions"], [])

    def test_database_profile_constraints(self):
        conn = connect()
        try:
            for value in (None, "unknown"):
                with self.subTest(value=value), self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(
                        "INSERT INTO sessions (id, user_id, challenge_word, flash_start_ms, started_at, "
                        "verification_profile) VALUES (?, ?, 'amber', 2000, 'fixture', ?)",
                        ("bad-profile", self.user["id"], value),
                    )
        finally:
            conn.close()

    def test_additive_migration_and_idempotency_preserve_legacy_data(self):
        session_id = self._start()
        save_look(session_id, LOOK)
        save_voice(session_id, SPEAK)
        self.client.post(f"/api/session/{session_id}/trust", headers=self.headers)
        with self.app.app_context():
            cert = issue_certificate(session_id)
        self._start()  # Also exercise an unfinished historical attempt.
        conn = connect()
        try:
            # Recreate the pre-Task-4 sessions schema in this temporary database.
            conn.execute("ALTER TABLE sessions DROP COLUMN verification_profile")
            conn.commit()
        finally:
            conn.close()
        before = self._snapshot()
        Config.VERIFICATION_PROFILE = "v2"
        init_db()
        after = self._snapshot()
        for row in after["sessions"]:
            self.assertEqual(row.pop("verification_profile"), "legacy")
        self.assertEqual(after, before)
        once = self._snapshot()
        init_db()
        self.assertEqual(self._snapshot(), once)
        with self.app.app_context():
            self.assertEqual(chain_status(cert["cert_id"]), "intact")
        conn = connect()
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            conn.close()

    def test_all_scoring_steps_use_stored_profile_after_switch_and_restart(self):
        image = io.BytesIO()
        Image.new("RGB", (64, 64)).save(image, format="JPEG")
        frames = [
            {"tMs": stamp, "image": base64.b64encode(image.getvalue()).decode()}
            for stamp in range(0, 3000, 200)
        ]
        wav = io.BytesIO()
        with wave.open(wav, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(b"\0\0" * 48000)
        audio = {"wav": base64.b64encode(wav.getvalue()).decode(), "frames": frames}
        for starting, switched in (("legacy", "v2"), ("v2", "legacy")):
            with self.subTest(starting=starting):
                self.app.config["VERIFICATION_PROFILE"] = starting
                session_id = self._start()
                Config.VERIFICATION_PROFILE = switched
                self.app = create_app()
                self.app.config["TESTING"] = True
                self.client = self.app.test_client()
                self.assertEqual(get_session(session_id)["verification_profile"], starting)
                selected = profiles.VerificationProfile(
                    starting, Mock(return_value=LOOK), Mock(return_value={**SPEAK, 'detail': {
                        **SPEAK['detail'], **gate_fixture.speak_detail(get_session(session_id)['challenge_word'])}}),
                    Mock(wraps=profiles.get_profile(starting).fuse)
                )
                # Fail loudly if any step resolves the current global setting.
                wrong = Mock(side_effect=AssertionError("attempt switched profile"))
                other = profiles.VerificationProfile(switched, wrong, wrong, wrong)
                with patch.object(profiles, "_PROFILES", {starting: selected, switched: other}):
                    looked = self.client.post(f"/api/session/{session_id}/look", headers=self.headers, json={"frames": frames})
                    self.assertEqual(looked.status_code, 200)
                    self.app.config["VERIFICATION_PROFILE"] = switched
                    spoken = self.client.post(f"/api/session/{session_id}/speak", headers=self.headers, json=audio)
                    self.assertEqual(spoken.status_code, 200)
                    self.app.config["VERIFICATION_PROFILE"] = "invalid-for-new-attempts"
                    trust = self.client.post(f"/api/session/{session_id}/trust", headers=self.headers)
                    self.assertEqual(trust.status_code, 200)
                    self.assertEqual(trust.get_json()["trustScore"], 100)
                    selected.score_look.assert_called_once()
                    selected.score_speak.assert_called_once()
                    selected.fuse.assert_called_once()
                    wrong.assert_not_called()
                issued = self.client.post(f"/api/session/{session_id}/certificate", headers=self.headers)
                self.assertEqual(issued.status_code, 200)

    def test_existing_database_migration_on_temporary_backup(self):
        original = ROOT / "authx.db"
        if not original.is_file():
            self.skipTest("no existing database to clone")
        original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
        clone = Path(self.temp.name) / "existing-copy.db"
        with contextlib.closing(sqlite3.connect(original.as_uri() + "?mode=ro", uri=True)) as source, \
                contextlib.closing(sqlite3.connect(clone)) as destination:
            source.backup(destination)
        before = self._snapshot(clone)
        with patch.object(Config, "DATABASE_PATH", clone):
            chain_before = {row["cert_id"]: chain_status(row["cert_id"]) for row in before["certificates"]}
            with patch.object(Config, "VERIFICATION_PROFILE", "v2"):
                create_app()
            after = self._snapshot(clone)
            expected = {
                **before,
                "sessions": [
                    {**row, "verification_profile": row.get("verification_profile", "legacy"),
                     'speak_attempts': row.get('speak_attempts', 0),
                     'speak_token': row.get('speak_token'), 'speak_reserved_at': row.get('speak_reserved_at'),
                     'speak_last_evidence': row.get('speak_last_evidence'),
                     'attempt_generation': row.get('attempt_generation', 0),
                     'machine_trust_score': row.get('machine_trust_score'),
                     'machine_risk_label': row.get('machine_risk_label')}
                    for row in before["sessions"]
                ],
                "results": [{**row, "speak_cosine": row.get("speak_cosine")} for row in before["results"]],
            }
            self.assertTrue(after == expected, 'Additive migration must preserve every historical column/row')
            chain_after = {row["cert_id"]: chain_status(row["cert_id"]) for row in before["certificates"]}
            self.assertEqual(chain_after, chain_before)
            once = self._snapshot(clone)
            init_db()
            self.assertEqual(self._snapshot(clone), once)
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), original_hash)

    def test_reopen_keeps_starting_profile(self):
        self.app.config["VERIFICATION_PROFILE"] = "v2"
        session_id = self._start()
        save_look(session_id, LOOK)
        self.app.config["VERIFICATION_PROFILE"] = "legacy"
        faculty = self._auth(get_user_by_username("sriram"))
        response = self.client.post(f"/api/session/{session_id}/reopen", headers=faculty)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_session(session_id)["verification_profile"], "v2")
        self.assertEqual(self._snapshot()["results"], [])

    def test_legacy_look_results_and_failure_reasons(self):
        profile = profiles.get_profile("legacy")
        face = {"ok": True, "faceScore": 95, "cosine": 0.7}
        blink = {"ok": True, "blinkScore": 90, "blinkCount": 1, "dipPercent": 60}
        flash = {"ok": True, "flashScore": 50, "reflectionDelta": None, "reflectionR": None, "detail": "insufficient"}
        with patch.object(profiles, "match_pre_flash", return_value=face) as matcher, \
                patch.object(profiles, "score_pre_flash", return_value=blink) as blinker, \
                patch.object(profiles, "score_flash_frames", return_value=flash) as flasher:
            result = profile.score_look([], 2000, "[0.1]")
            self.assertEqual(result["faceScore"], 95)
            self.assertEqual(result["flashScore"], 50)
            self.assertEqual(json.loads(result["detailJson"]), {"dipPercent": 60, "flashDetail": "insufficient"})
            matcher.return_value = {"ok": False, "reason": "no_face"}
            self.assertEqual(profile.score_look([], 2000, "[0.1]")["reason"], "no_face")
            matcher.return_value = face
            blinker.return_value = {"ok": False, "reason": "no_blink"}
            self.assertEqual(profile.score_look([], 2000, "[0.1]")["reason"], "no_blink")
            blinker.return_value = blink
            flasher.return_value = {"ok": False, "reason": "model_missing"}
            self.assertEqual(profile.score_look([], 2000, "[0.1]")["reason"], "model_missing")

    def test_profiles_retain_legacy_risk_fusion(self):
        legacy, v2 = profiles.get_profile("legacy"), profiles.get_profile("v2")
        with self.app.app_context():
            audio = np.zeros(16000)
            self.assertEqual(legacy.score_speak([], audio, 16000)["voiceScore"], 20)
            for scores in ((95, 90, 90, 50), (40, 90, 90, 90), (15, 70, 10, 25)):
                self.assertEqual(v2.fuse(*scores, cosine=.7, speak_cosine=.7, **gate_fixture.fusion_options()), fuse(*scores))


if __name__ == "__main__":
    unittest.main(verbosity=2)
