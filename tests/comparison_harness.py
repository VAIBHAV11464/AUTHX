"""Task 22 harness rules and real-route integration with controlled scorers.

Native unmocked fixture inference is the separate task22-demo-reviewed run.
"""
import base64
import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from tools import comparison as harness
import uploads_quality as captures
import speech_fixture
import gate_fixture
import speak_identity as identity
from config import Config
from app.services import verification_profiles as profiles
from app.routes import verification


class HarnessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='authx-harness-test-')
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        (self.folder / 'frame.png').write_bytes(base64.b64decode(captures.image64()))
        (self.folder / 'audio.wav').write_bytes(base64.b64decode(captures.audio()))
        self.embedding = json.dumps([2.] + [0.] * 127)
        (self.folder / 'embedding.json').write_text(self.embedding)
        frames = [{'path': 'frame.png', 'tMs': index * 50} for index in range(60)]
        self.data = {'schemaVersion': harness.DATASET_VERSION, 'datasetId': 'controlled-test',
            'enrollments': {'same': {'method': 'existing_embedding', 'path': 'embedding.json'}},
            'cases': [{'id': 'same-input', 'fixtureCategory': 'synthetic', 'split': 'demo',
                       'timingProvenance': 'synthetic_schedule', 'expectedWord': 'amber', 'flashStartMs': 2000,
                       'enrollment': 'same', 'groundTruth': {'category': 'unknown', 'safeExpected': None, 'wordMatch': True},
                       'attempts': [{'lookFrames': frames, 'speakFrames': frames, 'wav': 'audio.wav', 'audioStartMs': 0}]}]}
        self.path = self.folder / 'manifest.json'
        self.write()
        self.measured = []

    def write(self):
        self.path.write_text(json.dumps(self.data))

    def patches(self, look_failure=None, speak_failures=0):
        spoken = {'legacy': 0, 'v2': 0}
        selected = {}
        for name in harness.PROFILES:
            def look(frames, flash, embedding, name=name):
                self.measured.append((name, 'look', flash, embedding, [(t, harness.digest(image.tobytes())) for t, image in frames]))
                return {'ok': False, 'reason': look_failure} if look_failure else {'ok': True, 'dipPercent': 60, **deepcopy(identity.LOOK)}
            def speak(frames, samples, rate, name=name, **options):
                self.measured.append((name, 'speak', rate, options, harness.digest(samples.tobytes()),
                                      [(t, harness.digest(image.tobytes())) for t, image in frames]))
                spoken[name] += 1
                if name == 'v2' and spoken[name] <= speak_failures:
                    return {'ok': False, 'reason': 'wrong_word', 'speech': {**speech_fixture.evidence('bridge'), 'wordVerified': False}}
                detail = gate_fixture.speak_detail(options.get('expected_word', 'amber')) if name == 'v2' else {}
                detail.update(rms=.05, speechRatio=.8, mfccVariation=40)
                return {'ok': True, 'acousticScore': 100, 'lipScore': 100, 'lipR': .8, 'voiceScore': 100,
                        'speakCosine': .8, 'detail': detail}
            selected[name] = profiles.VerificationProfile(name, look, speak, profiles.get_profile(name).fuse)
        return (patch.object(profiles, '_PROFILES', selected),
                patch.object(verification, 'models_ready', return_value=True),
                patch.object(verification, 'speech_availability', return_value={'ok': True}))

    def run_controlled(self, **kwargs):
        a, b, c = self.patches()
        with a, b, c:
            return harness.run_dataset(self.path, **kwargs)

    def test_same_original_media_enrollment_word_flash_and_pinned_profiles(self):
        report = self.run_controlled()
        self.assertEqual(len(report['results']), 2)
        legacy, v2 = report['results']
        self.assertEqual(legacy['inputSha256'], v2['inputSha256'])
        looks = [r for r in self.measured if r[1] == 'look']
        self.assertEqual(looks[0][2:], looks[1][2:])
        self.assertEqual(looks[0][3], self.embedding)
        speaks = [r for r in self.measured if r[1] == 'speak']
        self.assertEqual(speaks[0][2], speaks[1][2])
        self.assertEqual(speaks[0][4:], speaks[1][4:])
        self.assertEqual(speaks[1][3]['expected_word'], 'amber')
        self.assertEqual(speaks[1][3]['embedding'], self.embedding)
        self.assertTrue(all(r['completed'] and r['acceptedSafe'] for r in report['results']))
        self.assertTrue(v2['safeEligible'])
        self.assertIsNone(legacy['safeEligible'])
        self.assertEqual(legacy['wordAttempts'], [])

    def test_incomplete_flow_cannot_be_completed_by_component_diagnostics(self):
        a, b, c = self.patches(look_failure='no_blink')
        with a, b, c, patch('app.services.speech.verify_word', return_value={'ok': True, 'speech': speech_fixture.evidence()}):
            report = harness.run_dataset(self.path, probes=True)
        for row in report['results']:
            self.assertFalse(row['completed'])
            self.assertFalse(row['acceptedSafe'])
            self.assertIsNone(row['machineRiskLabel'])
            self.assertEqual(row['failureReason'], 'no_blink')
            self.assertEqual(row['wordAttempts'], [])
            self.assertEqual(len(row['diagnostics']), 2)
            self.assertTrue(all(d['includedInAcceptance'] is False for d in row['diagnostics']))
        self.assertEqual(report['aggregate']['v2']['wordVerified']['denominator'], 0)

    def test_unknown_zero_denominators_and_known_negative_safe_are_distinct(self):
        report = self.run_controlled()
        metrics = report['aggregate']['v2']
        self.assertIsNone(metrics['incorrectSafe']['rate'])
        self.assertEqual(metrics['unknownSafeGroundTruth'], 1)
        rows = deepcopy(report['results'])
        for row in rows:
            row['groundTruth']['safeExpected'] = False
            row['groundTruth']['category'] = 'wrong_person'
        metrics = harness.aggregate(rows)['v2']
        self.assertEqual(metrics['incorrectSafe']['rate'], 1.)
        self.assertEqual(metrics['knownNegativeCompleted'], 1)
        rows[1]['completed'] = rows[1]['acceptedSafe'] = False
        self.assertEqual(harness.aggregate(rows)['v2']['incorrectSafe']['numerator'], 1)
        self.assertIsNone(harness.aggregate([])['legacy']['safeAcceptance']['rate'])
        self.assertEqual(harness.timing([])['n'], 0)
        self.assertIsNone(harness.timing([])['p95Seconds'])

    def test_retry_submission_counts_four_budget_and_saved_look_reuse(self):
        self.data['cases'][0]['attempts'] *= 2
        self.write()
        a, b, c = self.patches(speak_failures=1)
        with a, b, c:
            report = harness.run_dataset(self.path)
        row = next(r for r in report['results'] if r['profile'] == 'v2')
        self.assertTrue(row['completed'])
        self.assertEqual(row['speakSubmissionsSpent'], 2)
        self.assertEqual([s['stage'] for s in row['stages']].count('look'), 1)
        self.assertEqual(len(row['wordAttempts']), 2)
        self.assertTrue(row['retryRequested'])
        self.assertEqual(report['aggregate']['v2']['retrySubmissionRate']['denominator'], 3)
        self.assertEqual(report['aggregate']['v2']['retrySubmissionRate']['numerator'], 1)
        self.data['cases'][0]['attempts'] *= 3
        self.write()
        a, b, c = self.patches(speak_failures=10)
        with a, b, c:
            exhausted = harness.run_dataset(self.path)
        row = next(r for r in exhausted['results'] if r['profile'] == 'v2')
        self.assertEqual(row['speakSubmissionsSpent'], 4)
        self.assertEqual(row['failureReason'], 'speak_attempts_exhausted')
        self.assertEqual(row['stages'][-1]['attemptReason'], 'wrong_word')
        self.assertEqual([s['stage'] for s in row['stages']].count('speak'), 4)
        self.assertFalse(row['completed'])

    def test_bad_timestamps_are_rejected_by_route_without_harness_repair(self):
        self.data['cases'][0]['attempts'][0]['lookFrames'][10]['tMs'] = 450
        self.write()
        report = self.run_controlled()
        v2 = next(r for r in report['results'] if r['profile'] == 'v2')
        self.assertEqual(v2['failureReason'], 'bad_timestamps')
        self.assertFalse(v2['completed'])
        self.assertEqual(v2['speakSubmissionsSpent'], 0)
        self.assertTrue(next(r for r in report['results'] if r['profile'] == 'legacy')['completed'])

    def test_actual_timers_stage_scope_and_percentile_method(self):
        report = self.run_controlled()
        for row in report['results']:
            self.assertGreater(row['processingSeconds'], 0)
            self.assertGreaterEqual(row['processingSeconds'], sum(s['seconds'] for s in row['stages']))
            self.assertTrue(all(s['seconds'] >= 0 for s in row['stages']))
        metric = harness.timing(list(range(1, 21)))
        self.assertEqual(metric['p95Seconds'], 19)
        self.assertEqual(metric['medianSeconds'], 10.5)
        self.assertEqual(metric['percentileMethod'], 'nearest-rank')

    def test_repeated_runs_preserve_policy_outcomes_original_db_and_config(self):
        database = Config.DATABASE_PATH
        default = Config.VERIFICATION_PROFILE
        before = harness.original_inventory()
        report = self.run_controlled(repetitions=2)
        for profile in harness.PROFILES:
            rows = [r for r in report['results'] if r['profile'] == profile]
            self.assertEqual([r['acceptedSafe'] for r in rows], [True, True])
            self.assertEqual(rows[0]['machineRiskLabel'], rows[1]['machineRiskLabel'])
            self.assertEqual(rows[0]['inputSha256'], rows[1]['inputSha256'])
            self.assertEqual(report['aggregate'][profile]['uniqueCases'], 1)
        self.assertEqual(harness.original_inventory(), before)
        self.assertEqual(Config.DATABASE_PATH, database)
        self.assertEqual(Config.VERIFICATION_PROFILE, default)
        self.assertTrue(report['preservation']['allOriginalRowsUnchanged'])

    def test_output_allowlist_no_recordings_embeddings_credentials_or_dataset_paths(self):
        self.data['cases'][0]['password'] = 'do-not-export-secret-marker'
        self.data['cases'][0]['groundTruth']['otp'] = 'do-not-export-otp-marker'
        self.write()
        report = self.run_controlled()
        output = self.folder / 'report'
        harness.write_report(report, output)
        text = '\n'.join(p.read_text(encoding='utf-8') for p in output.iterdir())
        for forbidden in (self.embedding, str(self.folder), 'do-not-export-secret-marker', 'do-not-export-otp-marker',
                          base64.b64encode((self.folder / 'frame.png').read_bytes()).decode()):
            self.assertNotIn(forbidden, text)
        self.assertNotIn('JWT_SECRET', text)
        self.assertNotIn('SMTP_PASSWORD', text)
        self.assertTrue((output / 'results.csv').is_file())
        self.assertTrue((output / 'diagnostics.csv').is_file())
        self.assertTrue((output / 'aggregate.csv').is_file())
        self.assertEqual(harness.csv_safe('=1+1'), "'=1+1")
        with self.assertRaises(FileExistsError):
            harness.write_report(report, output)

    def test_missing_assets_versions_duplicate_ids_and_unrecorded_consent_fail_clearly(self):
        original = deepcopy(self.data)
        for mutate in (lambda d: d.update(schemaVersion='unknown'),
                       lambda d: d['cases'].append(deepcopy(d['cases'][0])),
                       lambda d: d['cases'][0].update(fixtureCategory='consented'),
                       lambda d: d['enrollments']['same'].update(path='../outside.json')):
            self.data = deepcopy(original)
            mutate(self.data)
            self.write()
            with self.assertRaises(ValueError):
                harness.load_dataset(self.path)

    def test_invalid_common_enrollment_has_no_invented_processing_time_or_result(self):
        (self.folder / 'embedding.json').write_text('[]')
        report = harness.run_dataset(self.path)
        for row in report['results']:
            self.assertEqual(row['failureStage'], 'enrollment')
            self.assertFalse(row['completed'])
            self.assertIsNone(row['processingSeconds'])
        self.assertEqual(report['aggregate']['v2']['fullFlowTiming']['n'], 0)

    def test_global_changes_after_start_cannot_change_pinned_word_or_profile(self):
        from flask import current_app
        from flask.testing import FlaskClient
        original = FlaskClient.post
        def changing(client, url, *args, **kwargs):
            response = original(client, url, *args, **kwargs)
            if url == '/api/session/start':
                current_app.config.update(VERIFICATION_PROFILE='legacy', CHALLENGE_WORDS=('bridge',))
            return response
        a, b, c = self.patches()
        with a, b, c, patch.object(FlaskClient, 'post', changing):
            report = harness.run_dataset(self.path)
        self.assertTrue(all(r['acceptedSafe'] for r in report['results']))
        measured = next(r for r in self.measured if r[0] == 'v2' and r[1] == 'speak')
        self.assertEqual(measured[3]['expected_word'], 'amber')

    def test_actual_body_limit_rejection_is_paired_and_not_repaired(self):
        (self.folder / 'frame.png').write_bytes((self.folder / 'frame.png').read_bytes() + b'\0' * 150000)
        report = self.run_controlled()
        for row in report['results']:
            self.assertEqual(row['failureReason'], 'upload_too_large')
            self.assertEqual(row['stages'][-1]['httpStatus'], 413)
            self.assertFalse(row['completed'])
        self.assertEqual(self.measured, [])

    def test_unexpected_route_error_has_no_secret_message_and_is_not_a_capture_retry(self):
        a, b, c = self.patches()
        from flask.testing import FlaskClient
        original = FlaskClient.post
        def failing(client, url, *args, **kwargs):
            if url.endswith('/look'):
                raise RuntimeError('do-not-export-error-secret')
            return original(client, url, *args, **kwargs)
        with a, b, c, patch.object(FlaskClient, 'post', failing):
            report = harness.run_dataset(self.path)
        self.assertNotIn('do-not-export-error-secret', json.dumps(report))
        for row in report['results']:
            self.assertEqual(row['failureReason'], 'route_exception')
            self.assertFalse(row['retryRequested'])
            self.assertFalse(row['completed'])

    def test_upload_importer_preserves_original_bytes_timestamps_and_audio_offset(self):
        from tools.comparison_import import import_uploads
        look = captures.capture()
        look['frames'][2]['tMs'] += .125
        speak = {**captures.capture(), 'wav': captures.audio(), 'audioStartMs': 12.75}
        for name, value in (('look-upload.json', look), ('speak-upload.json', speak), ('metadata.json', self.data['cases'][0])):
            (self.folder / name).write_text(json.dumps(value))
        path = import_uploads(self.folder / 'look-upload.json', self.folder / 'speak-upload.json', self.folder / 'frame.png',
                              self.folder / 'metadata.json', self.folder / 'imported')
        case = harness.load_dataset(path)['cases'][0]
        self.assertEqual(case.attempts[0]['look'], look)
        self.assertEqual(case.attempts[0]['speak'], speak)
        self.assertEqual((path.parent / 'enrollment.img').read_bytes(), (self.folder / 'frame.png').read_bytes())


if __name__ == '__main__':
    unittest.main(verbosity=2)
