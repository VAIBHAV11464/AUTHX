"""Task 11 timing validation and pinned capture selection on temporary DBs."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import uploads_quality as fixtures
from app.models import get_result, save_look
from app.services import uploads, verification_profiles as profiles


class TimingTests(unittest.TestCase):
    setUp = fixtures.UploadTests.setUp

    def test_optional_offset_and_invalid_values(self):
        self.assertEqual(uploads.audio_start_ms({}), 0)
        for value in (0, 30.5, 250):
            self.assertEqual(uploads.audio_start_ms({'audioStartMs': value}), value)
        for value in (None, True, '30', -1, 251, float('nan'), float('inf'), 10 ** 400):
            with self.subTest(value=value), self.assertRaises(uploads.UploadError) as exc:
                uploads.audio_start_ms({'audioStartMs': value})
            self.assertEqual(exc.exception.reason, 'bad_audio_timing')

    def test_start_returns_capture_selection_from_session_profile(self):
        for profile, expected in (('legacy', None), ('v2', 50)):
            self.app.config['VERIFICATION_PROFILE'] = profile
            response = self.client.post('/api/session/start', headers=self.headers)
            self.assertEqual(response.get_json().get('captureFrameMs'), expected)

    def test_sample_clock_offset_reaches_landmark_lip_measurement(self):
        frames = [(0, 'early'), (100, 'middle'), (200, 'late')]
        scored = {'ok': True, 'detail': {}}
        with patch.object(profiles, 'match_quality_frames', return_value={'ok': True, 'cosine': .8}), \
                patch.object(profiles, 'measure_landmarks', return_value=(None, ['measured'])), \
                patch.object(profiles, 'score_landmark_lips', return_value={'ok': True}) as lip, \
                patch.object(profiles, '_legacy_speak', return_value=scored):
            result = profiles.get_profile('v2').score_speak(frames, [], 16000, embedding='stored', expected_word='amber', audio_start_ms=30)
        self.assertEqual(lip.call_args.args, (['measured'], [], 16000, 30))
        self.assertEqual(result['detail']['audioStartMs'], 30)

    def test_invalid_timing_cannot_save_speak(self):
        session_id = self.client.post('/api/session/start', headers=self.headers).get_json()['sessionId']
        save_look(session_id, {'faceScore': 100, 'cosine': .8, 'blinkScore': 90, 'blinkCount': 1,
                              'flashScore': 90, 'reflectionDelta': .1, 'reflectionR': .5, 'detailJson': '{}'})
        with patch.object(profiles, '_v2_speak') as scorer:
            response = self.client.post(f'/api/session/{session_id}/speak', headers=self.headers,
                                        json={**fixtures.capture(), 'wav': fixtures.audio(), 'audioStartMs': -1})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['reason'], 'bad_audio_timing')
        self.assertIsNone(get_result(session_id)['voice_score'])
        scorer.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
