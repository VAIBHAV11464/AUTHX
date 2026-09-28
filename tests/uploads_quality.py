"""Tasks 5/6 tests; synthetic captures and temporary databases only."""

import base64
import contextlib
import io
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch
from dataclasses import replace

import jwt
import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Config
from app import create_app
from app.models import get_result, get_user_by_username, save_face_embedding, save_look
from app.services import uploads
from app.services import face_quality, face_detector, verification_profiles as profiles
import speech_fixture


def image64(width=128, height=128):
    output = io.BytesIO()
    Image.new("RGB", (width, height), (128, 128, 128)).save(output, "PNG")
    return base64.b64encode(output.getvalue()).decode()


def capture(count=15):
    raw = image64()
    return {"frames": [{"tMs": i * 2800 / (count - 1), "image": raw} for i in range(count)]}


def audio(seconds=3, channels=1, width=2, rate=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(b"\0" * int(seconds * rate) * channels * width)
    return base64.b64encode(output.getvalue()).decode()


class UploadTests(unittest.TestCase):
    def setUp(self):
        speech_fixture.install(self)
        temp = tempfile.TemporaryDirectory(prefix="authx-uploads-")
        self.addCleanup(temp.cleanup)
        settings = patch.multiple(Config, DATABASE_PATH=Path(temp.name) / "test.db", VERIFICATION_PROFILE="v2")
        settings.start()
        self.addCleanup(settings.stop)
        with contextlib.redirect_stdout(io.StringIO()):
            self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.user = get_user_by_username("avinash")
        save_face_embedding(self.user["id"], "[0.1]")
        token = jwt.encode({"sub": str(self.user["id"])}, self.app.config["JWT_SECRET"], algorithm="HS256")
        self.headers = {"Authorization": "Bearer " + token}
        context = self.app.app_context()
        context.push()
        self.addCleanup(context.pop)

    def reject(self, reason, function, value):
        with self.assertRaises(uploads.UploadError) as exc:
            function(value)
        self.assertEqual(exc.exception.reason, reason)

    def start(self):
        response = self.client.post("/api/session/start", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        return response.get_json()["sessionId"]

    def test_valid_browser_uploads_and_bounds(self):
        for count in (8, 15, 30, 90):
            with self.subTest(count=count):
                self.assertEqual(len(uploads.frames(capture(count))), count)
        self.assertEqual(uploads.image("data:image/png;base64," + image64()).shape, (128, 128, 3))
        for seconds in (2, 3, 4):
            for rate in (8000, 16000, 48000):
                samples, actual_rate = uploads.wav({"wav": audio(seconds, rate=rate)})
                self.assertEqual(actual_rate, 16000)
                self.assertEqual(len(samples), seconds * 16000)

    def test_image_shape_format_and_corruption(self):
        for raw in (None, 42, "", "%%%", "data:image/png,AAAA", "AAAA"):
            with self.subTest(raw=raw):
                self.reject("bad_image", uploads.image, raw)
        for width, height in ((63, 128), (1281, 64), (1000, 1000)):
            with self.subTest(width=width, height=height):
                self.reject("bad_image_dimensions", uploads.image, image64(width, height))
        truncated = base64.b64encode(base64.b64decode(image64())[:40]).decode()
        self.reject("bad_image", uploads.image, truncated)
        with patch.dict(self.app.config, V2_CLIP_MAX_PIXELS=128 * 128 * 7):
            self.reject("capture_too_large", uploads.frames, capture(8))

    def test_no_silent_frame_skipping(self):
        self.reject("bad_payload", uploads.frames, [])
        for value in (None, "x", {}):
            self.reject("bad_frames", uploads.frames, {"frames": value})
        for count in (0, 7, 91):
            self.reject("bad_frame_count", uploads.frames, {"frames": [None] * count})
        data = capture()
        data["frames"][4] = None
        self.reject("bad_frames", uploads.frames, data)
        data = capture()
        data["frames"][4]["image"] = "%%%"
        self.reject("bad_image", uploads.frames, data)

    def test_timestamps_and_video_duration(self):
        for stamp in (float("nan"), float("inf"), -1, 4001, True, "800", None, 10 ** 400, 0):
            with self.subTest(stamp=str(stamp)[:30]):
                data = capture()
                data["frames"][4]["tMs"] = stamp
                self.reject("bad_timestamps", uploads.frames, data)
        data = capture()
        data["frames"][4]["tMs"] = data["frames"][3]["tMs"]
        self.reject("bad_timestamps", uploads.frames, data)
        for offset, scale in ((600, 1), (0, 0.5)):
            data = capture()
            for item in data["frames"]:
                item["tMs"] = offset + item["tMs"] * scale
            self.reject("bad_capture_duration", uploads.frames, data)

    def test_wav_format_duration_and_truncation(self):
        for options in ({"channels": 2}, {"width": 1}, {"rate": 12345}):
            self.reject("bad_wav_format", uploads.wav, {"wav": audio(**options)})
        for seconds in (1.9, 4.1):
            self.reject("bad_audio_duration", uploads.wav, {"wav": audio(seconds)})
        blob = base64.b64decode(audio())
        for raw in ("%%%", base64.b64encode(blob[:-20]).decode(), base64.b64encode(blob[:20]).decode()):
            self.reject("bad_wav", uploads.wav, {"wav": raw})

    def test_api_rejections_do_not_overwrite_enrollment_or_results(self):
        for data in ([], {"image": image64(20, 20)}):
            response = self.client.post("/api/face/enroll", headers=self.headers, json=data)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(get_user_by_username("avinash")["face_embedding"], "[0.1]")
        session_id = self.start()
        response = self.client.post(f"/api/session/{session_id}/look", headers=self.headers, json=capture(7))
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(get_result(session_id))
        save_look(session_id, {
            "faceScore": 95, "cosine": 0.7, "blinkScore": 90, "blinkCount": 1,
            "flashScore": 50, "reflectionDelta": None, "reflectionR": None, "detailJson": "{}",
        })
        response = self.client.post(f"/api/session/{session_id}/speak", headers=self.headers, json={"wav": audio(1), **capture()})
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(get_result(session_id)["voice_score"])
        response = self.client.post("/api/voice/score", headers=self.headers, json={"wav": audio(), "frames": []})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["reason"], "bad_frame_count")

    def test_wav_container_alignment_and_headers(self):
        original = base64.b64decode(audio())
        for offset, size, value in ((20, 2, 3), (28, 4, 1), (32, 2, 1)):
            blob = bytearray(original)
            blob[offset:offset + size] = value.to_bytes(size, "little")
            self.reject("bad_wav_format", uploads.wav, {"wav": base64.b64encode(blob).decode()})
        blob = bytearray(original[:-1])
        blob[4:8] = (len(blob) - 8).to_bytes(4, "little")
        blob[40:44] = (len(blob) - 44).to_bytes(4, "little")
        # Pad the odd chunk as required by RIFF; PCM16 still needs whole samples.
        blob.append(0)
        blob[4:8] = (len(blob) - 8).to_bytes(4, "little")
        self.reject("bad_wav_format", uploads.wav, {"wav": base64.b64encode(blob).decode()})
        # Unknown RIFF chunks are allowed when well formed, including padding.
        blob = bytearray(original + b"JUNK" + (1).to_bytes(4, "little") + b"x\0")
        blob[4:8] = (len(blob) - 8).to_bytes(4, "little")
        self.assertEqual(len(uploads.wav({"wav": base64.b64encode(blob).decode()})[0]), 48000)

    def test_eight_mib_upload_limit(self):
        self.assertEqual(self.app.config["MAX_CONTENT_LENGTH"], 8 * 1024 * 1024)
        response = self.client.post("/api/face/enroll", headers=self.headers,
                                    data=b" " * (8 * 1024 * 1024 + 1), content_type="application/json")
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["reason"], "upload_too_large")


