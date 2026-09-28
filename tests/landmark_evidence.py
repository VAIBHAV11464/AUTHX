"""Tasks 12–14: geometry, aligned evidence, retries and legacy compatibility."""
import base64
import io
import json
import sys
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import uploads_quality as captures
from enrollment_matching import vector
from app.models import connect, get_result, save_face_embedding, save_look
from app.services import face_quality, face_matching, flash, verification_profiles as profiles
from app.services.landmark_geometry import eye_ratios, mouth_ratio, LEFT_EYE, RIGHT_EYE
from app.services.landmarks import LandmarkFrame
from app.services.liveness import score_landmark_blink
from app.services.lipsync import score_landmark_lips


def points(ear=.3, mouth=.2, scale=1, shift=0):
    result = np.zeros((478, 3))
    for offset, indices in ((0, LEFT_EYE), (40, RIGHT_EYE)):
        values = [(10, 20), (15, 20 - 10 * ear), (25, 20 - 10 * ear),
                  (30, 20), (25, 20 + 10 * ear), (15, 20 + 10 * ear)]
        for index, xy in zip(indices, values):
            result[index, :2] = np.array(xy) + [offset, 0]
    result[78, :2], result[308, :2] = (20, 60), (60, 60)
    result[13, :2], result[14, :2] = (40, 60 - mouth * 20), (40, 60 + mouth * 20)
    result[:, :2] = result[:, :2] * scale + shift
    return result


def blink_frames(closed=(10, 11), count=40, interval=50):
    return [LandmarkFrame(i * interval, None, points(ear=.1 if i in closed else .3)) for i in range(count)]


def speech_frames(offset=100, interval=50):
    return [LandmarkFrame(i * interval, None, points(mouth=.2 + .1 * np.sin(2 * np.pi * 2 * (i * interval - offset) / 1000)))
            for i in range(int(3000 / interval))]


def speech_audio(seconds=3):
    times = np.arange(int(seconds * 16000)) / 16000
    return (.1 + .08 * np.sin(2 * np.pi * 2 * times)) * np.sin(2 * np.pi * 220 * times)


