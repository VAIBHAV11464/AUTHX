"""Task 9: Speak identity gates, routing and migration in temporary databases."""

import base64
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import uploads_quality as captures
from enrollment_matching import vector
from app.models import (
    connect, get_result, get_session, init_db, save_face_embedding, save_look, save_voice,
)
from app.services import face_matching, face_quality, verification_profiles as profiles
from app.services.certificate import chain_status
from app.services.risk_engine import fuse, fuse_v2
import speech_fixture
import gate_fixture


LOOK = {"faceScore": 100, "cosine": .8, "blinkScore": 100, "blinkCount": 1,
        "flashScore": 90, "reflectionDelta": .1, "reflectionR": .5,
        "detailJson": json.dumps({'dipPercent': 60, 'flashDetail': 'measured', **gate_fixture.look_detail()})}
ACOUSTIC = {"acousticScore": 100, "rms": .05, "speechRatio": .8,
            "mfccVariation": 40, "detail": "fixture"}
LIP = {"ok": True, "lipScore": 100, "lipR": .8, "mouthVar": .01, "detail": "fixture",
       'gateEvidence': gate_fixture.lip(), 'evidenceFrames': 58}


class SpeakIdentityTests(unittest.TestCase):
    setUp = captures.UploadTests.setUp
    start = captures.UploadTests.start

    def fixtures(self):
        image = np.random.default_rng(42).integers(70, 190, (128, 128, 3), dtype=np.uint8)
        face = np.array([0, 0, 128, 128, 40, 40, 88, 40, 64, 70, 45, 95, 85, 95, .8], dtype=np.float32)
        return image, face.reshape(1, 15)

    def clip(self):
        image, _ = self.fixtures()
        output = io.BytesIO()
        Image.fromarray(image[:, :, ::-1]).save(output, "PNG")
        encoded = base64.b64encode(output.getvalue()).decode()
        return {"frames": [{"tMs": i * 200, "image": encoded} for i in range(15)], "wav": captures.audio()}

    def begun(self, profile="v2", look_cosine=.8):
        self.app.config["VERIFICATION_PROFILE"] = profile
        save_face_embedding(self.user["id"], json.dumps(vector(scale=40).tolist()))
        session_id = self.start()
        save_look(session_id, {**LOOK, "cosine": look_cosine})
        return session_id

    def spoken(self, session_id, cosine):
        _, faces = self.fixtures()
        with patch.object(face_quality, "detect_all_faces", return_value=(None, faces)), \
                patch.object(face_matching, "embed_row", return_value=vector(cosine, scale=50)), \
                patch.object(profiles, "score_wave", return_value=ACOUSTIC), \
                patch.object(profiles, "score_lip_frames", return_value=LIP), \
                patch.object(profiles, "measure_landmarks", return_value=(None, [])), \
                patch.object(profiles, "score_landmark_lips", return_value=LIP):
            return self.client.post(f"/api/session/{session_id}/speak", headers=self.headers, json=self.clip())

    def trust(self, session_id, **kwargs):
        response = self.client.post(f"/api/session/{session_id}/trust", headers=self.headers, **kwargs)
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_changed_person_between_real_look_and_speak_cannot_get_safe(self):
        save_face_embedding(self.user["id"], json.dumps(vector(scale=40).tolist()))
        session_id = self.start()
        _, faces = self.fixtures()
        blink = {"ok": True, "blinkScore": 100, "blinkCount": 1, "dipPercent": 60}
        flash = {"ok": True, "flashScore": 90, "reflectionDelta": .1, "reflectionR": .5, "detail": "measured"}
        with patch.object(face_quality, "detect_all_faces", return_value=(None, faces)), \
                patch.object(face_matching, "embed_row", return_value=vector(.8)), \
                patch.object(profiles, "measure_landmarks", return_value=(None, [])), \
                patch.object(profiles, "score_landmark_blink", return_value=blink), \
                patch.object(profiles, "score_v2_flash", return_value=flash):
            response = self.client.post(f"/api/session/{session_id}/look", headers=self.headers, json=self.clip())
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.get_json()["cosine"], .363)
        self.assertEqual(self.spoken(session_id, .1).status_code, 200)
        row = get_result(session_id)
        self.assertAlmostEqual(row["speak_cosine"], .1)
        self.assertEqual(row["voice_score"], 100)
        self.assertEqual(self.trust(session_id)["riskLabel"], "SUSPICIOUS")
        issued = self.client.post(f"/api/session/{session_id}/certificate", headers=self.headers)
        self.assertEqual(issued.status_code, 200)
        cert_id = issued.get_json()["certId"]
        self.assertIn("SUSPICIOUS", self.client.get("/certificate/" + cert_id).get_data(as_text=True))
        self.assertEqual(chain_status(cert_id), "intact")

    def test_same_person_keeps_scores_response_fields_and_lock(self):
        session_id = self.begun()
        response = self.spoken(session_id, .8)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.get_json()), {"ok", "acousticScore", "lipScore", "lipR", "voiceScore",
                                                   "rms", "speechRatio", "mfccVariation",
                                                   'verificationVersion', 'evidence', 'retryable'})
        self.assertEqual(self.trust(session_id)["riskLabel"], "SAFE")
        self.assertEqual(self.spoken(session_id, .1).status_code, 409)
        self.assertAlmostEqual(get_result(session_id)["speak_cosine"], .8)

    def test_both_steps_require_raw_boundary_and_valid_cosines(self):
        invalid = (None, float("nan"), float("inf"), -float("inf"), "0.9", True, -.2, 1.01, .36296)
        for key in ("cosine", "speak_cosine"):
            for value in invalid:
                with self.subTest(key=key, value=value):
                    evidence = {"cosine": .8, "speak_cosine": .8, key: value}
                    result = fuse_v2(100, 100, 100, 90, **evidence, **gate_fixture.fusion_options())
                    self.assertEqual((result["trustScore"], result["riskLabel"]), (74, "SUSPICIOUS"))
        for value in (.363, .363001, 1):
            self.assertEqual(fuse_v2(100, 100, 100, 90, cosine=value, speak_cosine=value, **gate_fixture.fusion_options()), fuse(100, 100, 100, 90))
        self.assertEqual(fuse_v2(15, 70, 10, 25, cosine=.1, speak_cosine=.1), fuse(15, 70, 10, 25))

    def test_unrounded_speak_cosine_stored_and_client_cannot_override(self):
        session_id = self.begun()
        self.assertEqual(self.spoken(session_id, .36296).status_code, 200)
        stored = get_result(session_id)["speak_cosine"]
        self.assertLess(stored, .363)
        self.assertEqual(round(stored, 4), .363)
        self.assertEqual(self.trust(session_id, json={"cosine": 1, "speakCosine": 1, "speak_cosine": 1})["riskLabel"], "SUSPICIOUS")

    def test_missing_historical_speak_identity_fails_closed_only_in_v2(self):
        for profile, expected in (("v2", "SUSPICIOUS"), ("legacy", "SAFE")):
            session_id = self.begun(profile)
            scores = {"acousticScore": 100, "lipScore": 100, "lipR": .8, "voiceScore": 100,
                      "detail": {'speech': speech_fixture.evidence(get_session(session_id)['challenge_word'])}}
            save_voice(session_id, scores)
            self.assertIsNone(get_result(session_id)["speak_cosine"])
            self.assertEqual(self.trust(session_id)["riskLabel"], expected)

    def test_pinned_v2_checks_identity_after_global_switch(self):
        session_id = self.begun()
        self.app.config["VERIFICATION_PROFILE"] = "legacy"
        self.assertEqual(self.spoken(session_id, .1).status_code, 200)
        self.assertEqual(self.trust(session_id)["riskLabel"], "SUSPICIOUS")
        self.assertEqual(get_session(session_id)["verification_profile"], "v2")

    def test_pinned_legacy_never_matches_speak_even_after_global_switch(self):
        session_id = self.begun("legacy")
        self.app.config["VERIFICATION_PROFILE"] = "v2"
        with patch.object(profiles, "match_quality_frames") as match, \
                patch.object(profiles, "score_wave", return_value=ACOUSTIC), \
                patch.object(profiles, "score_lip_frames", return_value=LIP), \
                patch.object(profiles, "measure_landmarks", return_value=(None, [])), \
                patch.object(profiles, "score_landmark_lips", return_value=LIP):
            response = self.client.post(f"/api/session/{session_id}/speak", headers=self.headers, json=self.clip())
        self.assertEqual(response.status_code, 200)
        match.assert_not_called()
        self.assertIsNone(get_result(session_id)["speak_cosine"])
        self.assertEqual(self.trust(session_id)["riskLabel"], "SAFE")

    def test_speak_uses_full_clip_approved_frames_and_reuses_detections(self):
        image, faces = self.fixtures()
        dark = np.zeros_like(image)
        # Unusable early frames have higher confidence; matching must skip them.
        bad_faces = faces.copy()
        bad_faces[0, -1] = .99
        frames = [(i * 200, dark if i < 3 else image) for i in range(15)]
        detections = [(None, bad_faces)] * 3 + [(None, faces)] * 12
        approved = [(2600, image, faces[0]), (2800, image, faces[0]), (2400, image, faces[0])]
        # Boost the last three confidences to confirm no pre-flash cutoff.
        for index, (_, _, face) in enumerate(approved):
            selected = face.copy()
            selected[-1] = .9 + index * .01
            detections[int(approved[index][0] / 200)] = (None, selected.reshape(1, 15))
        with patch.object(face_quality, "detect_all_faces", side_effect=detections) as detect, \
                patch.object(face_matching, "embed_row", side_effect=[vector(.4), vector(.5), vector(.6)]) as embed, \
                patch.object(profiles, "score_wave", return_value=ACOUSTIC), \
                patch.object(profiles, "score_lip_frames", return_value=LIP), \
                patch.object(profiles, "measure_landmarks", return_value=(None, [])), \
                patch.object(profiles, "score_landmark_lips", return_value=LIP):
            result = profiles.get_profile("v2").score_speak(frames, np.zeros(48000), 16000, embedding=json.dumps(vector().tolist()), expected_word='amber')
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["speakCosine"], .5)
        self.assertEqual(detect.call_count, len(frames))
        self.assertEqual(embed.call_count, 3)
        for call in embed.call_args_list:
            self.assertIs(call.args[0], image)
            self.assertGreater(float(call.args[1][-1]), .89)

    def test_failures_leave_look_intact_and_speak_retryable(self):
        session_id = self.begun()
        before = dict(get_result(session_id))
        _, faces = self.fixtures()
        cases = [("no_face", ("no_face", None)),
                 ("multiple_faces", (None, np.vstack((faces, faces)))),
                 ("model_missing", ("model_missing", None))]
        for reason, detected in cases:
            with self.subTest(reason=reason), patch.object(face_quality, "detect_all_faces", return_value=detected), \
                    patch.object(profiles, "_legacy_speak") as acoustic:
                response = self.client.post(f"/api/session/{session_id}/speak", headers=self.headers, json=self.clip())
                self.assertEqual(response.status_code, 503 if reason == "model_missing" else 422)
                self.assertEqual(response.get_json()["reason"], reason)
                acoustic.assert_not_called()
                self.assertEqual(dict(get_result(session_id)), before)
        self.assertEqual(self.spoken(session_id, .8).status_code, 200)

    def test_invalid_embedding_or_model_feature_leaves_no_speak_evidence(self):
        session_id = self.begun()
        _, faces = self.fixtures()
        for stored in ("[0.1]", "null", json.dumps([0] * 128)):
            save_face_embedding(self.user["id"], stored)
            with patch.object(face_quality, "detect_all_faces", return_value=(None, faces)):
                response = self.spoken(session_id, .8)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.get_json()["reason"], "not_enrolled")
            self.assertIsNone(get_result(session_id)["voice_score"])
        save_face_embedding(self.user["id"], json.dumps(vector().tolist()))
        for feature, reason in (([0] * 128, "invalid_face_embedding"),
                                ([float("nan")] * 128, "invalid_face_embedding"),
                                (cv2.error("unavailable"), "model_missing")):
            with patch.object(face_quality, "detect_all_faces", return_value=(None, faces)), \
                    patch.object(face_matching, "embed_row", **({"side_effect": feature} if isinstance(feature, Exception) else {"return_value": feature})):
                response = self.client.post(f"/api/session/{session_id}/speak", headers=self.headers, json=self.clip())
            self.assertEqual(response.status_code, 503 if reason == "model_missing" else 422)
            self.assertEqual(response.get_json()["reason"], reason)
            self.assertIsNone(get_result(session_id)["speak_cosine"])

    def test_standalone_voice_keeps_quality_only_contract(self):
        _, faces = self.fixtures()
        # The standalone endpoint has no session and cannot produce trust/certificates.
        with patch.object(face_quality, "detect_all_faces", return_value=(None, faces)), \
                patch.object(face_matching, "embed_row") as embed, \
                patch.object(profiles, "score_wave", return_value=ACOUSTIC), \
                patch.object(profiles, "score_lip_frames", return_value=LIP), \
                patch.object(profiles, "measure_landmarks", return_value=(None, [])), \
                patch.object(profiles, "score_landmark_lips", return_value=LIP):
            response = self.client.post("/api/voice/score", headers=self.headers, json=self.clip())
        self.assertEqual(response.status_code, 200)
        embed.assert_not_called()
        self.assertEqual(set(response.get_json()), {"ok", "voiceScore", "acoustic", "lip"})

    def test_additive_speak_column_preserves_old_rows_and_certificates(self):
        session_id = self.begun("legacy")
        save_voice(session_id, {"acousticScore": 100, "lipScore": 100, "lipR": .8, "voiceScore": 100, "detail": {}})
        self.trust(session_id)
        issued = self.client.post(f"/api/session/{session_id}/certificate", headers=self.headers).get_json()
        with contextlib.closing(connect()) as conn:
            conn.execute("ALTER TABLE results DROP COLUMN speak_cosine")
            conn.commit()
        def snapshot():
            conn = connect()
            try:
                return {table: [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
                        for table in ("users", "sessions", "results", "certificates", "otps")}
            finally:
                conn.close()
        before = snapshot()
        init_db()
        after = snapshot()
        for row in after["results"]:
            self.assertIsNone(row.pop("speak_cosine"))
        self.assertEqual(before, after)
        once = snapshot()
        init_db()
        self.assertEqual(snapshot(), once)
        self.assertEqual(chain_status(issued["certId"]), "intact")


if __name__ == "__main__":
    unittest.main(verbosity=2)