class QualityTests(unittest.TestCase):
    setUp = UploadTests.setUp
    start = UploadTests.start

    def fixtures(self):
        rng = np.random.default_rng(42)
        image = rng.integers(70, 190, (128, 128, 3), dtype=np.uint8)
        row = np.array([0, 0, 128, 128, 40, 40, 88, 40, 64, 70, 45, 95, 85, 95, .95], dtype=np.float32)
        return image, row.reshape(1, 15)

    def encoded(self, image):
        ok, blob = cv2.imencode(".png", image)
        self.assertTrue(ok)
        return base64.b64encode(blob).decode()

    def test_face_count_size_visibility_and_confidence(self):
        image, faces = self.fixtures()
        self.assertIsNone(face_quality.face_quality(image, faces)[0])
        self.assertEqual(face_quality.face_quality(image, None)[0], "no_face")
        self.assertEqual(face_quality.face_quality(image, np.vstack((faces, faces)))[0], "multiple_faces")
        for index, value, reason in ((2, 50, "face_too_small"), (0, 80, "face_cut_off"), (14, .5, "weak_face"), (4, np.nan, "no_face")):
            with self.subTest(reason=reason):
                changed = faces.copy()
                changed[0, index] = value
                self.assertEqual(face_quality.face_quality(image, changed)[0], reason)
        large = np.tile(image, (4, 4, 1))
        self.assertEqual(face_quality.face_quality(large, faces)[0], None)
        larger = np.tile(image, (8, 8, 1))
        self.assertEqual(face_quality.face_quality(larger, faces)[0], "face_too_small")

    def test_dark_bright_uneven_and_blurred_faces(self):
        image, faces = self.fixtures()
        uneven = np.zeros_like(image)
        uneven[:, 64:] = 255
        for changed, reason in ((np.zeros_like(image), "face_too_dark"), (np.full_like(image, 255), "face_too_bright"),
                                (uneven, "uneven_face_lighting"), (cv2.GaussianBlur(image, (31, 31), 8), "face_blurry")):
            with self.subTest(reason=reason):
                self.assertEqual(face_quality.face_quality(changed, faces)[0], reason)

    def test_detector_returns_all_faces_while_legacy_keeps_largest(self):
        image, faces = self.fixtures()
        smaller = faces.copy()
        smaller[0, 2:4] = 90
        both = np.vstack((smaller, faces))
        with patch.object(face_detector, "_yunet"), patch.object(face_detector, "_run_detect", return_value=both):
            self.assertEqual(face_detector.detect_all_faces(image)[1].shape, (2, 15))
            np.testing.assert_equal(face_detector.detect_faces(image)[1], faces[0])
        with patch.dict(self.app.config, YUNET_PATH=ROOT / "models/missing.onnx"):
            self.assertEqual(face_detector.detect_all_faces(image)[0], "model_missing")

    def test_clip_quality_ratio_and_minimum(self):
        image, faces = self.fixtures()
        frames = [(i * 300, image) for i in range(10)]
        with patch.object(face_quality, "detect_all_faces", return_value=(None, faces)):
            self.assertIsNone(face_quality.clip_quality(frames))
            self.assertEqual(face_quality.clip_quality(frames, 1800), "too_few_usable_face_frames")
        for good, expected in ((8, None), (7, "no_face")):
            detections = [(None, faces)] * good + [("no_face", None)] * (10 - good)
            with patch.object(face_quality, "detect_all_faces", side_effect=detections):
                self.assertEqual(face_quality.clip_quality(frames), expected)

    def test_flash_is_exempt_from_lighting_but_not_multiple_faces(self):
        image, faces = self.fixtures()
        frames = [(i * 100, image if i < 20 else np.full_like(image, 255)) for i in range(30)]
        with patch.object(face_quality, "detect_all_faces", return_value=(None, faces)):
            self.assertIsNone(face_quality.clip_quality(frames, 2000))
        detections = [(None, faces)] * 29 + [(None, np.vstack((faces, faces)))]
        with patch.object(face_quality, "detect_all_faces", side_effect=detections):
            self.assertEqual(face_quality.clip_quality(frames, 2000), "multiple_faces")

    def test_quality_enrollment_retries_preserve_existing_embedding(self):
        image, faces = self.fixtures()
        for frame, found, reason in ((np.zeros_like(image), faces, "face_too_dark"),
                                     (image, np.vstack((faces, faces)), "multiple_faces")):
            with patch.object(face_quality, "detect_all_faces", return_value=(None, found)), \
                    patch.object(face_quality, "embed_row") as embed:
                response = self.client.post("/api/face/enroll", headers=self.headers, json={"image": self.encoded(frame)})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.get_json()["reason"], reason)
                embed.assert_not_called()
                self.assertEqual(get_user_by_username("avinash")["face_embedding"], "[0.1]")
        with patch.object(face_quality, "detect_all_faces", return_value=(None, faces)), \
                patch.object(face_quality, "embed_row", return_value=np.ones(128)):
            response = self.client.post("/api/face/enroll", headers=self.headers, json={"image": self.encoded(image)})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(json.loads(get_user_by_username("avinash")["face_embedding"])), 128)

    def test_v2_quality_rejections_leave_steps_open_and_retry_succeeds(self):
        image, faces = self.fixtures()
        data = capture(30)
        for frame in data["frames"]:
            frame["image"] = self.encoded(image)
        session_id = self.start()
        looked = {"ok": True, "faceScore": 95, "cosine": .7, "blinkScore": 90, "blinkCount": 1,
                  "dipPercent": 60, "flashScore": 50, "reflectionDelta": None, "reflectionR": None, "detailJson": "{}"}
        with patch.object(face_quality, "detect_all_faces", return_value=(None, np.vstack((faces, faces)))), \
                patch.object(profiles, "_legacy_look") as legacy:
            response = self.client.post(f"/api/session/{session_id}/look", headers=self.headers, json=data)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.get_json()["reason"], "multiple_faces")
            self.assertIsNone(get_result(session_id))
            legacy.assert_not_called()
        with patch.object(face_quality, "detect_all_faces", return_value=(None, faces)), \
                patch.object(profiles, "match_quality_frames", return_value={"ok": True, "faceScore": 95, "cosine": .7}), \
                patch.object(profiles, "measure_landmarks", return_value=(None, [])), \
                patch.object(profiles, "score_landmark_blink", return_value={"ok": True}), \
                patch.object(profiles, "score_v2_flash", return_value={"ok": True}), \
                patch.object(profiles, "_legacy_look", return_value=looked) as legacy:
            response = self.client.post(f"/api/session/{session_id}/look", headers=self.headers, json=data)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(legacy.call_args.args[0]), 30)  # Blink/flash still use the full capture.
            self.assertEqual(legacy.call_args.kwargs["face_result"]["cosine"], .7)
        with patch.object(face_quality, "detect_all_faces", return_value=("no_face", None)):
            response = self.client.post(f"/api/session/{session_id}/speak", headers=self.headers, json={**data, "wav": audio()})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.get_json()["reason"], "no_face")
            self.assertIsNone(get_result(session_id)["voice_score"])
        lip = {"ok": True, "lipScore": 90, "lipR": .5, "mouthVar": 10, "detail": None}
        with patch.object(face_quality, "detect_all_faces", return_value=(None, faces)), \
                patch.object(profiles, "match_quality_frames", return_value={"ok": True, "faceScore": 95, "cosine": .7}), \
                patch.object(profiles, "measure_landmarks", return_value=(None, [])), \
                patch.object(profiles, "score_landmark_lips", return_value=lip):
            response = self.client.post(f"/api/session/{session_id}/speak", headers=self.headers, json={**data, "wav": audio()})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["voiceScore"], 30)
            standalone = self.client.post("/api/voice/score", headers=self.headers, json={**data, "wav": audio()})
            self.assertEqual(standalone.status_code, 200)
            self.assertEqual(set(standalone.get_json()), {"ok", "voiceScore", "acoustic", "lip"})

    def test_validation_uses_pinned_profile_in_both_directions(self):
        self.app.config["VERIFICATION_PROFILE"] = "legacy"
        old = self.start()
        self.app.config["VERIFICATION_PROFILE"] = "v2"
        new = self.start()
        registry = dict(profiles._PROFILES)
        looked = {"ok": True, "faceScore": 95, "cosine": .7, "blinkScore": 90, "blinkCount": 1,
                  "dipPercent": 60, "flashScore": 50, "reflectionDelta": None, "reflectionR": None, "detailJson": "{}"}
        handler = Mock(return_value=looked)
        registry["legacy"] = replace(registry["legacy"], score_look=handler)
        registry["v2"] = replace(registry["v2"], score_look=Mock())
        with patch.object(profiles, "_PROFILES", registry):
            response = self.client.post(f"/api/session/{old}/look", headers=self.headers, json=capture(7))
            self.assertEqual(response.status_code, 200)
            handler.assert_called_once()
            self.app.config["VERIFICATION_PROFILE"] = "legacy"
            response = self.client.post(f"/api/session/{new}/look", headers=self.headers, json=capture(7))
            self.assertEqual(response.status_code, 400)
            registry["v2"].score_look.assert_not_called()

    def test_v2_missing_model_is_service_error(self):
        session_id = self.start()
        with patch.dict(self.app.config, YUNET_PATH=ROOT / "models/missing.onnx"):
            response = self.client.post(f"/api/session/{session_id}/look", headers=self.headers, json=capture(30))
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json()["reason"], "model_missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
