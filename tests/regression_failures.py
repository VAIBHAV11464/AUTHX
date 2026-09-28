"""Task 21 gaps: completed auth, OTP races, permissions, setup and history."""
import contextlib
import io
import json
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import bcrypt
import jwt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import evidence_summaries as summaries
import uploads_quality as captures
from app import models
from app.routes import auth, verification
from app.services import speech, landmarks
from app.services.certificate import issue_certificate, chain_status


class FailureTests(unittest.TestCase):
    setUp = summaries.SummaryTests.setUp
    start = summaries.SummaryTests.start
    saved = summaries.SummaryTests.saved
    auth = summaries.SummaryTests.auth
    post = summaries.SummaryTests.post

    def sql(self, statement, params=()):
        with contextlib.closing(models.connect()) as conn:
            data = conn.execute(statement, params).fetchall()
            conn.commit()
            return data

    def otp(self, username='sriram', expires=None):
        user = models.get_user_by_username(username)
        code = '246810'  # Test-only value never delivered/printed.
        models.create_otp(user['id'], bcrypt.hashpw(code.encode(), bcrypt.gensalt(rounds=4)).decode(),
                          expires or (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat())
        return {'username': username, 'otp': code}

    def test_completed_faculty_admin_password_otp_roles_and_replay(self):
        password = 'local-test-only'
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()
        self.sql('UPDATE users SET password_hash = ?', (hashed,))
        for username, role in (('sriram', 'faculty'), ('vaibhav', 'admin')):
            codes = []
            with patch.object(auth, 'deliver_otp', side_effect=lambda user, code: codes.append(code) or 'test'):
                login = self.client.post('/api/auth/login', json={'username': username, 'password': password})
            self.assertTrue(login.get_json()['otp_required'])
            self.assertNotIn('token', login.get_json())
            self.assertNotIn(codes[0], json.dumps(login.get_json()))
            verified = self.client.post('/api/auth/otp', json={'username': username, 'otp': codes[0]})
            self.assertEqual(verified.status_code, 200)
            token = verified.get_json()['token']
            self.assertEqual(verified.get_json()['role'], role)
            headers = {'Authorization': 'Bearer ' + token}
            self.assertEqual(self.client.get('/api/faculty/ping', headers=headers).status_code, 200)
            self.assertEqual(self.client.get('/api/admin/summary', headers=headers).status_code, 200 if role == 'admin' else 403)
            self.assertEqual(self.client.post('/api/auth/otp', json={'username': username, 'otp': codes[0]}).status_code, 401)

    def test_new_login_invalidates_previous_otp_wrong_attempt_does_not_consume(self):
        data = self.otp()
        wrong = self.client.post('/api/auth/otp', json={**data, 'otp': '000000'})
        self.assertEqual(wrong.status_code, 401)
        self.assertIsNotNone(models.latest_unused_otp(models.get_user_by_username('sriram')['id']))
        user = models.get_user_by_username('sriram')
        models.create_otp(user['id'], bcrypt.hashpw(b'135790', bcrypt.gensalt(rounds=4)).decode(),
                          (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat())
        self.assertEqual(self.client.post('/api/auth/otp', json=data).status_code, 401)
        self.assertEqual(self.client.post('/api/auth/otp', json={**data, 'otp': '135790'}).status_code, 200)

    def test_otp_exact_expiry_boundary_is_rejected_and_consumed(self):
        now = datetime(2026, 9, 28, tzinfo=timezone.utc)
        data = self.otp(expires=now.isoformat())
        with patch.object(auth, '_utc_now', return_value=now):
            result = self.client.post('/api/auth/otp', json=data)
        self.assertEqual(result.status_code, 401)
        self.assertEqual(result.get_json()['error'], 'otp_expired')
        self.assertEqual(self.sql('SELECT used FROM otps')[-1]['used'], 1)

    def test_concurrent_otp_verification_issues_exactly_one_token(self):
        data = self.otp()
        barrier = Barrier(2)
        original = auth.latest_unused_otp
        def selected(*args, **kwargs):
            row = original(*args, **kwargs)
            barrier.wait(timeout=10)
            return row
        def request():
            with self.app.test_client() as client:
                return client.post('/api/auth/otp', json=data).status_code
        with patch.object(auth, 'latest_unused_otp', side_effect=selected), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: request(), range(2)))
        self.assertEqual(sorted(results), [200, 401])

    def test_otp_selected_before_new_login_cannot_issue_stale_token(self):
        data = self.otp()
        original = auth.latest_unused_otp
        def selected(user_id):
            row = original(user_id)
            models.create_otp(user_id, bcrypt.hashpw(b'135790', bcrypt.gensalt(rounds=4)).decode(),
                              (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat())
            return row
        with patch.object(auth, 'latest_unused_otp', side_effect=selected):
            result = self.client.post('/api/auth/otp', json=data)
        self.assertEqual(result.status_code, 401)

    def test_malformed_login_otp_payloads_return_json_without_writes(self):
        for endpoint in ('login', 'otp'):
            for data in (['x'], 'x', 42, True, {'username': []}, {'username': 'sriram', 'password': {}, 'otp': []}):
                response = self.client.post('/api/auth/' + endpoint, json=data)
                self.assertEqual(response.status_code, 401, (endpoint, type(data).__name__))
                self.assertFalse(response.get_json()['ok'])
        self.assertEqual(self.sql('SELECT COUNT(*) AS n FROM otps')[0]['n'], 0)

    def test_oversized_utf8_password_and_otp_fail_without_bcrypt_exception(self):
        self.otp()
        for value in ('x' * 73, '\u00e9' * 40, 'x' * 10000):
            for endpoint, field in (('login', 'password'), ('otp', 'otp')):
                response = self.client.post('/api/auth/' + endpoint, json={'username': 'sriram', field: value})
                self.assertEqual(response.status_code, 401)

    def test_corrupt_otp_timestamp_fails_closed(self):
        data = self.otp(expires='invalid')
        response = self.client.post('/api/auth/otp', json=data)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('token', response.get_json())

    def test_expiry_during_hash_verification_is_rechecked_on_consumption(self):
        now = datetime(2026, 9, 28, tzinfo=timezone.utc)
        data = self.otp(expires=(now + timedelta(milliseconds=500)).isoformat())
        with patch.object(auth, '_utc_now', side_effect=[now, now + timedelta(seconds=1)]):
            response = self.client.post('/api/auth/otp', json=data)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()['error'], 'otp_expired')
        self.assertEqual(self.sql('SELECT used FROM otps')[-1]['used'], 1)

    def test_failed_otp_consume_transaction_rolls_back_and_can_retry(self):
        data = self.otp()
        self.sql("CREATE TRIGGER block_otp BEFORE UPDATE ON otps BEGIN SELECT RAISE(ABORT, 'test rollback'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.client.post('/api/auth/otp', json=data)
        self.assertEqual(self.sql('SELECT used FROM otps')[-1]['used'], 0)
        self.sql('DROP TRIGGER block_otp')
        self.assertEqual(self.client.post('/api/auth/otp', json=data).status_code, 200)

    def test_jwt_signature_expiry_subject_and_database_role_are_authoritative(self):
        user = models.get_user_by_username('avinash')
        base = {'sub': str(user['id']), 'role': 'admin'}
        secret = self.app.config['JWT_SECRET']
        variants = [(jwt.encode(base, 'wrong-signature-test-key-32-bytes', algorithm='HS256'), 'invalid_token'),
                    (jwt.encode({**base, 'exp': 1}, secret, algorithm='HS256'), 'token_expired'),
                    (jwt.encode({**base, 'sub': 'invalid'}, secret, algorithm='HS256'), 'invalid_token'),
                    (jwt.encode({**base, 'sub': '99999'}, secret, algorithm='HS256'), 'invalid_token')]
        for token, error in variants:
            response = self.client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + token})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.get_json()['error'], error)
        forged_role = {'Authorization': 'Bearer ' + jwt.encode(base, secret, algorithm='HS256')}
        self.assertEqual(self.client.get('/api/admin/summary', headers=forged_role).status_code, 403)
        self.sql("UPDATE users SET role='faculty' WHERE id=?", (user['id'],))
        self.assertEqual(self.client.get('/api/faculty/ping', headers=forged_role).status_code, 200)
        self.assertEqual(self.client.get('/api/admin/summary', headers=forged_role).status_code, 403)

    def test_owner_and_role_matrix_cannot_mutate_other_session(self):
        sid = self.saved()
        before = dict(models.get_session(sid)), dict(models.get_result(sid))
        for step in ('look', 'speak', 'trust', 'certificate'):
            for headers, status in (({}, 401), (self.auth('sriram'), 403), (self.auth('vaibhav'), 403)):
                response = self.client.post(f'/api/session/{sid}/{step}', headers=headers, json={})
                self.assertEqual(response.status_code, status)
                self.assertNotIn('evidence', response.get_json())
        self.assertEqual(self.client.post(f'/api/session/{sid}/reopen', headers=self.headers).status_code, 403)
        self.assertEqual(self.client.post(f'/api/faculty/sessions/{sid}/override', headers=self.headers,
                                          json={'label': 'SAFE'}).status_code, 403)
        self.assertEqual((dict(models.get_session(sid)), dict(models.get_result(sid))), before)

    def test_admin_only_repeated_revocation_preserves_snapshot_chain_rotation_and_reissue(self):
        sid = self.saved('legacy')
        self.post(sid, 'trust')
        cert = dict(issue_certificate(sid))
        url = f"/api/admin/certificates/{cert['cert_id']}/revoke"
        for username in ('avinash', 'sriram'):
            self.assertEqual(self.client.post(url, headers=self.auth(username)).status_code, 403)
        for _ in range(2):
            response = self.client.post(url, headers=self.auth('vaibhav'))
            self.assertTrue(response.get_json()['hashUnchanged'])
        revoked = dict(models.get_certificate_for_session(sid))
        self.assertEqual(revoked, {**cert, 'revoked': 1})
        rotated = self.client.post(f'/api/session/{sid}/reopen', headers=self.auth('sriram')).get_json()
        self.assertTrue(rotated['newSession'])
        self.assertEqual(dict(issue_certificate(sid)), revoked)
        self.assertEqual(chain_status(cert['cert_id']), 'intact')
        self.assertEqual(self.client.post('/api/admin/certificates/missing/revoke', headers=self.auth('vaibhav')).status_code, 404)

    def test_real_setup_checks_leave_speak_and_budget_untouched(self):
        sid = self.start()
        from speak_identity import LOOK
        models.save_look(sid, LOOK)
        body = {**captures.capture(), 'wav': captures.audio()}
        # Bypass only the earlier suite's blanket availability fixture; use real local setup validation.
        with patch.object(verification, 'speech_availability', speech.availability), \
             patch.dict(self.app.config, SPEECH_MODEL_PATH=ROOT / '.runtime/not-present-model'):
            response = self.post(sid, 'speak', json=body)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()['reason'], 'speech_model_missing')
        self.assertEqual(models.get_session(sid)['speak_attempts'], 0)
        self.assertIsNone(models.get_result(sid)['voice_score'])
        with patch.dict(self.app.config, LANDMARK_PATH=ROOT / '.runtime/not-present-landmark'):
            reason, measured = landmarks.measure_clip([])
        self.assertEqual(reason, 'landmark_model_missing')
        self.assertEqual(measured, [])

if __name__ == '__main__':
    unittest.main(verbosity=2)
