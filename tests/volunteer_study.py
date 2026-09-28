"""Study-integrity and real API collector tests with explicitly controlled fixtures.

Fake test documents/scorers exercise policy only. They are never volunteer evidence.
"""
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from config import Config
from tools import comparison as harness
from tools import comparison_import as importer
from tools import study_capture as collector
from tools import volunteer_study as study
import comparison_harness as fixtures
import uploads_quality as captures


def frames():
    return [{'tMs': index * 50, 'image': captures.image64()} for index in range(60)]


class StudyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='study-policy-test-', dir=ROOT / '.runtime')
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.study = study.study_template()
        self.study['studyId'] = 'controlled-study'
        self.study['protocol']['declaredBeforeCollection'] = True
        self.study['cameras'] = [{'id': 'cam1', 'description': 'CONTROLLED TEST CAMERA', 'deviceKeySha256': harness.digest(b'cam1')},
                                 {'id': 'cam2', 'description': 'CONTROLLED TEST CAMERA TWO', 'deviceKeySha256': harness.digest(b'cam2')}]
        self.study['referenceLaptop'] = {'id': 'controlled-test-runtime', 'specification': 'CONTROLLED TEST; not a benchmark',
                                        'confirmedThisMachine': True, 'runtimeFingerprintSha256': study.runtime_fingerprint()}
        for n, split in ((1, 'evaluation'), (2, 'evaluation'), (3, 'tuning')):
            sid = 's' + str(n)
            document = self.folder / (sid + '.txt')
            document.write_text('CONTROLLED TEST DOCUMENT, NOT HUMAN CONSENT')
            self.study['subjects'].append({'id': sid, 'split': split, 'identityKeySha256': harness.digest(sid.encode()),
                'consentDocument': document.name, 'consentSha256': harness.digest(document.read_bytes()),
                'consentRecordedAt': '2026-09-27T00:00:00+00:00', 'consentReviewed': True, 'withdrawn': False,
                'recordingPermitted': True, 'replayPermitted': True})
        self.study['plannedTrials'] = [{'id': 'trial1', 'subjectId': 's1', 'cameraId': 'cam1', 'lighting': 'normal',
                                       'category': 'genuine', 'split': 'evaluation', 'sourceSubjectIds': ['s1']}]
        self.path = self.folder / 'study.json'
        self.save()
        self.embedding = json.dumps([1.] + [0.] * 127)
        self.helper = fixtures.HarnessTests()
        self.helper.measured = []

    def save(self, value=None, path=None):
        (path or self.path).write_text(json.dumps(value or self.study), encoding='utf-8')

    def collect(self, *, speak_failures=0, look_failure=None, end=True, two_sessions=False):
        self.capture = self.folder / 'capture'
        protocol_freeze = self.folder / 'protocol-freeze.json'
        study.freeze_protocol(self.path, protocol_freeze)
        with ExitStack() as stack:
            for p in self.helper.patches(look_failure=look_failure, speak_failures=speak_failures):
                stack.enter_context(p)
            stack.enter_context(patch('app.routes.face.models_ready', return_value=True))
            stack.enter_context(patch('app.routes.face.enroll_samples', return_value=(None, self.embedding)))
            app, page = stack.enter_context(collector.capture_app(self.path, 'trial1', self.capture, protocol_freeze=protocol_freeze))
            self.assertNotEqual(Config.DATABASE_PATH, ROOT / 'authx.db')
            self.assertEqual(Config.SMTP_USER, '')
            client = app.test_client()
            text = client.get(page).get_data(as_text=True)
            key = json.loads(re.search(r"'X-AuthX-Study': (\"[^\"]+\")", text)[1])
            token = json.loads(re.search(r"Authorization: 'Bearer ' \+ (\"[^\"]+\")", text)[1])
            headers = {'X-AuthX-Study': key, 'Authorization': 'Bearer ' + token}
            self.assertEqual(client.post('/api/face/enroll', headers=headers, json={'images': [captures.image64()]*5}).status_code, 403)
            self.assertNotIn('resolveStudyRole({role:', text.split('study-agree\').onclick')[0] if "study-agree').onclick" in text else '')
            self.assertEqual(client.post('/study/consent', headers=headers).status_code, 200)
            self.assertEqual(client.post('/api/face/enroll', headers=headers, json={'images': [captures.image64()]*5}).status_code, 403)
            self.assertEqual(client.post('/study/device', headers=headers, json={'deviceKeySha256': '0'*64}).status_code, 403)
            self.assertEqual(client.post('/study/device', headers=headers, json={'deviceKeySha256': self.study['cameras'][0]['deviceKeySha256']}).status_code, 200)
            enrollment = client.post('/api/face/enroll', headers=headers, json={'images': [captures.image64()]*5})
            self.assertTrue(enrollment.json['enrolled'])
            for number in range(2 if two_sessions else 1):
                sid = client.post('/api/session/start', headers=headers).json['sessionId']
                video_frames = frames()
                # Distinct authentic-looking test submissions; no real device is used.
                if number:
                    video_frames[0]['tMs'] += .01
                look = client.post(f'/api/session/{sid}/look', headers=headers, json={'frames': video_frames})
                if look_failure:
                    continue
                self.assertTrue(look.json['ok'])
                for index in range(speak_failures + 1):
                    spoken_frames = deepcopy(video_frames)
                    spoken_frames[0]['tMs'] += (index + 1) * .02
                    response = client.post(f'/api/session/{sid}/speak', headers=headers,
                        json={'frames': spoken_frames, 'wav': captures.audio(), 'audioStartMs': .123})
                    if response.json.get('ok'):
                        break
                if response.json.get('ok'):
                    self.assertTrue(client.post(f'/api/session/{sid}/trust', headers=headers).json['ok'])
                    self.assertTrue(client.post(f'/api/session/{sid}/certificate', headers=headers).json['ok'])
            self.assertEqual(client.post('/api/face/enroll', headers=headers, json={'images': [captures.image64()]*5}).status_code, 409)
            self.assertEqual(client.post('/api/faculty/sessions/x/override', headers=headers, json={'label': 'SAFE'}).status_code, 403)
            if two_sessions:
                self.assertEqual(client.post('/api/session/start', headers=headers).status_code, 409)
            if end:
                self.assertEqual(client.post('/study/end', headers=headers).status_code, 200)
                self.assertEqual(client.post('/study/end', headers=headers).status_code, 200)
                self.assertEqual(client.post('/api/session/start', headers=headers).status_code, 403)
            self.page_text = text
        self.assertEqual(Config.DATABASE_PATH, ROOT / 'authx.db')
        return self.capture

    def prepare(self, **kwargs):
        self.collect(**kwargs)
        self.export = self.folder / 'export'
        collector.export_capture(self.capture, self.export)
        self.ready = self.folder / 'study-ready.json'
        collector.assemble(self.path, [self.export], self.folder / 'dataset', self.ready)
        return study.load_study(self.ready)

    def run_report(self, info):
        with ExitStack() as stack:
            for p in self.helper.patches():
                stack.enter_context(p)
            return harness.run_dataset(study.private_path(info['path'].parent, info['study']['datasetManifest']))

    def mutate_ready(self, change):
        raw = study.read_json(self.ready)
        change(raw)
        self.save(raw, self.ready)
        with self.assertRaises(ValueError):
            study.load_study(self.ready)

    def test_empty_template_is_pending_null_not_passed_or_human_complete(self):
        empty = self.folder / 'empty.json'
        self.save(study.study_template(), empty)
        decision = study.analyze(study.load_study(empty, dataset_required=False))
        self.assertEqual(decision['decision'], 'retain_legacy')
        self.assertFalse(decision['task23HumanEvaluationComplete'])
        self.assertEqual(decision['samples']['uniqueRecordings'], 0)
        self.assertTrue(all(c['rate'] is None and c['status'] == 'unavailable' for c in decision['criteria'].values()))
        self.assertFalse(decision['defaultChanged'])

    def test_duplicate_identity_key_with_different_name_is_rejected(self):
        self.study['subjects'][1]['identityKeySha256'] = self.study['subjects'][0]['identityKeySha256']
        self.save()
        with self.assertRaisesRegex(ValueError, 'Aliased identity'):
            study.load_study(self.path, dataset_required=False)

    def test_missing_withdrawn_changed_or_unreviewed_consent_rejects(self):
        for change in ({'consentReviewed': False}, {'withdrawn': True}, {'recordingPermitted': False}, {'consentSha256': '0'*64}):
            raw = deepcopy(self.study)
            raw['subjects'][0].update(change)
            self.save(raw)
            with self.assertRaises(ValueError):
                study.load_study(self.path, dataset_required=False)

    def test_collector_consent_is_required_isolated_and_no_storage_token_or_automatic_devices(self):
        before = harness.original_inventory()
        self.collect()
        self.assertEqual(before, harness.original_inventory())
        self.assertNotIn('localStorage.setItem', self.page_text)
        self.assertIn('resolveStudyRole=resolve', self.page_text)
        self.assertIn('Wait until recording and scoring finish', self.page_text)
        self.assertEqual(len(study.read_json(self.capture / 'capture-ledger.json')['sessions']), 1)
        if os.getenv('AUTHX_TEST_OUTPUT_DIR'):
            output = Path(os.environ['AUTHX_TEST_OUTPUT_DIR'])
            output.mkdir(parents=True, exist_ok=True)
            scripts = re.findall(r'<script>(.*?)</script>', self.page_text, re.S)
            scripts[0] = re.sub(r"Authorization: 'Bearer ' \+ \"[^\"]+\"", "Authorization: 'Bearer ' + 'CONTROLLED_TEST_TOKEN'", scripts[0])
            scripts[0] = re.sub(r"'X-AuthX-Study': \"[^\"]+\"", "'X-AuthX-Study': 'CONTROLLED_TEST_KEY'", scripts[0])
            (output / 'collector-scripts.json').write_text(json.dumps(scripts), encoding='utf-8')

    def test_exact_export_original_frames_audio_offset_challenge_and_v2_enrollment(self):
        info = self.prepare(speak_failures=1)
        case = info['dataset']['cases'][0]
        self.assertEqual([e['stage'] for e in case.attempts], ['look', 'speak', 'speak'])
        self.assertEqual(case.attempts[1]['payload']['audioStartMs'], .123)
        self.assertEqual(case.attempts[1]['payload']['wav'], captures.audio())
        self.assertEqual(case.attempts[0]['payload']['frames'], frames())
        self.assertEqual(info['dataset']['enrollments'][case.enrollment_id]['blob'].decode(), self.embedding)
        captured = study.read_json(self.capture / 'capture-ledger.json')
        self.assertEqual(case.expected_word, captured['sessions'][0]['word'])
        self.assertEqual(case.flash_start_ms, captured['sessions'][0]['flashStartMs'])

    def test_failed_look_exports_without_fabricated_speak(self):
        info = self.prepare(look_failure='no_blink')
        self.assertEqual([e['stage'] for e in info['dataset']['cases'][0].attempts], ['look'])
        with ExitStack() as stack:
            for p in self.helper.patches(look_failure='no_blink'):
                stack.enter_context(p)
            report = harness.run_dataset(study.private_path(info['path'].parent, info['study']['datasetManifest']), probes=True)
        self.assertTrue(all(not r['completed'] for r in report['results']))
        self.assertTrue(all(r['diagnostics'][0]['reason'] == 'no_original_speak' for r in report['results']))
        decision = study.analyze(info, report, freeze_sha256='0'*64)
        self.assertIsNone(decision['latency']['v2']['rate'])
        self.assertEqual(decision['latency']['v2']['partialFailureSamples'], 1)

    def test_unended_capture_cannot_be_exported(self):
        self.collect(end=False)
        with self.assertRaises(FileNotFoundError):
            collector.export_capture(self.capture, self.folder / 'export')

    def test_attack_source_and_enrollment_split_leakage_are_rejected(self):
        self.prepare()
        self.mutate_ready(lambda data: data['cases'][0].update(sourceSubjectIds=['s3']))

    def test_ground_truth_cannot_be_relabeled_from_model_results(self):
        self.prepare()
        self.mutate_ready(lambda data: data['plannedTrials'][0].update(category='wrong_word'))

    def test_prepared_media_and_private_capture_ledger_tampering_reject(self):
        info = self.prepare()
        raw = study.read_json(self.folder / 'dataset/manifest.json')
        raw['cases'][0]['submissions'][0]['frames'][0]['tMs'] += .0001
        self.save(raw, self.folder / 'dataset/manifest.json')
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            study.load_study(self.ready)

    def test_reused_recording_cannot_be_an_independent_retry(self):
        info = self.prepare(two_sessions=True)
        raw = study.read_json(self.ready)
        raw['cases'][1]['recordings'][0]['id'] = raw['cases'][0]['recordings'][0]['id']
        self.save(raw, self.ready)
        with self.assertRaisesRegex(ValueError, 'Reused recording'):
            study.load_study(self.ready)

    def test_freeze_detects_truth_split_dependency_config_or_original_changes(self):
        info = self.prepare()
        frozen = study.freeze(self.ready, self.folder / 'freeze.json')
        study.assert_frozen(info, frozen)
        with patch.object(Config, 'V2_WORD_MIN_CONFIDENCE', .99):
            with self.assertRaisesRegex(ValueError, 'changed since'):
                study.assert_frozen(info, frozen)
        with patch.object(study, 'source_inventory', return_value={}):
            with self.assertRaises(ValueError):
                study.assert_frozen(info, frozen)
        with self.assertRaises(FileExistsError):
            study.freeze(self.ready, self.folder / 'freeze.json')

    def test_two_sessions_are_one_trial_four_speak_submissions_remain_real(self):
        info = self.prepare(two_sessions=True)
        report = self.run_report(info)
        decision = study.analyze(info, report, freeze_sha256='0'*64)
        self.assertEqual(decision['heldOutProfiles']['v2']['genuineCompletionWithinTwo']['denominator'], 1)
        self.assertEqual(decision['latency']['v2']['distinctSessionAttempts'], 2)
        self.assertEqual(len(decision['actualEnrollmentCollection']), 1)
        self.assertEqual(decision['samples']['registeredSessionAttempts'], 2)

    def test_tuning_demo_repeats_and_duplicate_profile_results_cannot_pass(self):
        info = self.prepare()
        report = self.run_report(info)
        repeated = deepcopy(report); repeated['repetitions'] = 2
        with self.assertRaisesRegex(ValueError, 'Repeat'):
            study.analyze(info, repeated)
        doubled = deepcopy(report); doubled['results'].append(doubled['results'][0])
        with self.assertRaises(ValueError):
            study.analyze(info, doubled)
        self.assertEqual(study.analyze(info, report)['decision'], 'retain_legacy')
        self.assertFalse(study.analyze(info, report)['task23HumanEvaluationComplete'])

    def test_wrong_machine_safe_is_reported_even_without_safe_certificate(self):
        rows = [{'category': 'wrong_person', 'sessions': [], 'wordMatch': True, 'completedWithinTwo': True,
                 'safeWithinTwo': False, 'machineSafe': True, 'retry': False, 'scoringSeconds': 1.}]
        result = study.metrics(rows)
        self.assertEqual(result['incorrectMachineSafe']['numerator'], 1)
        self.assertEqual(result['allCategoryCertificateCompletion']['numerator'], 1)
        self.assertEqual(result['allCategorySafeCompletion']['numerator'], 0)

    def test_replay_word_truth_stays_unknown_without_independent_declaration(self):
        self.study['plannedTrials'][0]['category'] = 'screen_replay'
        self.save()
        info = self.prepare()
        self.assertIsNone(info['dataset']['cases'][0].truth['wordMatch'])
        report = self.run_report(info)
        decision = study.analyze(info, report)
        self.assertEqual(decision['heldOutProfiles']['v2']['wordAgreement']['denominator'], 0)
        self.assertIsNone(decision['heldOutProfiles']['v2']['wordAgreement']['rate'])
        self.assertEqual(decision['heldOutProfiles']['v2']['wordVerified']['denominator'], 1)
        self.assertEqual(decision['groups']['v2']['category']['screen_replay']['allCategoryMachineSafe']['numerator'], 1)

    def test_known_replay_word_truth_is_independent_of_recognition_outcome(self):
        trial = {'category': 'screen_replay', 'wordMatch': False}
        self.assertFalse(study.declared_word_truth(trial))
        rows = [{'category': 'screen_replay', 'wordMatch': False,
                 'sessions': [{'wordAttempts': [{'exactTokenMatch': False, 'wordVerified': False}]}],
                 'completedWithinTwo': False, 'safeWithinTwo': False, 'machineSafe': False, 'retry': False, 'scoringSeconds': 1.}]
        result = study.metrics(rows)
        self.assertEqual(result['wordAgreement']['numerator'], 1)
        self.assertEqual(result['wordAgreement']['denominator'], 1)
        self.assertEqual(result['wordVerified']['numerator'], 0)

    def test_plan_declares_entire_matrix_before_collection_with_separate_sources(self):
        self.study['plannedTrials'] = []
        base = self.study['subjects'][0]
        # Explicitly controlled policy fixtures, never human consent claims.
        for n in range(4, 11):
            self.study['subjects'].append({**base, 'id': 's' + str(n), 'identityKeySha256': harness.digest(str(n).encode()),
                                           'split': 'tuning' if n == 4 else 'evaluation'})
        self.save()
        output = self.folder / 'planned.json'
        with self.assertRaisesRegex(ValueError, 'explicitly declare'):
            study.plan(self.path, output)
        result = study.plan(self.path, output, declare_protocol=True)
        self.assertEqual(len(result['plannedTrials']), 200)
        subjects = {s['id']: s for s in result['subjects']}
        for trial in result['plannedTrials']:
            self.assertTrue(all(subjects[s]['split'] == trial['split'] for s in trial['sourceSubjectIds']))
            if trial['category'] == 'wrong_person':
                self.assertNotEqual(trial['subjectId'], trial['sourceSubjectIds'][0])
        state = study.validation(study.load_study(output, dataset_required=False))
        self.assertFalse(state['readyForValidation'])
        self.assertEqual(state['plannedEvaluationTrials'], 160)
        self.assertEqual(state['missingEvaluationTrials'], 160)

    def test_evaluation_observed_before_scoring_change_cannot_be_called_untouched(self):
        self.prepare()
        with patch.object(Config, 'V2_WORD_MIN_CONFIDENCE', .99):
            with self.assertRaisesRegex(ValueError, 'predate a scoring'):
                study.load_study(self.ready)

    def test_two_labels_for_same_camera_do_not_satisfy_two_camera_requirement(self):
        self.study['cameras'][1]['deviceKeySha256'] = self.study['cameras'][0]['deviceKeySha256']
        self.save()
        with self.assertRaisesRegex(ValueError, 'same camera'):
            study.load_study(self.path, dataset_required=False)

    def test_decision_report_allows_only_anonymous_outcomes_no_media_paths_or_embeddings(self):
        info = self.prepare()
        report = self.run_report(info)
        decision = study.analyze(info, report)
        text = json.dumps(decision)
        for forbidden in (str(self.folder), self.embedding, captures.image64(), captures.audio(), 'consentDocument', 'JWT_SECRET'):
            self.assertNotIn(forbidden, text)
        output = self.folder / 'decision'
        study.write_decision(decision, output)
        self.assertTrue((output / 'readiness.json').exists())
        with self.assertRaises(FileExistsError):
            study.write_decision(decision, output)


if __name__ == '__main__':
    unittest.main(verbosity=2)
