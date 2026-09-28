"""Task 17 policy, evidence provenance and historical outcomes on temporary DBs."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import uploads_quality as captures
from app.models import save_look, save_voice, get_session, get_result, save_trust, get_certificate_for_session
from app.services.risk_engine import fuse, fuse_v2
from app.services.decision_evidence import evaluate_gates, stored_decision, decision_snapshot
from app.services.certificate import issue_certificate, chain_status
from speak_identity import LOOK
import gate_fixture


class DecisionGates(unittest.TestCase):
    setUp = captures.UploadTests.setUp
    start = captures.UploadTests.start

    def options(self, detail=None, **extra):
        return {'cosine': .8, 'speak_cosine': .8, 'expected_word': 'amber',
                'detail_json': detail if detail is not None else gate_fixture.all_detail(), **extra}

    def capped(self, options):
        result = fuse_v2(100, 100, 100, 90, **options)
        self.assertEqual((result['trustScore'], result['riskLabel']), (74, 'SUSPICIOUS'))
        self.assertEqual(result['base'], 100)
        self.assertEqual(result['flashAdjust'], 8)

    def test_every_missing_required_gate_rejects_compensating_scores(self):
        for step, check in (('lookGateEvidence', 'capture'), ('speakGateEvidence', 'capture'),
                            ('lookGateEvidence', 'blink'), ('lookGateEvidence', 'flash'),
                            ('speakGateEvidence', 'lip')):
            with self.subTest(step=step, check=check):
                detail = json.loads(gate_fixture.all_detail())
                del detail[step][check]
                self.capped(self.options(json.dumps(detail)))
        for key in ('cosine', 'speak_cosine'):
            self.capped(self.options(**{key: None}))
        detail = json.loads(gate_fixture.all_detail())
        del detail['speech']
        self.capped(self.options(json.dumps(detail)))

    def test_every_failed_flag_and_non_boolean_flag_fails_closed(self):
        for step, check, flag in (('lookGateEvidence', 'capture', 'usable'),
                                  ('speakGateEvidence', 'capture', 'usable'),
                                  ('lookGateEvidence', 'blink', 'completed'),
                                  ('lookGateEvidence', 'flash', 'measured'),
                                  ('speakGateEvidence', 'lip', 'usable')):
            for value in (False, None, 1, 'true', [], {}):
                with self.subTest(step=step, check=check, value=value):
                    detail = json.loads(gate_fixture.all_detail())
                    detail[step][check][flag] = value
                    self.capped(self.options(json.dumps(detail)))

    def test_malformed_counts_spans_measurements_and_configs_cannot_pass(self):
        fields = [('lookGateEvidence', 'capture', 'usableFrames'),
                  ('lookGateEvidence', 'capture', 'spanMs'), ('lookGateEvidence', 'capture', 'firstFrameMs'),
                  ('speakGateEvidence', 'capture', 'audioDurationMs'), ('speakGateEvidence', 'capture', 'audioStartMs'),
                  ('lookGateEvidence', 'blink', 'cycles'), ('lookGateEvidence', 'blink', 'samples'),
                  ('lookGateEvidence', 'blink', 'totalFrames'), ('lookGateEvidence', 'blink', 'maxGapMs'),
                  ('lookGateEvidence', 'flash', 'beforeSamples'), ('lookGateEvidence', 'flash', 'duringSamples'),
                  ('lookGateEvidence', 'flash', 'beforeSpanMs'), ('lookGateEvidence', 'flash', 'duringSpanMs'),
                  ('lookGateEvidence', 'flash', 'maxGapMs'), ('lookGateEvidence', 'flash', 'delta'),
                  ('speakGateEvidence', 'lip', 'samples'), ('speakGateEvidence', 'lip', 'correlation'),
                  ('speakGateEvidence', 'lip', 'mouthVariance')]
        for step, check, field in fields:
            for value in (None, True, '20', float('nan'), float('inf'), -2):
                with self.subTest(field=field, value=value):
                    detail = json.loads(gate_fixture.all_detail())
                    detail[step][check][field] = value
                    self.capped(self.options(json.dumps(detail)))
        for step in ('lookGateEvidence', 'speakGateEvidence'):
            for value in ({}, None, [], {'V2_FRAME_MIN_COUNT': 0}):
                detail = json.loads(gate_fixture.all_detail())
                detail[step]['config'] = value
                self.capped(self.options(json.dumps(detail)))

    def test_historical_malformed_or_unknown_version_is_not_evidence(self):
        for value in (None, '{}', '[]', 'null', 'true', '{broken', '"text"'):
            self.capped(self.options(value if value is not None else '{}'))
        for step in ('lookGateEvidence', 'speakGateEvidence'):
            detail = json.loads(gate_fixture.all_detail())
            detail[step]['version'] = 'unknown'
            self.capped(self.options(json.dumps(detail)))
        for step, flag in (('lookGateEvidence', 'videoValidated'), ('speakGateEvidence', 'audioValidated')):
            detail = json.loads(gate_fixture.all_detail())
            del detail[step]['capture'][flag]
            self.capped(self.options(json.dumps(detail)))

    def test_all_gates_preserve_original_weights_labels_and_boundaries(self):
        for scores in ((100, 100, 100, 90), (95, 90, 90, 25), (40, 90, 90, 90), (15, 70, 10, 25)):
            self.assertEqual(fuse_v2(*scores, **self.options()), fuse(*scores))
        for raw in (.363, .363001, 1):
            self.assertEqual(fuse_v2(100, 100, 100, 90, **self.options(cosine=raw, speak_cosine=raw))['riskLabel'], 'SAFE')
        for key in ('cosine', 'speak_cosine'):
            for raw in (.36296, True, '0.8', None, float('inf'), float('nan'), 1.01):
                self.capped(self.options(**{key: raw}))

    def test_measured_flat_flash_and_usable_low_lip_scores_remain_eligible(self):
        detail = json.loads(gate_fixture.all_detail())
        detail['lookGateEvidence']['flash'].update(delta=0, correlation=0)
        detail['speakGateEvidence']['lip'].update(correlation=0, mouthVariance=0)
        options = self.options(json.dumps(detail))
        self.assertTrue(evaluate_gates(**options)['safeEligible'])
        # Still mouth score 20 affects combined voice through its original weight.
        self.assertEqual(fuse_v2(100, 100, 80, 25, **options), fuse(100, 100, 80, 25))
        self.assertEqual(fuse_v2(100, 100, 80, 25, **options)['riskLabel'], 'SAFE')

    def test_valid_but_insufficient_coverage_does_not_pass(self):
        for step, check, field, value in (
                ('lookGateEvidence', 'capture', 'usableFrames', 47),
                ('speakGateEvidence', 'capture', 'usableFrames', 7),
                ('lookGateEvidence', 'blink', 'cycles', 0),
                ('lookGateEvidence', 'blink', 'samples', 31),
                ('lookGateEvidence', 'blink', 'maxGapMs', 151),
                ('lookGateEvidence', 'flash', 'beforeSamples', 3),
                ('lookGateEvidence', 'flash', 'duringSpanMs', 149.99),
                ('lookGateEvidence', 'flash', 'maxGapMs', 150.01),
                ('lookGateEvidence', 'flash', 'maxGapMs', 0),
                ('speakGateEvidence', 'lip', 'samples', 47),
                ('speakGateEvidence', 'lip', 'maxGapMs', 151)):
            detail = json.loads(gate_fixture.all_detail())
            detail[step][check][field] = value
            self.capped(self.options(json.dumps(detail)))
        for step, check in (('speakGateEvidence', 'lip'), ('lookGateEvidence', 'blink')):
            detail = json.loads(gate_fixture.all_detail())
            detail[step][check]['maxGapMs'] = 0
            self.capped(self.options(json.dumps(detail)))

    def begun(self, detail=None):
        session_id = self.start()
        word = get_session(session_id)['challenge_word']
        save_look(session_id, LOOK)
        save_voice(session_id, {'acousticScore': 100, 'lipScore': 100, 'lipR': .8, 'voiceScore': 100,
                                'speakCosine': .8, 'detail': gate_fixture.speak_detail(word) if detail is None else detail})
        return session_id

    def test_server_evidence_and_pinned_profile_not_client_fields(self):
        session_id = self.begun()
        row = get_result(session_id)
        self.app.config['VERIFICATION_PROFILE'] = 'legacy'
        conn = __import__('app.models', fromlist=['connect']).connect()
        try:
            detail = json.loads(row['detail_json'])
            del detail['lookGateEvidence']['flash']
            conn.execute('UPDATE results SET detail_json = ? WHERE session_id = ?', (json.dumps(detail), session_id))
            conn.commit()
        finally:
            conn.close()
        response = self.client.post(f'/api/session/{session_id}/trust', headers=self.headers,
                                    json={'evidence': json.loads(gate_fixture.all_detail()),
                                          'verificationVersion': 'legacy', 'cosine': 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['riskLabel'], 'SUSPICIOUS')
        machine = stored_decision(get_result(session_id)['detail_json'])
        self.assertEqual(machine['gates']['flash'], 'not_recorded')
        self.assertFalse(machine['safeEligible'])
        self.assertEqual(machine['config']['SAFE_MIN'], 75)
        self.assertEqual(machine['config']['WEIGHT_FACE'], .45)
        self.assertIn('speakGateEvidence', json.loads(get_result(session_id)['detail_json']))

    def test_new_v2_certificate_requires_a_gated_machine_decision(self):
        session_id = self.begun()
        save_trust(session_id, 100, 'SAFE')
        self.assertIsNone(issue_certificate(session_id))
        self.assertEqual(self.client.post(f'/api/session/{session_id}/certificate', headers=self.headers).get_json()['reason'], 'evidence_required')
        self.assertEqual(self.client.post(f'/api/session/{session_id}/trust', headers=self.headers).status_code, 200)
        cert = issue_certificate(session_id)
        self.assertEqual(chain_status(cert['cert_id']), 'intact')
        frozen = dict(cert)
        conn = __import__('app.models', fromlist=['connect']).connect()
        try:
            conn.execute('UPDATE results SET detail_json = ? WHERE session_id = ?', ('{}', session_id))
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(dict(issue_certificate(session_id)), frozen)

    def test_legacy_keeps_original_arithmetic_and_certificate_behavior(self):
        self.app.config['VERIFICATION_PROFILE'] = 'legacy'
        session_id = self.begun(detail={})
        response = self.client.post(f'/api/session/{session_id}/trust', headers=self.headers)
        self.assertEqual(response.get_json()['riskLabel'], 'SAFE')
        self.assertIsNone(stored_decision(get_result(session_id)['detail_json']))
        self.assertIsNotNone(issue_certificate(session_id))

    def test_failed_word_and_raw_identity_cannot_be_replaced_by_flags(self):
        for confidence in (.799999, None, True, float('nan')):
            detail = json.loads(gate_fixture.all_detail())
            detail['speech']['words'][0]['confidence'] = confidence
            self.capped(self.options(json.dumps(detail)))
        self.capped(self.options(expected_word='bridge'))

    def test_malformed_machine_snapshot_cannot_authorize_new_issuance(self):
        options = self.options()
        machine = decision_snapshot(fuse_v2(100, 100, 100, 90, **options), evaluate_gates(**options))
        self.assertIsNotNone(stored_decision({'machineDecision': machine}))
        for bad in ({'safeEligible': False}, {'gates': {}}, {'trustScore': True}, {'base': float('nan')},
                    {'version': 'unknown'}, {'config': {}}, {'riskLabel': 'SUSPICIOUS'}):
            self.assertIsNone(stored_decision({'machineDecision': {**machine, **bad}}))


if __name__ == '__main__':
    unittest.main(verbosity=2)
