"""Task 16 word verification, persistence, migration, races and legacy compatibility."""
import contextlib
import os
import base64
import base64
import io
import json
import sys
import tempfile
import threading
import time
import unittest
import wave
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import jwt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from config import Config
from app import create_app
from app.models import (connect, create_session, get_session, get_result, get_user_by_username,
                        save_face_embedding, save_look, save_voice, save_trust, reserve_speak,
                        finish_speak, clear_attempt, init_db, get_certificate_for_session)
from app.services import speech, verification_profiles as profiles
from app.services.certificate import issue_certificate, chain_status
from app.routes import verification
from uploads_quality import capture, audio
from speak_identity import LOOK, ACOUSTIC, LIP
from speech_fixture import evidence
import gate_fixture


def recognition(word='amber', confidence=.9):
    return {'ok': True, 'transcript': word, 'words': [{'word': word, 'confidence': confidence}],
            **speech._metadata()}


class WordRules(unittest.TestCase):
    def test_exact_confidence_boundary_case_punctuation_and_token_normalization(self):
        for text in ('amber', ' AMBER! ', '"Amber."'):
            value = {'ok': True, 'transcript': text, 'words': [{'word': 'Amber', 'confidence': .8}]}
            self.assertTrue(speech.verify_transcript(value, 'amber')['ok'])
        value = {'ok': True, 'transcript': 'amber', 'words': [{'word': 'amber', 'confidence': .79999}]}
        self.assertEqual(speech.verify_transcript(value, 'amber')['reason'], 'word_confidence_low')

    def test_empty_wrong_multiple_words_and_disagreeing_word_records(self):
        for text, reason in (('', 'word_not_heard'), ('bridge', 'wrong_word'),
                             ('say amber', 'ambiguous_word'), ('amber amber', 'ambiguous_word'),
                             ('amber123', 'wrong_word'), ("amber's", 'ambiguous_word')):
            self.assertEqual(speech.verify_transcript({'ok': True, 'transcript': text}, 'amber')['reason'], reason)
        for words in ([], None, [{'word': 'bridge', 'confidence': .9}],
                      [{'word': 'amber', 'confidence': .9}] * 2):
            self.assertEqual(speech.verify_transcript({'ok': True, 'transcript': 'amber', 'words': words}, 'amber')['reason'],
                             'word_confidence_missing')

    def test_missing_nonfinite_non_numeric_and_impossible_confidence(self):
        for confidence in (None, True, '0.9', float('nan'), float('inf'), -.1, 1.1):
            result = {'ok': True, 'transcript': 'amber', 'words': [{'word': 'amber', 'confidence': confidence}]}
            self.assertEqual(speech.verify_transcript(result, 'amber')['reason'], 'word_confidence_missing')


