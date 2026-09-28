"""Task 18 additive API fields, escaped views and immutable certificate evidence."""
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import jwt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import uploads_quality as captures
import landmark_evidence as geometry_tests
from app.models import (connect, get_session, get_result, get_user_by_username, save_look, save_voice,
                        save_trust, get_certificate_for_session, insert_certificate, _utc_now, set_risk_label)
from app.services.certificate import chain_status, block_hash, issue_certificate, _score_json
from app.services.evidence_summary import session_fields, certificate_fields, display_lines
from speak_identity import LOOK
import gate_fixture

OPTIONAL = {'verificationVersion', 'evidence', 'retryable'}


class SummaryTests(unittest.TestCase):
    setUp = captures.UploadTests.setUp
    start = captures.UploadTests.start
    payload = geometry_tests.EvidenceApiTests.payload
    measured = geometry_tests.EvidenceApiTests.measured
    patches = geometry_tests.EvidenceApiTests.patches
    measured_begun = geometry_tests.EvidenceApiTests.begun

    def auth(self, username):
        user = get_user_by_username(username)
        token = jwt.encode({'sub': str(user['id'])}, self.app.config['JWT_SECRET'], algorithm='HS256')
        return {'Authorization': 'Bearer ' + token}

    def post(self, session_id, step, **options):
        return self.client.post(f'/api/session/{session_id}/{step}', headers=self.headers, **options)

    def saved(self, profile='v2', evidence=True):
        self.app.config['VERIFICATION_PROFILE'] = profile
        session_id = self.start()
        word = get_session(session_id)['challenge_word']
        save_look(session_id, LOOK if evidence else {**LOOK, 'detailJson': '{}'})
        detail = gate_fixture.speak_detail(word) if evidence else {}
        detail.update(rms=.05, speechRatio=.8, mfccVariation=40)
        save_voice(session_id, {'acousticScore': 100, 'lipScore': 100, 'lipR': .8, 'voiceScore': 100,
                                'speakCosine': .8, 'detail': detail})
        return session_id

    def test_optional_fields_add_to_start_look_speak_trust_certificate(self):
        started = self.client.post('/api/session/start', headers=self.headers).get_json()
        self.assertEqual(set(started), {'ok', 'sessionId', 'word', 'flashStartMs', 'captureFrameMs'} | OPTIONAL)
        self.assertTrue(started['retryable'])
        session_id = self.measured_begun()
        a, b, c, d = self.patches()
        with a, b, c, d:
            looked = self.post(session_id, 'look', json=self.payload()).get_json()
            self.assertEqual(set(looked), {'ok', 'faceScore', 'cosine', 'blinkScore', 'blinkCount', 'dipPercent',
                                         'flashScore', 'reflectionDelta', 'reflectionR'} | OPTIONAL)
            self.assertTrue(looked['retryable'])
            spoken = self.post(session_id, 'speak', json=self.payload()).get_json()
            self.assertEqual(set(spoken), {'ok', 'acousticScore', 'lipScore', 'lipR', 'voiceScore', 'rms',
                                         'speechRatio', 'mfccVariation'} | OPTIONAL)
            self.assertFalse(spoken['retryable'])
            self.assertEqual(spoken['verificationVersion'], 'v2')
            self.assertTrue(spoken['evidence']['safeEligible'])
            self.assertTrue(spoken['evidence']['speech']['verified'])
        trusted = self.post(session_id, 'trust').get_json()
        self.assertEqual(set(trusted), {'ok', 'trustScore', 'riskLabel', 'base', 'flashAdjust'} | OPTIONAL)
        self.assertEqual(trusted['evidence']['machineDecision']['riskLabel'], 'SAFE')
        issued = self.post(session_id, 'certificate').get_json()
        self.assertEqual(set(issued), {'ok', 'certId', 'prevHash', 'blockHash'} | OPTIONAL)
        self.assertFalse(issued['retryable'])
        self.assertEqual(chain_status(issued['certId']), 'intact')

    def test_historical_v2_unknown_gates_do_not_change_stored_label_on_display(self):
        session_id = self.saved(evidence=False)
        save_trust(session_id, 99, 'SAFE')
        before = dict(get_session(session_id)), dict(get_result(session_id))
        response = self.client.get(f'/api/faculty/sessions/{session_id}', headers=self.auth('sriram'))
        data = response.get_json()
        self.assertEqual(data['riskLabel'], 'SAFE')
        self.assertEqual(data['verificationVersion'], 'v2')
        self.assertIsNone(data['evidence']['machineDecision'])
        self.assertFalse(data['evidence']['safeEligible'])
        states = {check['key']: check['status'] for check in data['evidence']['checks']}
        self.assertEqual(states['blink'], 'not_recorded')
        self.assertEqual(states['word'], 'not_recorded')
        self.assertEqual((dict(get_session(session_id)), dict(get_result(session_id))), before)

    def test_faculty_label_changes_do_not_claim_machine_checks_passed(self):
        session_id = self.saved()
        conn = connect()
        try:
            conn.execute('UPDATE results SET speak_cosine = .1 WHERE session_id = ?', (session_id,))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self.post(session_id, 'trust').get_json()['riskLabel'], 'SUSPICIOUS')
        response = self.client.post(f'/api/faculty/sessions/{session_id}/override', headers=self.auth('sriram'), json={'label': 'SAFE'})
        self.assertEqual(response.status_code, 200)
        data = self.client.get(f'/api/faculty/sessions/{session_id}', headers=self.auth('sriram')).get_json()
        self.assertEqual(data['riskLabel'], 'SAFE')
        self.assertEqual(data['evidence']['machineDecision']['riskLabel'], 'SUSPICIOUS')
        self.assertFalse(data['evidence']['safeEligible'])
        self.assertIn('faculty', data['evidence']['labelNote'])
        cert = self.post(session_id, 'certificate').get_json()
        record = json.loads(get_certificate_for_session(session_id)['score_json'])
        self.assertEqual(record['riskLabel'], 'SAFE')
        self.assertEqual(record['evidence']['machineDecision']['riskLabel'], 'SUSPICIOUS')
        self.assertEqual(chain_status(cert['certId']), 'intact')

    def test_new_certificate_freezes_evidence_versions_config_and_machine_label(self):
        session_id = self.saved()
        trusted = self.post(session_id, 'trust').get_json()
        issued = self.post(session_id, 'certificate').get_json()
        frozen = dict(get_certificate_for_session(session_id))
        record = json.loads(frozen['score_json'])
        self.assertEqual(record['verificationVersion'], 'v2')
        self.assertEqual(record['evidence']['policyVersion'], 'v2-decision-gates-1')
        self.assertEqual(record['evidence']['decisionConfig']['SAFE_MIN'], 75)
        self.assertEqual(record['evidence']['speech']['voskVersion'], '0.3.45')
        before_page = self.client.get('/certificate/' + issued['certId']).get_data(as_text=True)
        conn = connect()
        try:
            conn.execute('UPDATE results SET detail_json = ?, cosine = 0, voice_score = 0 WHERE session_id = ?', ('{}', session_id))
            conn.execute("UPDATE sessions SET challenge_word = 'changed', risk_label = 'DEEPFAKE', speak_last_evidence = '{}' WHERE id = ?", (session_id,))
            conn.commit()
        finally:
            conn.close()
        self.app.config.update(VERIFICATION_PROFILE='legacy', COSINE_MATCH=.99, V2_WORD_MIN_CONFIDENCE=.99)
        repeated = self.post(session_id, 'certificate').get_json()
        self.assertEqual(issued, repeated)
        self.assertEqual(dict(get_certificate_for_session(session_id)), frozen)
        self.assertEqual(self.client.get('/certificate/' + issued['certId']).get_data(as_text=True), before_page)
        self.assertEqual(chain_status(issued['certId']), 'intact')

    def test_legacy_and_historical_certificates_keep_original_bytes_and_hash_format(self):
        session_id = self.saved(profile='legacy', evidence=False)
        self.post(session_id, 'trust')
        cert = issue_certificate(session_id)
        before = dict(cert)
        record = json.loads(cert['score_json'])
        self.assertNotIn('verificationVersion', record)
        self.assertNotIn('evidence', record)
        self.assertEqual(cert['block_hash'], block_hash(cert['prev_hash'], session_id, record['trustScore'], cert['created_at'], cert['score_json']))
        self.app.config['VERIFICATION_PROFILE'] = 'v2'
        data = self.post(session_id, 'certificate').get_json()
        self.assertEqual(data['verificationVersion'], 'not_recorded')
        self.assertIn('not recorded', data['evidence']['summary'])
        self.assertEqual(dict(get_certificate_for_session(session_id)), before)
        page = self.client.get('/certificate/' + cert['cert_id']).get_data(as_text=True)
        self.assertIn('Evidence snapshot not recorded', page)
        self.assertIn('intact', page)

    def test_transcript_confidence_escaping_and_bounded_data(self):
        session_id = self.start()
        dangerous = '<script>alert(1)</script>'
        last = {'reason': 'wrong_word', 'speech': {'transcript': dangerous, 'expectedWord': 'amber',
                'words': [{'word': dangerous, 'confidence': .9}], 'minimumConfidence': .8, 'wordVerified': False}}
        conn = connect()
        try:
            conn.execute('UPDATE sessions SET speak_last_evidence = ? WHERE id = ?', (json.dumps(last), session_id))
            conn.commit()
        finally:
            conn.close()
        fields = session_fields(get_session(session_id), None)
        lines = display_lines(fields)
        self.assertIn(dangerous, ' '.join(lines))
        self.assertIn('confidence 0.90', ' '.join(lines))
        # A deliberately old/imported snapshot checks Jinja escaping independently of recognition.
        record = {'riskLabel': 'SAFE', 'trustScore': 90, 'word': dangerous, 'verificationVersion': 'v2',
                  'evidence': {**fields['evidence'], 'summary': dangerous}}
        frozen = json.dumps(record, sort_keys=True)
        created = _utc_now()
        insert_certificate(session_id, 'AX-escaped', block_hash('GENESIS', session_id, 90, created, frozen), 'GENESIS', frozen, created)
        page = self.client.get('/certificate/AX-escaped').get_data(as_text=True)
        self.assertNotIn(dangerous, page)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', page)
        last['speech']['transcript'] = 'x' * 5000
        last['speech']['words'] = [{'word': 'x' * 500, 'confidence': float('nan')}] * 100
        conn = connect()
        try:
            conn.execute('UPDATE sessions SET speak_last_evidence = ? WHERE id = ?', (json.dumps(last), session_id))
            conn.commit()
        finally:
            conn.close()
        bounded = session_fields(get_session(session_id), None)['evidence']['speech']
        self.assertEqual(len(bounded['transcript']), 1000)
        self.assertEqual(len(bounded['words']), 16)
        self.assertEqual(len(bounded['words'][0]['word']), 64)
        self.assertIsNone(bounded['words'][0]['confidence'])
        json.dumps(bounded, allow_nan=False)

    def test_retry_fields_failure_and_setup_guidance_preserve_budget(self):
        session_id = self.start()
        save_look(session_id, LOOK)
        response = self.post(session_id, 'speak', json={})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.get_json()['retryable'])
        self.assertEqual(get_session(session_id)['speak_attempts'], 0)
        from app.routes import verification
        with patch.object(verification, 'speech_availability', return_value={'ok': False, 'reason': 'speech_model_missing'}):
            response = self.post(session_id, 'speak', json={**captures.capture(), 'wav': captures.audio()})
        self.assertEqual(response.status_code, 503)
        self.assertTrue(response.get_json()['retryable'])
        conn = connect()
        try:
            conn.execute('UPDATE sessions SET speak_attempts = 4 WHERE id = ?', (session_id,))
            conn.commit()
        finally:
            conn.close()
        response = self.post(session_id, 'speak', json={})
        self.assertFalse(response.get_json()['retryable'])
        self.assertTrue(response.get_json()['freshSessionRequired'])

    def test_role_ownership_and_html_do_not_leak_summary_or_private_data(self):
        session_id = self.saved()
        for headers in ({}, self.headers):
            response = self.client.get(f'/api/faculty/sessions/{session_id}', headers=headers)
            self.assertIn(response.status_code, (401, 403))
            self.assertNotIn('evidence', response.get_json())
        forbidden = self.client.post(f'/api/session/{session_id}/trust', headers=self.auth('sriram'))
        self.assertEqual(forbidden.status_code, 403)
        self.assertNotIn('evidence', forbidden.get_json())
        page = self.client.get(f'/faculty/session/{session_id}').get_data(as_text=True)
        self.assertNotIn('confidence 0.90', page)
        fields = session_fields(get_session(session_id), get_result(session_id))
        raw = json.dumps(fields)
        for name in ('face_embedding', 'password_hash', 'otp_hash', 'wav', 'approvedFrames'):
            self.assertNotIn(name, raw)

    def test_read_only_display_uses_saved_machine_snapshot_across_config_switch(self):
        session_id = self.saved()
        self.post(session_id, 'trust')
        first = session_fields(get_session(session_id), get_result(session_id))
        self.app.config['COSINE_MATCH'] = .99
        self.app.config['VERIFICATION_PROFILE'] = 'legacy'
        second = session_fields(get_session(session_id), get_result(session_id))
        self.assertEqual(first, second)
        self.assertEqual(get_session(session_id)['trust_score'], 100)


if __name__ == '__main__':
    unittest.main(verbosity=2)
