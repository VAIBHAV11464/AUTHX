"""Task 19 isolated lifecycle, delayed-worker, audit and history preservation checks."""
import contextlib
import hashlib
import json
import sqlite3
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import evidence_summaries as summary_tests
from app import create_app
from app import models
from app.models import get_session, get_result, save_look, save_voice, save_trust
from app.services import session_lifecycle as life, verification_profiles as profiles
from app.services.certificate import issue_certificate, chain_status
from app.services.evidence_summary import session_fields
from app.routes import verification
from speak_identity import LOOK
from verification_profiles import SPEAK
from uploads_quality import capture, audio


class LifecycleTests(unittest.TestCase):
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

    def at(self, session_id, seconds):
        started = datetime.fromisoformat(get_session(session_id)['started_at']).timestamp()
        return patch.object(life.time, 'time', return_value=started + seconds)

    def reopen(self, session_id, username='sriram'):
        return self.client.post(f'/api/session/{session_id}/reopen', headers=self.auth(username))

    def override(self, session_id, label='SAFE', username='sriram', **extra):
        return self.client.post(f'/api/faculty/sessions/{session_id}/override',
                                headers=self.auth(username), json={'label': label, **extra})

    def test_exact_600_second_boundary_for_both_profiles_and_all_unfinished_stages(self):
        for profile in ('legacy', 'v2'):
            for stage in ('empty', 'look', 'voice'):
                sid = self.saved(profile) if stage == 'voice' else self.start()
                if stage != 'voice':
                    self.sql('UPDATE sessions SET verification_profile = ? WHERE id = ?', (profile, sid))
                if stage == 'look':
                    save_look(sid, LOOK)
                self.assertFalse(life.expired(get_session(sid), now=datetime.fromisoformat(get_session(sid)['started_at']).timestamp() + 599.999))
                with self.at(sid, 600), patch.object(verification, 'models_ready', side_effect=AssertionError('expired inference')):
                    for step in ('look', 'speak', 'trust', 'certificate'):
                        response = self.post(sid, step, json={})
                        self.assertEqual(response.status_code, 409, (profile, stage, step, response.get_json()))
                        self.assertEqual(response.get_json()['reason'], 'session_expired')
                        self.assertFalse(response.get_json()['retryable'])
                        self.assertTrue(response.get_json()['freshSessionRequired'])
                    self.assertEqual(self.reopen(sid).get_json()['reason'], 'session_expired')
                    self.assertFalse(session_fields(get_session(sid), get_result(sid))['retryable'])

    def test_auth_and_roles_precede_expiry_and_private_evidence(self):
        sid = self.start()
        with self.at(sid, 601):
            for step in ('look', 'speak', 'trust', 'certificate'):
                for headers, status in (({}, 401), (self.auth('sriram'), 403)):
                    response = self.client.post(f'/api/session/{sid}/{step}', headers=headers)
                    self.assertEqual(response.status_code, status)
                    self.assertNotIn('evidence', response.get_json())
            self.assertEqual(self.reopen(sid, 'avinash').status_code, 403)
            self.assertEqual(self.override(sid, username='avinash').status_code, 403)

    def test_direct_late_saves_and_issue_cannot_resurrect_open_attempt(self):
        empty = self.start()
        sid = self.saved()
        with self.at(empty, 600), self.assertRaisesRegex(life.LifecycleError, 'session_expired'):
            save_look(empty, LOOK)
        with self.at(sid, 600):
            with self.assertRaisesRegex(life.LifecycleError, 'session_expired'):
                save_trust(sid, 100, 'SAFE')
            with self.assertRaisesRegex(life.LifecycleError, 'session_expired'):
                issue_certificate(sid)
        self.assertIsNone(get_result(empty))
        self.assertIsNone(get_session(sid)['trust_score'])

    def test_delayed_look_crosses_deadline_and_cannot_save(self):
        sid = self.start()
        started = datetime.fromisoformat(get_session(sid)['started_at']).timestamp()
        clock = {'now': started + 599}
        def score(*args):
            clock['now'] = started + 600
            return {'ok': True, **LOOK}
        with patch.object(life.time, 'time', side_effect=lambda: clock['now']), \
                patch.object(verification, 'models_ready', return_value=True), \
                patch.object(profiles, '_PROFILES', {'v2': profiles.VerificationProfile('v2', score, None, None)}):
            response = self.post(sid, 'look', json=capture())
        self.assertEqual(response.get_json()['reason'], 'session_expired')
        self.assertIsNone(get_result(sid))

    def test_reopen_generation_blocks_old_look_legacy_voice_and_trust_workers(self):
        sid = self.start()
        generation = get_session(sid)['attempt_generation']
        self.assertEqual(self.reopen(sid).status_code, 200)
        with self.assertRaisesRegex(life.LifecycleError, 'session_attempt_superseded'):
            save_look(sid, LOOK, generation=generation)
        save_look(sid, LOOK)
        row_id = get_result(sid)['id']
        self.reopen(sid)
        save_look(sid, LOOK)
        with self.assertRaisesRegex(life.LifecycleError, 'session_attempt_superseded'):
            save_voice(sid, SPEAK, result_id=row_id)
        save_voice(sid, SPEAK)
        with self.assertRaisesRegex(life.LifecycleError, 'session_attempt_superseded'):
            save_trust(sid, 100, 'SAFE', result_id=row_id)
        self.assertIsNone(get_session(sid)['trust_score'])

    def test_expiring_reserved_speak_releases_own_lease_without_saving_or_refund(self):
        sid = self.start()
        save_look(sid, LOOK)
        with self.at(sid, 599):
            reservation = models.reserve_speak(sid, self.user['id'])
        self.assertTrue(reservation['ok'])
        with self.at(sid, 600):
            outcome = models.finish_speak(sid, reservation, SPEAK)
            self.assertEqual(outcome['reason'], 'session_expired')
            self.assertEqual(outcome['attemptsUsed'], 1)
            self.assertEqual(models.reserve_speak(sid, self.user['id'])['reason'], 'session_expired')
        self.assertIsNone(get_result(sid)['voice_score'])
        self.assertIsNone(get_session(sid)['speak_token'])

    def test_retry_budget_lease_restart_and_uncertified_reopen_keep_deadline(self):
        sid = self.start()
        save_look(sid, LOOK)
        before = get_session(sid)
        reservation = models.reserve_speak(sid, self.user['id'])
        self.assertEqual(self.reopen(sid).get_json()['reason'], 'speak_in_progress')
        models.finish_speak(sid, reservation, {'ok': False, 'reason': 'no_face', 'detail': 'failure'})
        self.assertEqual(self.reopen(sid).status_code, 200)
        self.assertEqual(get_session(sid)['speak_attempts'], 1)
        self.assertEqual(get_session(sid)['started_at'], before['started_at'])
        self.app.config['VERIFICATION_PROFILE'] = 'legacy'
        self.sql('UPDATE sessions SET speak_attempts = 4 WHERE id = ?', (sid,))
        create_app()  # Same isolated DB; persisted fields survive migration/restart.
        self.assertEqual(self.reopen(sid).get_json()['reason'], 'speak_attempts_exhausted')
        self.assertEqual(get_session(sid)['verification_profile'], 'v2')

    def test_superseded_reservation_cannot_refund_newer_worker_even_at_expiry(self):
        sid = self.start()
        save_look(sid, LOOK)
        with self.at(sid, 100):
            first = models.reserve_speak(sid, self.user['id'])
        with self.at(sid, 221):
            second = models.reserve_speak(sid, self.user['id'])
        with self.at(sid, 600):
            outcome = models.finish_speak(sid, first, {'ok': False, 'reason': 'verification_unavailable'}, setup_failure=True)
        self.assertEqual(outcome['reason'], 'speak_attempt_superseded')
        self.assertEqual(get_session(sid)['speak_token'], second['token'])
        self.assertEqual(get_session(sid)['speak_attempts'], 2)

    def test_scored_history_does_not_expire_or_recalculate_but_old_reopen_is_denied(self):
        for profile in ('legacy', 'v2'):
            sid = self.saved(profile)
            trusted = self.post(sid, 'trust').get_json()
            before = dict(get_session(sid)), dict(get_result(sid))
            with self.at(sid, 10000):
                self.app.config['SAFE_MIN'] = 101
                self.assertEqual(self.post(sid, 'trust').get_json()['trustScore'], trusted['trustScore'])
                self.assertEqual((dict(get_session(sid)), dict(get_result(sid))), before)
                self.assertEqual(self.reopen(sid).get_json()['reason'], 'session_expired')
                self.assertIsNotNone(issue_certificate(sid))
            self.app.config['SAFE_MIN'] = 75

    def test_certified_rotation_preserves_every_old_field_and_pinned_profile(self):
        for profile in ('legacy', 'v2'):
            sid = self.saved(profile)
            self.post(sid, 'trust')
            cert = dict(issue_certificate(sid))
            before = dict(get_session(sid)), dict(get_result(sid))
            self.app.config.update(VERIFICATION_PROFILE='legacy' if profile == 'v2' else 'v2', CHALLENGE_WORDS=('citrus',), FLASH_START_MIN_MS=2001, FLASH_START_MAX_MS=2001)
            with self.at(sid, 10000):
                response = self.reopen(sid).get_json()
            new = get_session(response['sessionId'])
            self.assertTrue(response['newSession'])
            self.assertNotEqual(new['id'], sid)
            self.assertEqual(new['verification_profile'], profile)
            self.assertEqual(new['challenge_word'], 'citrus')
            self.assertEqual(new['flash_start_ms'], 2001)
            self.assertEqual(new['speak_attempts'], 0)
            self.assertEqual(new['status'], 'open')
            self.assertEqual((dict(get_session(sid)), dict(get_result(sid))), before)
            self.assertEqual(dict(issue_certificate(sid)), cert)
            self.assertEqual(chain_status(cert['cert_id']), 'intact')
            self.assertIsNone(get_result(new['id']))
            with self.assertRaisesRegex(life.LifecycleError, 'session_certified'):
                save_trust(sid, 1, 'DEEPFAKE')

    def test_concurrent_certified_reopen_converges_on_one_successor(self):
        sid = self.saved()
        self.post(sid, 'trust')
        issue_certificate(sid)
        def reopen(_):
            with self.app.test_client() as client:
                return client.post(f'/api/session/{sid}/reopen', headers=self.auth('sriram')).get_json()
        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(pool.map(reopen, range(6)))
        self.assertEqual(len({row['sessionId'] for row in rows}), 1)
        self.assertEqual(len(self.sql('SELECT * FROM sessions')), 2)

    def test_certificate_locks_scoring_even_when_historical_results_are_absent(self):
        sid = self.saved()
        self.post(sid, 'trust')
        frozen = dict(issue_certificate(sid))
        self.sql('DELETE FROM results WHERE session_id = ?', (sid,))
        with patch.object(verification, 'models_ready', side_effect=AssertionError('certified measurement')):
            self.assertEqual(self.post(sid, 'look', json={}).get_json()['reason'], 'look_locked')
            self.assertEqual(self.post(sid, 'speak', json={}).get_json()['reason'], 'speak_locked')
        self.assertEqual(dict(issue_certificate(sid)), frozen)

    def test_override_actor_audit_machine_independence_and_frozen_certificate(self):
        for profile in ('legacy', 'v2'):
            sid = self.saved(profile)
            self.post(sid, 'trust')
            machine = dict(get_result(sid))
            self.assertEqual(self.override(sid, 'DEEPFAKE', actorId=self.user['id'], createdAt='fake').status_code, 200)
            row = self.sql('SELECT * FROM faculty_overrides WHERE session_id = ?', (sid,))[0]
            self.assertEqual(row['actor_id'], models.get_user_by_username('sriram')['id'])
            self.assertEqual(row['actor_role'], 'faculty')
            self.assertEqual(row['previous_label'], 'SAFE')
            self.assertEqual(row['machine_risk_label'], 'SAFE')
            self.assertNotEqual(row['created_at'], 'fake')
            self.assertEqual(dict(get_result(sid)), machine)
            self.assertEqual(self.post(sid, 'trust').get_json()['riskLabel'], 'DEEPFAKE')
            cert = dict(issue_certificate(sid))
            if profile == 'v2':
                self.assertEqual(json.loads(cert['score_json'])['evidence']['facultyOverride']['selectedLabel'], 'DEEPFAKE')
            self.override(sid, 'SAFE', 'vaibhav')
            self.assertEqual(dict(issue_certificate(sid)), cert)
            self.assertEqual(dict(get_result(sid)), machine)
            detail = self.client.get(f'/api/faculty/sessions/{sid}', headers=self.auth('sriram')).get_json()
            self.assertEqual(len(detail['overrides']), 2)
            self.assertEqual(detail['evidence']['machineDecision']['riskLabel'], 'SAFE')
            self.assertEqual(detail['evidence']['facultyOverride']['actorRole'], 'admin')

    def test_override_rollback_and_old_label_no_fabricated_history(self):
        sid = self.start()
        self.sql("UPDATE sessions SET risk_label = 'SAFE' WHERE id = ?", (sid,))
        self.assertIsNone(session_fields(get_session(sid), None)['evidence']['facultyOverride'])
        self.sql("CREATE TRIGGER reject_override BEFORE UPDATE OF risk_label ON sessions BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            models.set_risk_label(sid, 'DEEPFAKE', actor_id=models.get_user_by_username('sriram')['id'])
        self.assertEqual(self.sql('SELECT * FROM faculty_overrides'), [])
        self.assertEqual(get_session(sid)['risk_label'], 'SAFE')
        self.sql('DROP TRIGGER reject_override')
        self.assertEqual(self.override(sid, 'bad').status_code, 400)
        with self.assertRaisesRegex(life.LifecycleError, 'forbidden'):
            models.set_risk_label(sid, 'SAFE', actor_id=self.user['id'])

    def test_reopen_keeps_audit_history_without_applying_previous_generation(self):
        sid = self.saved()
        self.post(sid, 'trust')
        self.override(sid, 'DEEPFAKE')
        self.reopen(sid)
        self.assertIsNone(session_fields(get_session(sid), None)['evidence']['facultyOverride'])
        self.assertEqual(len(self.sql('SELECT * FROM faculty_overrides WHERE session_id = ?', (sid,))), 1)

    def test_additive_migration_of_preserved_real_database_copy(self):
        source_path = ROOT / 'authx.db'
        before_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        target_path = Path(models.Config.DATABASE_PATH).with_name('historical-copy.db')
        with contextlib.closing(sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)) as source, \
                contextlib.closing(sqlite3.connect(target_path)) as target:
            source.backup(target)
        def snapshot():
            with contextlib.closing(sqlite3.connect(target_path)) as conn:
                conn.row_factory = sqlite3.Row
                return {name: [dict(row) for row in conn.execute(f'SELECT * FROM {name} ORDER BY id')]
                        for name in ('users', 'sessions', 'results', 'certificates', 'otps')}
        before = snapshot()
        models.init_db(target_path)
        after = snapshot()
        for table, rows in before.items():
            self.assertEqual(len(after[table]), len(rows))
            for old, new in zip(rows, after[table]):
                self.assertEqual({key: new[key] for key in old}, old)
        models.init_db(target_path)
        self.assertEqual(snapshot(), after)
        self.assertEqual(hashlib.sha256(source_path.read_bytes()).hexdigest(), before_hash)
        with contextlib.closing(sqlite3.connect(target_path)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM faculty_overrides').fetchone()[0], 0)
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_malformed_or_non_utc_start_fails_closed_without_mutating_history(self):
        for value in ('fixture', '2026-09-28T00:00:00', None, '2026-09-28T00:00:00+05:30'):
            self.assertTrue(life.expired({'status': 'open', 'started_at': value}))
            self.assertFalse(life.expired({'status': 'certified', 'started_at': value}))


if __name__ == '__main__':
    unittest.main(verbosity=2)