class EvidenceTests(unittest.TestCase):
    setUp = captures.UploadTests.setUp

    def test_scale_and_translation_invariant_geometry(self):
        for scale, shift in ((1, 0), (2, 100), (.5, -10)):
            np.testing.assert_allclose(eye_ratios(points(scale=scale, shift=shift)), (.3, .3))
            self.assertAlmostEqual(mouth_ratio(points(scale=scale, shift=shift)), .2)
        for invalid in (None, [], np.zeros((478, 3)), np.full((478, 3), np.nan)):
            self.assertIsNone(eye_ratios(invalid))
            self.assertIsNone(mouth_ratio(invalid))

    def test_complete_bilateral_blink_before_flash(self):
        result = score_landmark_blink(blink_frames(), 2000)
        self.assertTrue(result['ok'])
        self.assertEqual((result['blinkCount'], result['blinkScore']), (1, 90))
        self.assertGreater(result['dipPercent'], 60)
        self.assertEqual(score_landmark_blink(blink_frames((5, 15, 25)), 2000)['blinkScore'], 70)

    def test_no_initial_open_or_no_return_cannot_count(self):
        for closed in ((), (0, 1, 2), (35, 36, 37, 38, 39), tuple(range(40))):
            self.assertEqual(score_landmark_blink(blink_frames(closed), 2000)['reason'], 'no_blink')

    def test_blink_return_at_or_after_flash_cannot_count(self):
        for flash_at in (600, 550):
            frames = blink_frames((10, 11), count=60)
            self.assertEqual(score_landmark_blink(frames, flash_at)['reason'], 'no_blink')
        frames = blink_frames(tuple(range(40, 43)), count=60)
        self.assertEqual(score_landmark_blink(frames, 2000)['reason'], 'no_blink')

    def test_wink_long_closure_and_dropout_do_not_count(self):
        frames = blink_frames()
        for i in (10, 11):
            altered = frames[i].points.copy()
            altered[list(RIGHT_EYE)] = points()[list(RIGHT_EYE)]
            frames[i] = LandmarkFrame(i * 50, None, altered)
        self.assertEqual(score_landmark_blink(frames, 2000)['reason'], 'no_blink')
        self.assertEqual(score_landmark_blink(blink_frames(tuple(range(10, 23))), 2000)['reason'], 'no_blink')
        frames = blink_frames()
        frames[11] = LandmarkFrame(550, None, None)
        self.assertEqual(score_landmark_blink(frames, 2000)['reason'], 'no_blink')

    def test_sparse_or_missing_blink_evidence_requests_retry(self):
        self.assertEqual(score_landmark_blink(blink_frames(count=7), 2000)['reason'], 'insufficient_blink_evidence')
        self.assertEqual(score_landmark_blink(blink_frames(interval=200), 2000)['reason'], 'insufficient_blink_evidence')
        frames = blink_frames()
        for i in range(15):
            frames[i] = LandmarkFrame(i * 50, None, None)
        self.assertEqual(score_landmark_blink(frames, 2000)['reason'], 'insufficient_blink_evidence')

    def test_quality_rejected_frames_are_not_measured_or_bridged(self):
        originals = [(i * 50, object()) for i in range(40)]
        approved = [(stamp, image, None) for stamp, image in originals if stamp != 550]
        def measure(frames):
            return None, [LandmarkFrame(stamp, image, points(ear=.1 if stamp == 500 else .3)) for stamp, image in frames]
        with patch.object(profiles, 'measure_landmarks', side_effect=measure) as model:
            reason, measured = profiles._measure_approved(originals, {'approvedFrames': approved})
        self.assertIsNone(reason)
        self.assertNotIn(550, [stamp for stamp, _ in model.call_args.args[0]])
        self.assertIsNone(measured[11].points)
        self.assertEqual(score_landmark_blink(measured, 2000)['reason'], 'no_blink')

    def test_lips_use_normalized_opening_and_audio_offset(self):
        frames, audio = speech_frames(), speech_audio(2.9)
        aligned = score_landmark_lips(frames, audio, 16000, 100)
        wrong = score_landmark_lips(frames, audio, 16000, 0)
        self.assertTrue(aligned['ok'])
        self.assertEqual(aligned['lipScore'], 90)
        self.assertGreater(aligned['lipR'], .95)
        self.assertLess(wrong['lipR'], .45)
        scaled = [LandmarkFrame(f.t_ms, None, points(mouth=mouth_ratio(f.points), scale=2, shift=100)) for f in frames]
        self.assertEqual(score_landmark_lips(scaled, audio, 16000, 100)['lipR'], aligned['lipR'])

    def test_measured_still_mouth_is_low_score(self):
        frames = [LandmarkFrame(i * 50, None, points()) for i in range(60)]
        result = score_landmark_lips(frames, speech_audio(), 16000)
        self.assertTrue(result['ok'])
        self.assertEqual((result['lipScore'], result['detail']), (20, 'still_mouth'))

    def test_missing_or_silent_lips_request_retry(self):
        for frames, audio, offset in ((speech_frames()[:5], speech_audio(), 0),
                                      (speech_frames(interval=200), speech_audio(), 0),
                                      (speech_frames(), np.zeros(48000), 0),
                                      (speech_frames(), np.ones(48000) * .1, 0),
                                      (speech_frames(), np.full(48000, np.nan), 0),
                                      (speech_frames(), speech_audio(), 4000)):
            result = score_landmark_lips(frames, audio, 16000, offset)
            self.assertFalse(result['ok'])
            self.assertEqual(result['reason'], 'insufficient_lip_evidence')
            self.assertIsNone(result['lipScore'])

    def test_landmark_loss_does_not_earn_neutral_lip_score(self):
        frames = speech_frames()
        for i in range(20):
            frames[i] = LandmarkFrame(i * 50, None, None)
        result = score_landmark_lips(frames, speech_audio(), 16000)
        self.assertEqual(result['reason'], 'insufficient_lip_evidence')
        self.assertIsNone(result['lipR'])

    def flash_samples(self, response=115):
        return [(t, 100) for t in (1800, 1850, 1900, 1950)] + [(t, response) for t in (2000, 2050, 2100, 2150)]

    def test_measured_strong_and_weak_flash_responses(self):
        strong = flash.score_v2_brightness(self.flash_samples(), 2000)
        weak = flash.score_v2_brightness(self.flash_samples(100), 2000)
        self.assertEqual((strong['ok'], strong['flashScore']), (True, 90))
        self.assertEqual((weak['ok'], weak['flashScore']), (True, 25))
        self.assertEqual(weak['reflectionDelta'], 0)
        self.assertIsNone(weak['detail'])

    def test_insufficient_flash_cannot_earn_neutral_score(self):
        for samples in ([], self.flash_samples()[:4], self.flash_samples()[4:], self.flash_samples()[::2]):
            result = flash.score_v2_brightness(samples, 2000)
            self.assertEqual(result['reason'], 'insufficient_flash_evidence')
            self.assertIsNone(result['flashScore'])
        self.assertEqual(flash.score_brightness([], 2000)['flashScore'], 50)  # legacy preserved

    def test_invalid_or_sparse_flash_evidence_requests_retry(self):
        for samples in (self.flash_samples(255), self.flash_samples(float('nan')),
                        [(t, 0) for t, _ in self.flash_samples()]):
            self.assertEqual(flash.score_v2_brightness(samples, 2000)['reason'], 'invalid_flash_evidence')
        samples = self.flash_samples()
        samples[1], samples[2] = samples[2], samples[1]
        self.assertEqual(flash.score_v2_brightness(samples, 2000)['reason'], 'insufficient_flash_evidence')
        samples = [(t, value) for t, value in self.flash_samples() if t != 2050]
        self.assertEqual(flash.score_v2_brightness(samples, 2000)['reason'], 'insufficient_flash_evidence')

    def test_jump_outside_flash_is_measured_weak(self):
        samples = self.flash_samples(100) + [(2500, 180), (2550, 180)]
        self.assertEqual(flash.score_v2_brightness(samples, 2000)['flashScore'], 25)