class WordApi(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='authx-word-')
        self.addCleanup(temp.cleanup)
        self.db = Path(temp.name) / 'test.db'
        cfg = patch.multiple(Config, DATABASE_PATH=self.db, VERIFICATION_PROFILE='v2', CHALLENGE_WORDS=('amber',))
        cfg.start()
        self.addCleanup(cfg.stop)
        with contextlib.redirect_stdout(io.StringIO()):
            self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.user = get_user_by_username('avinash')
        save_face_embedding(self.user['id'], '[0.1]')
        self.headers = self.auth(self.user)
        ctx = self.app.app_context()
        ctx.push()
        self.addCleanup(ctx.pop)
        # Isolate already-tested face/lip calculations while running real word policy.
        for mock in (patch.object(verification, 'speech_availability', return_value={'ok': True}),
                     patch.object(profiles, 'match_quality_frames', return_value={'ok': True, 'cosine': .8}),
                     patch.object(profiles, '_landmark_voice', side_effect=self.scored_voice)):
            mock.start()
            self.addCleanup(mock.stop)

    def auth(self, user):
        token = jwt.encode({'sub': str(user['id'])}, self.app.config['JWT_SECRET'], algorithm='HS256')
        return {'Authorization': 'Bearer ' + token}

    def scored_voice(self, *args):
        return {'ok': True, 'acousticScore': 100, 'lipScore': 100, 'lipR': .8, 'voiceScore': 100,
                'acoustic': ACOUSTIC, 'lip': LIP,
                'detail': {'rms': .05, 'speechRatio': .8, 'mfccVariation': 40,
                           'speakGateEvidence': gate_fixture.record(lip=gate_fixture.lip()),
                           'speakMeasurement': {'measurementVersion': 'fixture'}}}

    def begun(self, profile='v2', look=True):
        self.app.config['VERIFICATION_PROFILE'] = profile
        started = self.client.post('/api/session/start', headers=self.headers).get_json()
        if look:
            save_look(started['sessionId'], {**LOOK, 'detailJson': json.dumps({
                'lookMeasurement': {'version': 'preserved'}, **gate_fixture.look_detail()})})
        return started['sessionId']

    def speak(self, session_id, result=None, **extra):
        with patch.object(speech, 'transcribe', return_value=result or recognition()):
            return self.client.post(f'/api/session/{session_id}/speak', headers=self.headers,
                                    json={**capture(), 'wav': audio(), **extra})

    def test_success_server_word_not_client_word_and_separate_evidence(self):
        session_id = self.begun()
        self.app.config['VERIFICATION_PROFILE'] = 'legacy'
        wrong = self.speak(session_id, recognition('bridge'), word='bridge', expected_word='bridge')
        self.assertEqual(wrong.get_json()['reason'], 'wrong_word')
        self.assertIsNone(get_result(session_id)['voice_score'])
        self.assertEqual(self.client.post(f'/api/session/{session_id}/trust', headers=self.headers).status_code, 422)
        self.assertEqual(self.speak(session_id).status_code, 200)
        row = get_result(session_id)
        detail = json.loads(row['detail_json'])
        self.assertEqual(detail['lookMeasurement'], {'version': 'preserved'})
        self.assertIn('speakMeasurement', detail)
        self.assertTrue(speech.stored_word_verified(row['detail_json'], 'amber'))
        self.assertFalse(detail['speech']['grammarRestricted'])
        self.assertEqual(get_session(session_id)['speak_attempts'], 2)
        self.assertEqual(self.speak(session_id).get_json()['reason'], 'speak_locked')
        self.assertEqual(get_session(session_id)['speak_attempts'], 2)
        trust = self.client.post(f'/api/session/{session_id}/trust', headers=self.headers)
        self.assertEqual(trust.get_json()['riskLabel'], 'SAFE')
        issued = self.client.post(f'/api/session/{session_id}/certificate', headers=self.headers).get_json()
        self.assertEqual(chain_status(issued['certId']), 'intact')
        # Successful response keeps existing fields; recordings never enter evidence.
        self.assertNotIn('wav', detail)
        self.assertNotIn('frames', detail)

    def test_initial_plus_three_retries_then_restart_reopen_and_fresh_session(self):
        session_id = self.begun()
        before = dict(get_result(session_id))
        for index in range(4):
            response = self.speak(session_id, recognition('bridge'))
            body = response.get_json()
            self.assertEqual(response.status_code, 422)
            self.assertEqual(body['attemptsUsed'], index + 1)
            self.assertEqual(body['attemptsRemaining'], 3 - index)
            self.assertEqual(body['reason'], 'wrong_word' if index < 3 else 'speak_attempts_exhausted')
            self.assertEqual(dict(get_result(session_id)), before)
        self.assertEqual(body['attemptReason'], 'wrong_word')
        self.assertTrue(body['freshSessionRequired'])
        recorded = json.loads(get_session(session_id)['speak_last_evidence'])
        self.assertEqual(recorded['speech']['transcript'], 'bridge')
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.assertEqual(self.speak(session_id).status_code, 409)
        faculty = self.auth(get_user_by_username('sriram'))
        reopened = self.client.post(f'/api/session/{session_id}/reopen', headers=faculty)
        self.assertEqual(reopened.get_json()['reason'], 'speak_attempts_exhausted')
        self.assertEqual(get_session(session_id)['speak_attempts'], 4)
        fresh = self.begun()
        self.assertNotEqual(fresh, session_id)
        self.assertEqual(self.speak(fresh).status_code, 200)

    def test_fourth_attempt_can_succeed(self):
        session_id = self.begun()
        for _ in range(3):
            self.assertEqual(self.speak(session_id, recognition('bridge')).status_code, 422)
        self.assertEqual(self.speak(session_id, recognition(confidence=.8)).status_code, 200)
        self.assertEqual(get_session(session_id)['speak_attempts'], 4)
        self.assertEqual(self.speak(session_id).get_json()['reason'], 'speak_locked')

    def test_real_offline_synthetic_word_wrong_word_and_phrase_through_api(self):
        records = []
        with patch.object(verification, 'speech_availability', wraps=speech.availability), \
                patch('socket.socket.connect', side_effect=AssertionError('network forbidden')):
            for name, expected in (('amber', None), ('bridge', 'wrong_word'), ('phrase', 'ambiguous_word')):
                fixture = ROOT / f'.runtime/fixtures/speech-{name}.wav'
                self.assertTrue(fixture.is_file(), 'Generate the documented offline SAPI fixtures')
                with wave.open(str(fixture), 'rb') as handle:
                    self.assertEqual((handle.getnchannels(), handle.getsampwidth()), (1, 2))
                    rate = handle.getframerate()
                    raw = handle.readframes(handle.getnframes())
                raw = (raw + b'\0' * rate * 3 * 2)[:rate * 3 * 2]
                output = io.BytesIO()
                with wave.open(output, 'wb') as handle:
                    handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(rate)
                    handle.writeframes(raw)
                session_id = self.begun()
                response = self.client.post(f'/api/session/{session_id}/speak', headers=self.headers,
                                            json={**capture(), 'wav': base64.b64encode(output.getvalue()).decode()})
                self.assertEqual(response.status_code, 200 if expected is None else 422, response.get_json())
                self.assertEqual(response.get_json().get('reason'), expected)
                record = json.loads(get_session(session_id)['speak_last_evidence'])
                records.append({'fixture': name, 'response': response.get_json(), 'speech': record['speech']})
                if expected:
                    self.assertIsNone(get_result(session_id)['voice_score'])
                    self.assertEqual(self.client.post(f'/api/session/{session_id}/certificate', headers=self.headers).status_code, 422)
        (Path(os.environ.get('AUTHX_TEST_OUTPUT_DIR', str(Config.DATABASE_PATH.parent))) / 'synthetic-api-inference.json').write_text(json.dumps(records, indent=2))

    def test_real_offline_synthetic_word_wrong_word_and_phrase_through_api(self):
        records = []
        with patch.object(verification, 'speech_availability', wraps=speech.availability), \
                patch('socket.socket.connect', side_effect=AssertionError('network forbidden')):
            for name, expected in (('amber', None), ('bridge', 'wrong_word'), ('phrase', 'ambiguous_word')):
                fixture = ROOT / f'.runtime/fixtures/speech-{name}.wav'
                self.assertTrue(fixture.is_file(), 'Generate the documented offline SAPI fixtures')
                with wave.open(str(fixture), 'rb') as handle:
                    self.assertEqual((handle.getnchannels(), handle.getsampwidth()), (1, 2))
                    rate = handle.getframerate()
                    raw = handle.readframes(handle.getnframes())
                raw = (raw + b'\0' * rate * 3 * 2)[:rate * 3 * 2]
                output = io.BytesIO()
                with wave.open(output, 'wb') as handle:
                    handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(rate)
                    handle.writeframes(raw)
                session_id = self.begun()
                response = self.client.post(f'/api/session/{session_id}/speak', headers=self.headers,
                                            json={**capture(), 'wav': base64.b64encode(output.getvalue()).decode()})
                self.assertEqual(response.status_code, 200 if expected is None else 422, response.get_json())
                self.assertEqual(response.get_json().get('reason'), expected)
                record = json.loads(get_session(session_id)['speak_last_evidence'])
                records.append({'fixture': name, 'response': response.get_json(), 'speech': record['speech']})
                if expected:
                    self.assertIsNone(get_result(session_id)['voice_score'])
                    self.assertEqual(self.client.post(f'/api/session/{session_id}/certificate', headers=self.headers).status_code, 422)
        (Path(os.environ.get('AUTHX_TEST_OUTPUT_DIR', str(Config.DATABASE_PATH.parent))) / 'synthetic-api-inference.json').write_text(json.dumps(records, indent=2))

    def test_authorization_look_validation_and_model_failures_do_not_consume(self):
        session_id = self.begun(look=False)
        self.assertEqual(self.speak(session_id).get_json()['reason'], 'look_required')
        save_look(session_id, LOOK)
        foreign = self.auth(get_user_by_username('sriram'))
        self.assertEqual(self.client.post(f'/api/session/{session_id}/speak', headers=foreign).status_code, 403)
        self.assertEqual(self.client.post(f'/api/session/{session_id}/speak').status_code, 401)
        self.assertEqual(self.client.post(f'/api/session/{session_id}/speak', headers=self.headers, json={}).status_code, 400)
        for reason in ('speech_model_missing', 'speech_model_invalid', 'speech_runtime_unavailable'):
            with patch.object(verification, 'speech_availability', return_value={'ok': False, 'reason': reason}):
                self.assertEqual(self.speak(session_id).status_code, 503)
        self.assertEqual(get_session(session_id)['speak_attempts'], 0)
        # Runtime failure after reserving must refund, and stay usable after setup repair.
        failed = self.speak(session_id, {'ok': False, 'reason': 'speech_runtime_unavailable'})
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(get_session(session_id)['speak_attempts'], 0)
        self.assertIsNone(get_session(session_id)['speak_token'])
        with patch.object(profiles, '_landmark_voice', side_effect=RuntimeError('fixture failure')):
            self.assertEqual(self.speak(session_id).status_code, 503)
        self.assertEqual(get_session(session_id)['speak_attempts'], 0)
        self.assertEqual(self.speak(session_id).status_code, 200)

    def test_valid_quality_lip_and_word_failures_consume_and_persist_last_only(self):
        session_id = self.begun()
        for reason in ('no_face', 'insufficient_lip_evidence'):
            with patch.object(profiles, 'match_quality_frames', return_value={'ok': False, 'reason': reason, 'detail': 'missing evidence'}):
                response = self.speak(session_id)
            self.assertEqual(response.get_json()['reason'], reason)
        self.assertEqual(self.speak(session_id, recognition(confidence=.79)).get_json()['reason'], 'word_confidence_low')
        self.assertEqual(get_session(session_id)['speak_attempts'], 3)
        self.assertIsNone(get_result(session_id)['voice_score'])
        last = json.loads(get_session(session_id)['speak_last_evidence'])
        self.assertEqual(last['speech']['words'][0]['confidence'], .79)

    def test_reopen_before_exhaustion_retains_budget(self):
        session_id = self.begun()
        self.speak(session_id, recognition('bridge'))
        self.assertIsNone(clear_attempt(session_id))
        self.assertEqual(get_session(session_id)['speak_attempts'], 1)
        save_look(session_id, LOOK)
        self.assertEqual(self.speak(session_id, recognition('bridge')).get_json()['attemptsUsed'], 2)

    def test_concurrent_api_submissions_have_one_reservation_and_no_reopen(self):
        session_id = self.begun()
        entered, release = threading.Event(), threading.Event()
        def slow(samples, rate):
            entered.set()
            if not release.wait(10):
                raise RuntimeError('test synchronization timeout')
            return recognition('bridge')
        def submit():
            with self.app.test_client() as client:
                return client.post(f'/api/session/{session_id}/speak', headers=self.headers,
                                   json={**capture(), 'wav': audio()})
        with patch.object(speech, 'transcribe', side_effect=slow), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(submit)
            try:
                self.assertTrue(entered.wait(5))
                second = submit()
                self.assertEqual(second.get_json()['reason'], 'speak_in_progress')
                self.assertEqual(clear_attempt(session_id), 'speak_in_progress')
                self.assertEqual(get_session(session_id)['speak_attempts'], 1)
            finally:
                release.set()
            self.assertEqual(first.result().get_json()['reason'], 'wrong_word')
        self.assertEqual(get_session(session_id)['speak_attempts'], 1)

    def test_database_reservations_race_and_abandoned_lease_cannot_bypass(self):
        session_id = self.begun()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: reserve_speak(session_id, self.user['id'], self.db), range(8)))
        winners = [value for value in results if value['ok']]
        self.assertEqual(len(winners), 1)
        old = winners[0]
        self.assertEqual(get_session(session_id)['speak_attempts'], 1)
        # A dead worker is recovered after two minutes, but its reserved attempt stays spent.
        with contextlib.closing(connect()) as conn:
            conn.execute('UPDATE sessions SET speak_reserved_at = ? WHERE id = ?', (time.time() - 121, session_id))
            conn.commit()
        new = reserve_speak(session_id, self.user['id'])
        self.assertTrue(new['ok'])
        self.assertEqual(finish_speak(session_id, old, {'ok': False, 'reason': 'wrong_word'})['reason'], 'speak_attempt_superseded')
        self.assertEqual(get_session(session_id)['speak_token'], new['token'])
        finish_speak(session_id, new, {'ok': False, 'reason': 'wrong_word'})
        self.assertEqual(get_session(session_id)['speak_attempts'], 2)

    def test_historical_missing_evidence_blocks_new_trust_and_certificate_preserves_issued(self):
        session_id = self.begun()
        scores = self.scored_voice()
        scores['speakCosine'] = .8
        save_voice(session_id, scores)
        self.assertEqual(self.client.post(f'/api/session/{session_id}/trust', headers=self.headers).get_json()['reason'], 'word_required')
        save_trust(session_id, 99, 'SAFE')  # historical pre-word result
        rejected = self.client.post(f'/api/session/{session_id}/certificate', headers=self.headers)
        self.assertEqual(rejected.get_json()['reason'], 'word_required')
        self.assertIsNone(get_certificate_for_session(session_id))
        # Insert the historical snapshot explicitly; current issuance must not bypass new gates.
        from app.models import insert_certificate, _utc_now
        from app.services.certificate import _score_json, block_hash
        created = _utc_now()
        historical_session = {**dict(get_session(session_id)), 'verification_profile': 'legacy'}
        frozen_scores = _score_json(historical_session, get_result(session_id))
        insert_certificate(session_id, 'AX-historical', block_hash('GENESIS', session_id, 99, created, frozen_scores),
                           'GENESIS', frozen_scores, created)
        issued = get_certificate_for_session(session_id)
        before = dict(issued)
        repeated = self.client.post(f'/api/session/{session_id}/certificate', headers=self.headers)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(dict(get_certificate_for_session(session_id)), before)
        self.assertEqual(chain_status(issued['cert_id']), 'intact')

    def test_legacy_and_standalone_do_not_require_word_or_budget(self):
        session_id = self.begun('legacy')
        with patch.object(verification, 'speech_availability', side_effect=AssertionError('legacy speech call')), \
                patch.object(speech, 'transcribe', side_effect=AssertionError('legacy recognizer')), \
                patch.object(profiles, 'score_wave', return_value=ACOUSTIC), \
                patch.object(profiles, 'score_lip_frames', return_value=LIP):
            response = self.client.post(f'/api/session/{session_id}/speak', headers=self.headers,
                                        json={**capture(), 'wav': audio()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_session(session_id)['speak_attempts'], 0)
        self.assertEqual(self.client.post(f'/api/session/{session_id}/trust', headers=self.headers).status_code, 200)
        self.app.config['VERIFICATION_PROFILE'] = 'v2'
        with patch.object(speech, 'transcribe', side_effect=AssertionError('standalone recognition')), \
                patch.object(profiles, 'inspect_clip', return_value=(None, [])):
            response = self.client.post('/api/voice/score', headers=self.headers, json={**capture(), 'wav': audio()})
        self.assertEqual(response.status_code, 200)

    def test_additive_retry_migration_preserves_all_existing_columns(self):
        session_id = self.begun('legacy')
        save_voice(session_id, self.scored_voice())
        self.client.post(f'/api/session/{session_id}/trust', headers=self.headers)
        issued = issue_certificate(session_id)
        with contextlib.closing(connect()) as conn:
            for column in ('speak_attempts', 'speak_token', 'speak_reserved_at', 'speak_last_evidence'):
                conn.execute(f'ALTER TABLE sessions DROP COLUMN {column}')
            conn.commit()
            old = [dict(row) for row in conn.execute('SELECT * FROM sessions')]
        before_result = dict(get_result(session_id))
        before_cert = dict(issued)
        init_db()
        init_db()
        session = dict(get_session(session_id))
        for key, value in old[0].items():
            self.assertEqual(session[key], value)
        self.assertEqual(session['speak_attempts'], 0)
        self.assertIsNone(session['speak_last_evidence'])
        self.assertEqual(dict(get_result(session_id)), before_result)
        self.assertEqual(dict(get_certificate_for_session(session_id)), before_cert)
        self.assertEqual(chain_status(issued['cert_id']), 'intact')

    def test_threshold_cannot_silently_be_lowered_and_stored_evidence_is_checked(self):
        session_id = self.begun()
        for minimum in (.79, float('nan'), True):
            self.app.config['V2_WORD_MIN_CONFIDENCE'] = minimum
            self.assertEqual(self.speak(session_id).get_json()['reason'], 'speech_configuration_invalid')
            self.assertEqual(get_session(session_id)['speak_attempts'], 0)
        for change in ({'wordVerified': False}, {'grammarRestricted': True}, {'expectedWord': 'bridge'},
                       {'words': [{'word': 'amber', 'confidence': .79999}]}, {'minimumConfidence': .7}):
            self.assertFalse(speech.stored_word_verified(json.dumps({'speech': {**evidence(), **change}}), 'amber'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
