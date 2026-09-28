"""Tasks 7/8 regression tests using temporary databases and synthetic vectors."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import uploads_quality as capture_tests
from uploads_quality import image64
from app.models import get_user_by_username, get_result, get_session, save_look, save_voice
import speech_fixture
import gate_fixture
from app.services import enrollment
from app.services import face_matching, face_quality, verification_profiles as profiles
from app.services.face_embedding import unit_vector
from app.services.risk_engine import fuse, fuse_v2


def vector(cosine=1.0, scale=1.0):
    result = np.zeros(128)
    result[0] = cosine
    result[1] = np.sqrt(max(0, 1 - cosine * cosine))
    return result * scale


class EnrollmentTests(unittest.TestCase):
    setUp = capture_tests.UploadTests.setUp

    def test_normalized_average_of_all_usable_samples(self):
        features = [vector(1, 100), vector(.98, 2), vector(.97, 50), vector(.99, 7), vector(.96, 3)]
        results = [(None, json.dumps(value.tolist())) for value in features]
        with patch.object(enrollment, "enroll_image", side_effect=results):
            reason, result = enrollment.enroll_samples([None] * 5)
        self.assertIsNone(reason)
        expected = unit_vector(np.mean([unit_vector(value) for value in features], axis=0))
        np.testing.assert_allclose(json.loads(result), expected, atol=1e-12)
        self.assertAlmostEqual(np.linalg.norm(json.loads(result)), 1.0)

    def test_three_good_samples_with_two_unusable_frames(self):
        good = (None, json.dumps(vector().tolist()))
        results = [good, ("face_blurry", None), good, ("face_too_dark", None), good]
        with patch.object(enrollment, "enroll_image", side_effect=results):
            reason, result = enrollment.enroll_samples([None] * 5)
        self.assertIsNone(reason)
        np.testing.assert_equal(json.loads(result), vector())
        with patch.object(enrollment, "enroll_image", side_effect=[good, good] + [("no_face", None)] * 3):
            self.assertEqual(enrollment.enroll_samples([None] * 5)[0], "too_few_enrollment_samples")

    def test_identity_disagreement_is_not_dropped_as_an_outlier(self):
        good = (None, json.dumps(vector().tolist()))
        other = (None, json.dumps(vector(0).tolist()))
        for results in ([good] * 4 + [other], [good] * 3 + [other] * 2):
            with patch.object(enrollment, "enroll_image", side_effect=results):
                self.assertEqual(enrollment.enroll_samples([None] * 5), ("inconsistent_enrollment", None))
        for reason in ("multiple_faces", "model_missing"):
            with patch.object(enrollment, "enroll_image", side_effect=[good] * 4 + [(reason, None)]):
                self.assertEqual(enrollment.enroll_samples([None] * 5), (reason, None))

    def test_invalid_feature_rejected_and_single_image_supported(self):
        for feature in ([], [1] * 127, [0] * 128, [float("nan")] * 128, [float("inf")] * 128, {"bad": "vector"}):
            with self.subTest(feature=str(feature)[:20]):
                self.assertIsNone(unit_vector(feature))
                with patch.object(enrollment, "enroll_image", return_value=(None, json.dumps(feature))):
                    self.assertEqual(enrollment.enroll_samples([None]), ("invalid_face_embedding", None))
        with patch.object(enrollment, "enroll_image", return_value=(None, json.dumps(vector(scale=90).tolist()))):
            reason, result = enrollment.enroll_samples([None])
            self.assertIsNone(reason)
            np.testing.assert_equal(json.loads(result), vector())

    def test_api_batch_and_single_image_save_compatible_vectors(self):
        raw = image64()
        for body in ({"images": [raw] * 5}, {"image": raw}):
            with patch.object(enrollment, "enroll_image", return_value=(None, json.dumps(vector(scale=50).tolist()))):
                response = self.client.post("/api/face/enroll", headers=self.headers, json=body)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), {"ok": True, "enrolled": True})
            np.testing.assert_equal(json.loads(get_user_by_username("avinash")["face_embedding"]), vector())

    def test_batch_input_validation_precedes_model_work(self):
        raw = image64()
        for body in ({"images": None}, {"images": raw}, {"images": [raw] * 4},
                     {"images": [raw] * 6}, {"images": [raw] * 5, "image": raw}, {"images": [raw] * 4 + ["%%%"]}):
            with patch.object(enrollment, "enroll_image") as scorer:
                response = self.client.post("/api/face/enroll", headers=self.headers, json=body)
                self.assertEqual(response.status_code, 400)
                scorer.assert_not_called()
                self.assertEqual(get_user_by_username("avinash")["face_embedding"], "[0.1]")

    def test_failed_reenrollment_preserves_embedding_and_timestamp(self):
        before = dict(get_user_by_username("avinash"))
        raw = image64()
        with patch.object(enrollment, "enroll_image", side_effect=[(None, json.dumps(vector().tolist()))] * 2 + [("no_face", None)] * 3):
            response = self.client.post("/api/face/enroll", headers=self.headers, json={"images": [raw] * 5})
        self.assertEqual(response.status_code, 422)
        after = dict(get_user_by_username("avinash"))
        self.assertEqual(after, before)

    def test_legacy_single_image_and_profile_specific_wizard_settings(self):
        for profile, count in (("legacy", 1), ("v2", 5)):
            self.app.config["VERIFICATION_PROFILE"] = profile
            html = self.client.get("/student").get_data(as_text=True)
            self.assertIn(f"enrollmentSamples: {count}", html)
        self.app.config["VERIFICATION_PROFILE"] = "legacy"
        with patch("app.routes.face.enroll_image", return_value=(None, "[0.1]")):
            response = self.client.post("/api/face/enroll", headers=self.headers, json={"image": image64()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_user_by_username("avinash")["face_embedding"], "[0.1]")


class MatchingTests(unittest.TestCase):
    setUp = capture_tests.UploadTests.setUp
    start = capture_tests.UploadTests.start

    def fixtures(self):
        image = np.random.default_rng(42).integers(70, 190, (128, 128, 3), dtype=np.uint8)
        row = np.array([0, 0, 128, 128, 40, 40, 88, 40, 64, 70, 45, 95, 85, 95, .8], dtype=np.float32)
        return image, row.reshape(1, 15)

    def test_quality_approved_preflash_frames_only(self):
        image, faces = self.fixtures()
        dark = np.zeros_like(image)
        bright = np.full_like(image, 255)
        frames = [(i * 100, dark if i < 2 else image if i < 20 else bright) for i in range(30)]
        bad_faces = faces.copy()
        bad_faces[0, -1] = .99
        detections = [(None, bad_faces)] * 2 + [(None, faces)] * 18 + [(None, bad_faces)] * 10
        with patch.object(face_quality, "detect_all_faces", side_effect=detections), \
                patch.object(face_matching, "embed_row", side_effect=[vector(.4), vector(.5), vector(.6)]) as embed:
            result = face_matching.match_quality_frames(frames, 2000, json.dumps(vector().tolist()))
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["cosine"], .5)
        self.assertEqual(embed.call_count, 3)
        for call in embed.call_args_list:
            self.assertIs(call.args[0], image)
            self.assertAlmostEqual(float(call.args[1][-1]), .8)

    def test_old_unnormalized_and_new_normalized_embeddings(self):
        image, faces = self.fixtures()
        frames = [(i * 100, image) for i in range(30)]
        for scale in (1, 100):
            with patch.object(face_quality, "detect_all_faces", return_value=(None, faces)), \
                    patch.object(face_matching, "embed_row", return_value=vector(.4, scale=50)):
                result = face_matching.match_quality_frames(frames, 2000, json.dumps(vector(scale=scale).tolist()))
            self.assertTrue(result["ok"])
            self.assertAlmostEqual(result["cosine"], .4)

    def test_unrounded_cosine_is_retained(self):
        image, faces = self.fixtures()
        frames = [(i * 100, image) for i in range(30)]
        with patch.object(face_quality, "detect_all_faces", return_value=(None, faces)), \
                patch.object(face_matching, "embed_row", return_value=vector(.36296)):
            result = face_matching.match_quality_frames(frames, 2000, json.dumps(vector().tolist()))
        self.assertTrue(result["ok"])
        self.assertLess(result["cosine"], .363)
        self.assertEqual(round(result["cosine"], 4), .363)
        self.assertEqual(fuse_v2(100, 100, 100, 90, cosine=result["cosine"], speak_cosine=.7)["riskLabel"], "SUSPICIOUS")

    def test_insufficient_quality_and_multiple_faces_do_not_embed(self):
        image, faces = self.fixtures()
        for reason, frames, detections in (
            ("too_few_usable_face_frames", [(i * 100, image) for i in range(5)], [(None, faces)] * 5),
            ("no_face", [(i * 100, image) for i in range(10)], [(None, faces)] * 7 + [("no_face", None)] * 3),
            ("multiple_faces", [(i * 100, image) for i in range(30)], [(None, faces)] * 29 + [(None, np.vstack((faces, faces)))]),
        ):
            with self.subTest(reason=reason), patch.object(face_quality, "detect_all_faces", side_effect=detections), \
                    patch.object(face_matching, "embed_row") as embed:
                self.assertEqual(face_matching.match_quality_frames(frames, 2000, json.dumps(vector().tolist()))["reason"], reason)
                embed.assert_not_called()

    def test_invalid_enrollment_or_model_vectors_fail_closed(self):
        image, faces = self.fixtures()
        frames = [(i * 100, image) for i in range(30)]
        with patch.object(face_quality, "detect_all_faces", return_value=(None, faces)), \
                patch.object(face_matching, "embed_row") as embed:
            for stored in ("[0.1]", "null", "broken", json.dumps([0] * 128)):
                self.assertEqual(face_matching.match_quality_frames(frames, 2000, stored)["reason"], "not_enrolled")
            embed.assert_not_called()
            for feature in ([0] * 128, [float("nan")] * 128, [1] * 127):
                embed.return_value = feature
                self.assertEqual(face_matching.match_quality_frames(frames, 2000, json.dumps(vector().tolist()))["reason"], "invalid_face_embedding")

    def test_v2_does_not_repeat_the_legacy_matcher(self):
        image, faces = self.fixtures()
        frames = [(i * 100, image) for i in range(30)]
        blink = {"ok": True, "blinkScore": 90, "blinkCount": 1, "dipPercent": 60}
        flash = {"ok": True, "flashScore": 50, "reflectionDelta": None, "reflectionR": None, "detail": "insufficient"}
        with patch.object(face_quality, "detect_all_faces", return_value=(None, faces)) as detect, \
                patch.object(face_matching, "embed_row", return_value=vector(.7)), \
                patch.object(profiles, "match_pre_flash") as legacy, \
                patch.object(profiles, "measure_landmarks", return_value=(None, [])), \
                patch.object(profiles, "score_landmark_blink", return_value=blink), \
                patch.object(profiles, "score_v2_flash", return_value=flash):
            result = profiles.get_profile("v2").score_look(frames, 2000, json.dumps(vector(scale=20).tolist()))
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["cosine"], .7)
        self.assertEqual(detect.call_count, len(frames))
        legacy.assert_not_called()

    def test_safe_cosine_boundary_and_invalid_evidence(self):
        for cosine in (None, float("nan"), float("inf"), -float("inf"), "0.7", True, -.2, 1.01, .362999999):
            with self.subTest(cosine=cosine):
                result = fuse_v2(100, 100, 100, 90, cosine=cosine, speak_cosine=.7, **gate_fixture.fusion_options())
                self.assertEqual((result["trustScore"], result["riskLabel"]), (74, "SUSPICIOUS"))
        for cosine in (.363, .363001, 1):
            self.assertEqual(fuse_v2(100, 100, 100, 90, cosine=cosine, speak_cosine=.7, **gate_fixture.fusion_options()), fuse(100, 100, 100, 90))
        self.assertEqual(fuse_v2(15, 70, 10, 25, cosine=.1), fuse(15, 70, 10, 25))
        self.assertEqual(fuse(100, 100, 100, 90)["riskLabel"], "SAFE")

    def finish_with_scores(self, cosine):
        session_id = self.start()
        save_look(session_id, {"faceScore": 60, "cosine": cosine, "blinkScore": 100, "blinkCount": 1,
                              "flashScore": 90, "reflectionDelta": .1, "reflectionR": .4,
                              "detailJson": json.dumps(gate_fixture.look_detail())})
        save_voice(session_id, {"acousticScore": 100, "lipScore": 100, "lipR": .9, "voiceScore": 100, "speakCosine": .7,
                                "detail": gate_fixture.speak_detail(get_session(session_id)['challenge_word'])})
        return session_id

    def test_api_uses_stored_raw_cosine_and_pinned_profile_for_certificates(self):
        self.app.config["VERIFICATION_PROFILE"] = "v2"
        new = self.finish_with_scores(.36296)
        self.app.config["VERIFICATION_PROFILE"] = "legacy"
        response = self.client.post(f"/api/session/{new}/trust", headers=self.headers, json={"cosine": 1, "verification_profile": "legacy"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.get_json()["trustScore"], response.get_json()["riskLabel"]), (74, "SUSPICIOUS"))
        self.assertEqual(get_result(new)["cosine"], .36296)
        issued = self.client.post(f"/api/session/{new}/certificate", headers=self.headers)
        self.assertEqual(issued.status_code, 200)
        page = self.client.get("/certificate/" + issued.get_json()["certId"]).get_data(as_text=True)
        self.assertIn("SUSPICIOUS", page)
        self.assertIn("intact", page)
        old = self.finish_with_scores(.36296)
        self.app.config["VERIFICATION_PROFILE"] = "v2"
        response = self.client.post(f"/api/session/{old}/trust", headers=self.headers)
        self.assertEqual((response.get_json()["trustScore"], response.get_json()["riskLabel"]), (90, "SAFE"))

    def test_api_boundary_and_missing_cosine(self):
        for cosine, expected in ((.363, "SAFE"), (None, "SUSPICIOUS")):
            session_id = self.finish_with_scores(cosine)
            response = self.client.post(f"/api/session/{session_id}/trust", headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["riskLabel"], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
