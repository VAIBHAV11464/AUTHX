"""Task 20 single-transaction chain append, idempotence, collisions and rollback."""
import contextlib
import json
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import evidence_summaries as summary_tests
from app import models
from app.models import get_session, get_result
from app.services import certificate as cert
from app.services.session_lifecycle import LifecycleError
from app.services import session_lifecycle as life
from app.routes import verification


class AtomicTests(unittest.TestCase):
    setUp = summary_tests.SummaryTests.setUp
    start = summary_tests.SummaryTests.start
    saved = summary_tests.SummaryTests.saved
    auth = summary_tests.SummaryTests.auth
    post = summary_tests.SummaryTests.post

    def sql(self, query, params=()):
        with contextlib.closing(models.connect()) as conn:
            rows = conn.execute(query, params).fetchall()
            conn.commit()
            return rows

    def ready(self, profile='v2'):
        sid = self.saved(profile)
        self.assertEqual(self.post(sid, 'trust').status_code, 200)
        return sid

    def issue(self, sid):
        with self.app.app_context():
            row = cert.issue_certificate(sid)
            return dict(row) if row else None

    def assert_chain(self):
        rows = models.list_certificates()
        expected = cert.GENESIS
        for row in rows:
            self.assertEqual(row['prev_hash'], expected)
            score = json.loads(row['score_json'])['trustScore']
            self.assertEqual(row['block_hash'], cert.block_hash(row['prev_hash'], row['session_id'], score,
                                                               row['created_at'], row['score_json']))
            self.assertEqual(cert.chain_status(row['cert_id']), 'intact')
            expected = row['block_hash']

    def test_one_connection_transaction_includes_every_issuance_read_and_write(self):
        sid = self.ready()
        real_connect = models.connect
        statements = []
        connections = []
        def connect():
            conn = real_connect()
            connections.append(conn)
            conn.set_trace_callback(statements.append)
            return conn
        with patch.object(cert, 'connect', side_effect=connect), \
                patch.object(models, 'connect', side_effect=AssertionError('nested model connection')):
            issued = cert.issue_certificate(sid)
        self.assertEqual(len(connections), 1)
        self.assertEqual(statements[0], 'BEGIN IMMEDIATE')
        self.assertEqual(statements[-1], 'COMMIT')
        for table in ('sessions', 'results', 'certificates', 'faculty_overrides'):
            self.assertTrue(any('SELECT' in sql and table in sql for sql in statements), table)
        self.assertTrue(any('INSERT INTO certificates' in sql for sql in statements))
        self.assertTrue(any("status = 'certified'" in sql for sql in statements))
        self.assertIsNotNone(issued)
        self.assert_chain()

    def test_same_session_concurrent_api_requests_return_one_identical_certificate(self):
        for profile in ('legacy', 'v2'):
            sid = self.ready(profile)
            barrier = threading.Barrier(8)
            def issue(_):
                barrier.wait(timeout=10)
                with self.app.test_client() as client:
                    response = client.post(f'/api/session/{sid}/certificate', headers=self.headers)
                    self.assertEqual(response.status_code, 200)
                    return response.get_json()
            with ThreadPoolExecutor(max_workers=8) as pool:
                issued = list(pool.map(issue, range(8)))
            self.assertTrue(all(row == issued[0] for row in issued))
            self.assertEqual(len(self.sql('SELECT * FROM certificates WHERE session_id = ?', (sid,))), 1)
        self.assert_chain()

    def test_different_sessions_append_single_chain_in_sqlite_insertion_order(self):
        head = self.issue(self.ready('legacy'))
        sessions = [self.ready('legacy' if index % 2 else 'v2') for index in range(10)]
        barrier = threading.Barrier(10)
        def issue(sid):
            barrier.wait(timeout=10)
            return self.issue(sid)
        with ThreadPoolExecutor(max_workers=10) as pool:
            rows = list(pool.map(issue, sessions))
        self.assertEqual(len({row['cert_id'] for row in rows}), 10)
        self.assertEqual(dict(models.get_certificate(head['cert_id'])), head)
        self.assertEqual(len(models.list_certificates()), 11)
        self.assert_chain()

    def test_existing_revoked_cert_returns_unchanged_after_reopen_mutation_and_config_change(self):
        sid = self.ready()
        issued = self.issue(sid)
        self.client.post(f'/api/session/{sid}/reopen', headers=self.auth('sriram'))
        cert.revoke(issued['cert_id'])
        frozen = dict(models.get_certificate(issued['cert_id']))
        self.sql("UPDATE sessions SET status = 'open', started_at = 'invalid', trust_score = NULL, risk_label = 'DEEPFAKE', challenge_word = 'changed' WHERE id = ?", (sid,))
        self.sql('DELETE FROM results WHERE session_id = ?', (sid,))
        self.app.config.update(VERIFICATION_PROFILE='legacy', COSINE_MATCH=.99, V2_WORD_MIN_CONFIDENCE=.99)
        self.assertEqual(self.issue(sid), frozen)
        response = self.post(sid, 'certificate')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['certId'], issued['cert_id'])
        self.assertEqual(response.get_json()['evidence'], json.loads(frozen['score_json'])['evidence'])
        self.assertEqual(self.issue(sid), frozen)
        self.assert_chain()

    def test_new_v2_eligibility_checked_inside_transaction_and_direct_calls_fail_closed(self):
        for field, reason in (('speech', 'word_required'), ('machineDecision', 'evidence_required')):
            sid = self.ready()
            detail = json.loads(get_result(sid)['detail_json'])
            del detail[field]
            self.sql('UPDATE results SET detail_json = ? WHERE session_id = ?', (json.dumps(detail), sid))
            self.assertIsNone(self.issue(sid))
            response = self.post(sid, 'certificate')
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.get_json()['reason'], reason)
            self.assertEqual(get_session(sid)['status'], 'scored')
            self.assertIsNone(models.get_certificate_for_session(sid))

    def test_stale_route_session_after_uncertified_reopen_cannot_issue(self):
        sid = self.ready()
        stale = get_session(sid)
        models.clear_attempt(sid)
        with patch.object(verification, 'get_session', return_value=stale):
            response = self.post(sid, 'certificate')
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(models.get_certificate_for_session(sid))
        self.assertEqual(get_session(sid)['status'], 'open')

    def test_waiting_issuer_rechecks_expiry_after_obtaining_sqlite_lock(self):
        sid = self.saved()
        started = datetime.fromisoformat(get_session(sid)['started_at']).timestamp()
        clock = {'now': started + 599}
        entered = threading.Event()
        real_connect = cert.connect
        def connect():
            conn = real_connect()
            entered.set()
            return conn
        with contextlib.closing(models.connect()) as lock:
            lock.execute('BEGIN IMMEDIATE')
            with patch.object(cert, 'connect', side_effect=connect), \
                    patch.object(life.time, 'time', side_effect=lambda: clock['now']), ThreadPoolExecutor(max_workers=1) as pool:
                request = pool.submit(self.issue, sid)
                try:
                    self.assertTrue(entered.wait(5))
                    clock['now'] = started + 600
                finally:
                    lock.rollback()
                with self.assertRaisesRegex(LifecycleError, 'session_expired'):
                    request.result(timeout=10)
        self.assertIsNone(models.get_certificate_for_session(sid))
        self.assertEqual(get_session(sid)['status'], 'open')

    def test_failure_after_insert_and_status_update_rolls_back_everything(self):
        head = self.issue(self.ready('legacy'))
        sid = self.ready()
        before = dict(get_session(sid))
        real_insert = cert.insert_certificate
        def failing(*args, **kwargs):
            real_insert(*args, **kwargs)
            raise RuntimeError('injected after insertion and certification')
        with patch.object(cert, 'insert_certificate', side_effect=failing), self.assertRaisesRegex(RuntimeError, 'injected'):
            cert.issue_certificate(sid)
        self.assertIsNone(models.get_certificate_for_session(sid))
        self.assertEqual(dict(get_session(sid)), before)
        self.assertEqual(dict(models.get_certificate(head['cert_id'])), head)
        issued = self.issue(sid)
        self.assertEqual(issued['prev_hash'], head['block_hash'])
        self.assert_chain()

    def test_sqlite_failure_during_status_update_rolls_back_insert_and_releases_lock(self):
        sid = self.ready()
        before = dict(get_session(sid))
        self.sql("CREATE TRIGGER certification_failure BEFORE UPDATE OF status ON sessions WHEN NEW.status = 'certified' BEGIN SELECT RAISE(ABORT, 'fixture abort'); END")
        with self.assertRaisesRegex(__import__('sqlite3').IntegrityError, 'fixture abort'):
            cert.issue_certificate(sid)
        self.assertEqual(dict(get_session(sid)), before)
        self.assertIsNone(models.get_certificate_for_session(sid))
        self.sql('DROP TRIGGER certification_failure')
        self.assertIsNotNone(self.issue(sid))
        self.assert_chain()

    def test_id_collision_retries_use_same_lock_and_exhaustion_is_clean(self):
        with patch.object(cert.secrets, 'token_hex', return_value='existing'):
            head = self.issue(self.ready('legacy'))
        sid = self.ready()
        with patch.object(cert.secrets, 'token_hex', side_effect=['existing', 'existing', 'fresh']) as random:
            issued = self.issue(sid)
        self.assertEqual(random.call_count, 3)
        self.assertEqual(issued['cert_id'], self.app.config['CERT_PREFIX'] + 'fresh')
        next_sid = self.ready()
        before = dict(get_session(next_sid))
        with patch.object(cert.secrets, 'token_hex', return_value='existing'), self.assertRaisesRegex(RuntimeError, 'cert_id_collision'):
            cert.issue_certificate(next_sid)
        self.assertEqual(dict(get_session(next_sid)), before)
        self.assertIsNone(models.get_certificate_for_session(next_sid))
        self.assertEqual(dict(models.get_certificate(head['cert_id'])), head)
        self.assertIsNotNone(self.issue(next_sid))
        self.assert_chain()

    def test_override_waits_for_issuance_and_cannot_change_frozen_snapshot(self):
        sid = self.ready()
        entered, release, actor_started = threading.Event(), threading.Event(), threading.Event()
        original = cert._score_json
        def slow(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise RuntimeError('test timeout')
            return original(*args, **kwargs)
        actor_id = models.get_user_by_username('sriram')['id']
        def override():
            actor_started.set()
            return models.set_risk_label(sid, 'DEEPFAKE', actor_id=actor_id)
        with patch.object(cert, '_score_json', side_effect=slow), ThreadPoolExecutor(max_workers=2) as pool:
            issuance = pool.submit(self.issue, sid)
            try:
                self.assertTrue(entered.wait(5))
                change = pool.submit(override)
                self.assertTrue(actor_started.wait(5))
            finally:
                release.set()
            issued = issuance.result(timeout=10)
            self.assertTrue(change.result(timeout=10))
        self.assertEqual(json.loads(issued['score_json'])['riskLabel'], 'SAFE')
        self.assertIsNone(json.loads(issued['score_json'])['evidence']['facultyOverride'])
        self.assertEqual(get_session(sid)['risk_label'], 'DEEPFAKE')
        self.assertEqual(self.issue(sid), issued)
        self.assert_chain()

    def test_reopen_waits_for_issuance_and_rotates_without_destroying_result(self):
        sid = self.ready()
        before_result = dict(get_result(sid))
        entered, release = threading.Event(), threading.Event()
        original = cert._score_json
        def slow(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise RuntimeError('test timeout')
            return original(*args, **kwargs)
        def reopen():
            with self.app.test_client() as client:
                return client.post(f'/api/session/{sid}/reopen', headers=self.auth('sriram')).get_json()
        with patch.object(cert, '_score_json', side_effect=slow), ThreadPoolExecutor(max_workers=2) as pool:
            issuance = pool.submit(self.issue, sid)
            try:
                self.assertTrue(entered.wait(5))
                reopening = pool.submit(reopen)
            finally:
                release.set()
            issued = issuance.result(timeout=10)
            rotation = reopening.result(timeout=10)
        self.assertTrue(rotation['newSession'])
        self.assertNotEqual(rotation['sessionId'], sid)
        self.assertEqual(dict(get_result(sid)), before_result)
        self.assertEqual(self.issue(sid), issued)
        self.assertEqual(get_session(sid)['status'], 'certified')
        self.assert_chain()

    def test_snapshot_serialization_failure_preserves_chain_and_session(self):
        sid = self.ready()
        before = dict(get_session(sid))
        with patch.object(cert, '_score_json', side_effect=ValueError('snapshot failure')), self.assertRaisesRegex(ValueError, 'snapshot failure'):
            cert.issue_certificate(sid)
        self.assertEqual(dict(get_session(sid)), before)
        self.assertEqual(models.list_certificates(), [])
        self.assertIsNotNone(self.issue(sid))
        self.assert_chain()

    def test_broken_historical_chain_is_not_repaired_or_rehashed(self):
        head = self.issue(self.ready('legacy'))
        self.sql("UPDATE certificates SET prev_hash = 'historic-broken' WHERE cert_id = ?", (head['cert_id'],))
        old = dict(models.get_certificate(head['cert_id']))
        new = self.issue(self.ready())
        self.assertEqual(dict(models.get_certificate(head['cert_id'])), old)
        self.assertEqual(new['prev_hash'], old['block_hash'])
        self.assertEqual(cert.chain_status(head['cert_id']), 'broken')
        self.assertEqual(cert.chain_status(new['cert_id']), 'broken')


if __name__ == '__main__':
    unittest.main(verbosity=2)