class EvidenceApiTests(unittest.TestCase):
    setUp = captures.UploadTests.setUp

    def begun(self):
        save_face_embedding(self.user['id'], json.dumps(vector().tolist()))
        session_id = self.client.post('/api/session/start', headers=self.headers).get_json()['sessionId']
        conn = connect()
        try:
            conn.execute('UPDATE sessions SET flash_start_ms = 2000 WHERE id = ?', (session_id,))
            conn.commit()
        finally:
            conn.close()
        return session_id

    def payload(self):
        image = np.random.default_rng(42).integers(70, 190, (128, 128, 3), dtype=np.uint8)
        encoded = []
        for during in (False, True):
            out = io.BytesIO()
            Image.fromarray(image + (25 if during else 0)).save(out, 'PNG')
            encoded.append(base64.b64encode(out.getvalue()).decode())
        out = io.BytesIO()
        with wave.open(out, 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
            wav.writeframes((speech_audio() * 32767).astype('<i2').tobytes())
        return {'frames': [{'tMs': i * 50, 'image': encoded[int(2000 <= i * 50 < 2400)]} for i in range(60)],
                'wav': base64.b64encode(out.getvalue()).decode()}

    def measured(self, frames):
        return None, [LandmarkFrame(stamp, image, points(ear=.1 if 500 <= stamp < 600 else .3,
                      mouth=.2 + .1 * np.sin(2 * np.pi * 2 * stamp / 1000))) for stamp, image in frames]

    def patches(self):
        faces = np.array([[0, 0, 128, 128, 40, 40, 88, 40, 64, 70, 45, 95, 85, 95, .8]], dtype=np.float32)
        return (patch.object(face_quality, 'detect_all_faces', return_value=(None, faces)),
                patch.object(face_matching, 'embed_row', return_value=vector()),
                patch.object(flash, 'detect_faces', return_value=(None, faces[0])),
                patch.object(profiles, 'measure_landmarks', side_effect=self.measured))

    def test_real_geometry_and_flash_scoring_complete_api_flow(self):
        session_id = self.begun()
        a, b, c, d = self.patches()
        with a, b, c, d as measured:
            looked = self.client.post(f'/api/session/{session_id}/look', headers=self.headers, json=self.payload())
            self.assertEqual(looked.status_code, 200)
            self.assertEqual(looked.get_json()['blinkCount'], 1)
            self.assertEqual(looked.get_json()['flashScore'], 90)
            self.app.config['V2_EAR_OPEN'] = .25
            spoken = self.client.post(f'/api/session/{session_id}/speak', headers=self.headers, json=self.payload())
            self.assertEqual(spoken.status_code, 200)
            self.assertEqual(spoken.get_json()['lipScore'], 90)
            self.assertEqual(measured.call_count, 2)  # one landmark pass per step
        detail = json.loads(get_result(session_id)['detail_json'])
        self.assertEqual(detail['measurementVersion'], 'v2-landmarks-1')
        self.assertEqual(detail['landmarkModelSha256'], self.app.config['LANDMARK_SHA256'])
        self.assertIn('V2_EAR_OPEN', detail['measurementConfig'])
        self.assertIn('lookMeasurement', detail)
        self.assertIn('speakMeasurement', detail)
        self.assertEqual(detail['lookMeasurement']['measurementConfig']['V2_EAR_OPEN'], .21)
        self.assertEqual(detail['speakMeasurement']['measurementConfig']['V2_EAR_OPEN'], .25)
        trust = self.client.post(f'/api/session/{session_id}/trust', headers=self.headers)
        self.assertEqual(trust.status_code, 200)
        self.assertEqual(self.client.post(f'/api/session/{session_id}/certificate', headers=self.headers).status_code, 200)

    def test_missing_blink_model_or_flash_does_not_lock_look(self):
        session_id = self.begun()
        for reason, measured_result in (('insufficient_blink_evidence', (None, [])),
                                        ('landmark_model_missing', ('landmark_model_missing', [])),
                                        ('landmark_model_invalid', ('landmark_model_invalid', []))):
            a, b, c, _ = self.patches()
            with a, b, c, patch.object(profiles, 'measure_landmarks', return_value=measured_result):
                response = self.client.post(f'/api/session/{session_id}/look', headers=self.headers, json=self.payload())
            self.assertEqual(response.status_code, 503 if reason.startswith('landmark_model_') else 422)
            self.assertEqual(response.get_json()['reason'], reason)
            self.assertIsNone(get_result(session_id))
        a, b, _, d = self.patches()
        with a, b, d, patch.object(flash, 'detect_faces', return_value=('no_face', None)):
            response = self.client.post(f'/api/session/{session_id}/look', headers=self.headers, json=self.payload())
        self.assertEqual(response.get_json()['reason'], 'insufficient_flash_evidence')
        self.assertIsNone(get_result(session_id))
        a, b, c, d = self.patches()
        with a, b, c, d:
            self.assertEqual(self.client.post(f'/api/session/{session_id}/look', headers=self.headers, json=self.payload()).status_code, 200)

    def test_missing_lips_leave_look_intact_and_speak_retryable(self):
        session_id = self.begun()
        save_look(session_id, {'faceScore': 95, 'cosine': .8, 'blinkScore': 90, 'blinkCount': 1,
                              'flashScore': 90, 'reflectionDelta': .1, 'reflectionR': .5, 'detailJson': '{}'})
        before = dict(get_result(session_id))
        a, b, c, _ = self.patches()
        with a, b, c, patch.object(profiles, 'measure_landmarks', return_value=(None, [])):
            response = self.client.post(f'/api/session/{session_id}/speak', headers=self.headers, json=self.payload())
        self.assertEqual(response.get_json()['reason'], 'insufficient_lip_evidence')
        self.assertEqual(dict(get_result(session_id)), before)
        a, b, c, d = self.patches()
        with a, b, c, d:
            self.assertEqual(self.client.post(f'/api/session/{session_id}/speak', headers=self.headers, json=self.payload()).status_code, 200)

    def test_legacy_never_requires_landmarks_or_complete_flash_evidence(self):
        self.app.config['VERIFICATION_PROFILE'] = 'legacy'
        session_id = self.begun()
        face = {'ok': True, 'faceScore': 95, 'cosine': .8}
        blink = {'ok': True, 'blinkScore': 90, 'blinkCount': 1, 'dipPercent': 60}
        missing_flash = {'ok': True, 'flashScore': 50, 'reflectionDelta': None, 'reflectionR': None, 'detail': 'too_few_flash_frames'}
        with patch.object(profiles, 'match_pre_flash', return_value=face), \
                patch.object(profiles, 'score_pre_flash', return_value=blink), \
                patch.object(profiles, 'score_flash_frames', return_value=missing_flash), \
                patch.object(profiles, 'measure_landmarks') as landmarks:
            response = self.client.post(f'/api/session/{session_id}/look', headers=self.headers, json=self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['flashScore'], 50)
        landmarks.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
