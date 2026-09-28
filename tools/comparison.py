"""Offline paired-media comparison through real routes, using one temporary DB.

No application factory is called on import. Raw assets stay in the dataset directory;
only whitelisted outcomes, evidence, hashes and timings leave the driver.
"""
import argparse
import base64
import contextlib
from copy import deepcopy
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import io
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
from werkzeug.exceptions import RequestEntityTooLarge

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import Config

DATASET_VERSION = 'authx-comparison-dataset-1'
REPORT_VERSION = 'authx-comparison-report-1'
PROFILES = ('legacy', 'v2')
SETUP_REASONS = {'model_missing', 'landmark_model_missing', 'landmark_model_invalid', 'speech_model_missing',
                 'speech_model_invalid', 'speech_runtime_unavailable', 'speech_configuration_invalid',
                 'verification_unavailable', 'not_enrolled', 'invalid_face_embedding'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', value):
        raise ValueError('Invalid stable identifier')
    return value


def asset(base, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError('Asset paths must be relative to the dataset')
    path = (base / relative).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise ValueError('Missing asset or path outside dataset')
    return path.read_bytes()


def frame_payload(base, frames):
    if not isinstance(frames, list):
        raise ValueError('Frame records must be a list')
    # Do not repair, interpolate or validate timing here. Real route policy
    # decides whether the original upload is usable, separately per profile.
    return [{'tMs': frame.get('tMs'), 'image': base64.b64encode(asset(base, frame['path'])).decode('ascii')}
            for frame in frames]


@dataclass(frozen=True)
class Case:
    case_id: str
    fixture_category: str
    split: str
    timing_provenance: str
    expected_word: str
    flash_start_ms: int
    enrollment_id: str
    truth: dict
    attempts: tuple
    input_hash: str


def load_dataset(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite manifest value')))
    if not isinstance(data, dict) or data.get('schemaVersion') != DATASET_VERSION:
        raise ValueError('Unsupported dataset version')
    identifier(data.get('datasetId'))
    enrollment = data.get('enrollments')
    if not isinstance(enrollment, dict) or not enrollment:
        raise ValueError('Enrollment references are required')
    prepared = {}
    for name, reference in enrollment.items():
        identifier(name)
        method = reference.get('method')
        if method not in ('legacy_single_image', 'existing_embedding'):
            raise ValueError('Unsupported common enrollment method')
        blob = asset(path.parent, reference['path'])
        prepared[name] = {'method': method, 'blob': blob}
    cases = []
    seen = set()
    if not isinstance(data.get('cases'), list) or not data['cases']:
        raise ValueError('Nonempty cases are required')
    for row in data['cases']:
        case_id = identifier(row.get('id'))
        if case_id in seen:
            raise ValueError('Duplicate case identifier')
        seen.add(case_id)
        category = row.get('fixtureCategory')
        if category not in ('public', 'synthetic', 'consented'):
            raise ValueError('Explicit fixture category is required')
        if category == 'consented' and row.get('consentRecorded') is not True:
            raise ValueError('Consented cases require a recorded consent declaration')
        if row.get('split') not in ('demo', 'tuning', 'evaluation'):
            raise ValueError('Explicit dataset split is required')
        if row.get('timingProvenance') not in ('captured_sample_clock', 'synthetic_schedule'):
            raise ValueError('Timing provenance is required')
        word = row.get('expectedWord')
        flash = row.get('flashStartMs')
        if word not in Config.CHALLENGE_WORDS:
            raise ValueError('Expected word must be an existing server challenge')
        if isinstance(flash, bool) or not isinstance(flash, int) or not Config.FLASH_START_MIN_MS <= flash <= Config.FLASH_START_MAX_MS:
            raise ValueError('Flash timing must be within server bounds')
        if row.get('enrollment') not in prepared:
            raise ValueError('Unknown enrollment reference')
        truth = row.get('groundTruth')
        if not isinstance(truth, dict) or truth.get('category') not in (
                'unknown', 'genuine', 'wrong_person', 'wrong_word', 'photo', 'screen_replay', 'other_negative'):
            raise ValueError('Explicit ground truth category is required')
        for key in ('safeExpected', 'wordMatch'):
            if truth.get(key) is not None and not isinstance(truth[key], bool):
                raise ValueError('Ground truth is boolean or null')
        attempts = []
        sequence = row.get('submissions')
        if sequence is not None:
            if not isinstance(sequence, list) or not sequence:
                raise ValueError('Nonempty original submission sequence is required')
            for event in sequence:
                stage = event.get('stage')
                if stage not in ('look', 'speak'):
                    raise ValueError('Original submissions must be Look or Speak')
                payload = {'frames': frame_payload(path.parent, event['frames'])}
                if stage == 'speak':
                    payload.update(wav=base64.b64encode(asset(path.parent, event['wav'])).decode('ascii'),
                                   audioStartMs=event.get('audioStartMs', 0))
                attempts.append({'stage': stage, 'payload': payload})
        elif not isinstance(row.get('attempts'), list) or not row['attempts']:
            raise ValueError('At least one original paired capture is required')
        for attempt in row.get('attempts', []) if sequence is None else []:
            look = {'frames': frame_payload(path.parent, attempt['lookFrames'])}
            speak = {'frames': frame_payload(path.parent, attempt['speakFrames']),
                     'wav': base64.b64encode(asset(path.parent, attempt['wav'])).decode('ascii'),
                     'audioStartMs': attempt.get('audioStartMs', 0)}
            attempts.append({'look': look, 'speak': speak})
        fingerprint = digest(canonical({'enrollment': digest(prepared[row['enrollment']]['blob']), 'word': word,
                                       'flash': flash, 'attempts': attempts}))
        cases.append(Case(case_id, category, row['split'], row['timingProvenance'], word, flash, row['enrollment'],
                          {key: truth.get(key) for key in ('category', 'safeExpected', 'wordMatch')}, tuple(attempts), fingerprint))
    return {'datasetId': data['datasetId'], 'manifestSha256': digest(raw), 'enrollments': prepared, 'cases': cases}


def original_inventory():
    files = [ROOT / 'authx.db', ROOT / 'requirements.txt', ROOT / 'requirements.lock']
    files += sorted(p for p in (ROOT / 'models').rglob('*') if p.is_file())
    hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): digest(p.read_bytes()) for p in files if p.is_file()}
    database = ROOT / 'authx.db'
    row_hash = None
    if database.is_file():
        with contextlib.closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as conn:
            rows = {name: conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
                    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            row_hash = digest(repr(rows).encode())
    return {'fileHashes': hashes, 'allOriginalRowsSha256': row_hash}


@contextlib.contextmanager
def isolated_app():
    # models.connect reads Config.DATABASE_PATH, so set it before app creation.
    old = {key: getattr(Config, key) for key in ('DATABASE_PATH', 'VERIFICATION_PROFILE', 'SMTP_USER', 'SMTP_PASSWORD')}
    with tempfile.TemporaryDirectory(prefix='authx-comparison-') as folder:
        try:
            Config.DATABASE_PATH = Path(folder) / 'comparison.db'
            Config.VERIFICATION_PROFILE = 'legacy'
            Config.SMTP_USER = Config.SMTP_PASSWORD = ''
            from app import create_app
            with contextlib.redirect_stdout(io.StringIO()):
                app = create_app()
            app.config['TESTING'] = True
            with app.app_context():
                yield app
        finally:
            for key, value in old.items():
                setattr(Config, key, value)


def finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def speech_summary(record, expected_word):
    if not isinstance(record, dict):
        return None
    transcript = record.get('transcript')
    if not isinstance(transcript, str):
        return None
    confidence = record.get('matchedConfidence', record.get('confidence'))
    words = record.get('words') if isinstance(record.get('words'), list) else []
    valid = [w.get('confidence') for w in words if isinstance(w, dict) and finite(w.get('confidence')) and 0 <= w['confidence'] <= 1]
    if not finite(confidence) or not 0 <= confidence <= 1:
        confidence = valid[0] if len(valid) == 1 else None
    return {'transcript': transcript[:1000], 'confidence': confidence,
            'exactTokenMatch': re.findall(r'\w+', transcript.casefold()) == [expected_word.casefold()],
            'wordVerified': record.get('wordVerified', record.get('verified')) is True,
            'grammarRestricted': record.get('grammarRestricted'),
            'speechVersion': record.get('speechVersion'), 'wordConfigVersion': record.get('wordConfigVersion')}


def stage_record(stage, response, seconds, attempt=None):
    data = response.get_json(silent=True) or {}
    reason = data.get('reason') or data.get('error')
    return {'stage': stage, 'attempt': attempt, 'httpStatus': response.status_code,
            'ok': data.get('ok') is True, 'reason': reason, 'attemptReason': data.get('attemptReason'),
            'retryable': data.get('retryable') is True,
            'setupFailure': (data.get('attemptReason') or reason) in SETUP_REASONS, 'attemptsUsed': data.get('attemptsUsed'),
            'seconds': seconds}, data


def run_case(app, client, headers, case, profile, repetition, order, probes=False):
    from app import models
    from app.services.decision_evidence import stored_decision
    from app.services.verification_profiles import get_profile
    from app.services import uploads, speech
    from app.routes import verification
    stages, words = [], []
    started = time.perf_counter()
    def post(stage, url, payload=None, attempt=None):
        began = time.perf_counter()
        try:
            response = client.post(url, headers=headers, json=deepcopy(payload) if payload is not None else None)
        except Exception as exc:
            # Preserve a per-case operational failure without exporting exception
            # messages (which can contain local paths, recordings or account data).
            record = {'stage': stage, 'attempt': attempt, 'httpStatus': 500, 'ok': False,
                      'reason': 'route_exception', 'exceptionType': type(exc).__name__,
                      'retryable': False, 'setupFailure': True, 'attemptsUsed': None,
                      'seconds': time.perf_counter() - began}
            stages.append(record)
            return record, {}
        record, data = stage_record(stage, response, time.perf_counter() - began, attempt)
        stages.append(record)
        return record, data
    # Fixture-only SERVER settings, never a recognizer vocabulary/grammar.
    app.config.update(VERIFICATION_PROFILE=profile, CHALLENGE_WORDS=(case.expected_word,),
                      FLASH_START_MIN_MS=case.flash_start_ms, FLASH_START_MAX_MS=case.flash_start_ms)
    _, data = post('start', '/api/session/start')
    sid = data.get('sessionId')
    completed = False
    if sid:
        session = models.get_session(sid)
        if (session['verification_profile'], session['challenge_word'], session['flash_start_ms']) != (
                profile, case.expected_word, case.flash_start_ms):
            raise AssertionError('Pinned server inputs changed')
        for index, attempt in enumerate(case.attempts, 1):
            if 'stage' in attempt:
                # Exact collector events: never invent a Speak after failed Look,
                # and never retry with a recording that was not actually submitted.
                if attempt['stage'] == 'look':
                    if models.get_result(sid) is not None:
                        continue
                    look, _ = post('look', f'/api/session/{sid}/look', attempt['payload'], index)
                    if not look['ok'] and (look['setupFailure'] or not look['retryable']):
                        break
                    continue
                row = models.get_result(sid)
                if row is None:
                    continue
                if row['voice_score'] is None:
                    spoken, body = post('speak', f'/api/session/{sid}/speak', attempt['payload'], index)
                    measured = speech_summary((body.get('evidence') or {}).get('speech'), case.expected_word)
                    if measured:
                        words.append({'attempt': index, **measured})
                    if not spoken['ok']:
                        if spoken['setupFailure'] or not spoken['retryable']:
                            break
                        continue
                trusted, _ = post('trust', f'/api/session/{sid}/trust')
                if trusted['ok']:
                    issued, _ = post('certificate', f'/api/session/{sid}/certificate')
                    completed = issued['ok']
                break
            if models.get_result(sid) is None:
                look, _ = post('look', f'/api/session/{sid}/look', attempt['look'], index)
                if not look['ok']:
                    if look['setupFailure'] or not look['retryable']:
                        break
                    continue
            row = models.get_result(sid)
            if row['voice_score'] is None:
                spoken, body = post('speak', f'/api/session/{sid}/speak', attempt['speak'], index)
                measured = speech_summary((body.get('evidence') or {}).get('speech'), case.expected_word)
                if measured:
                    words.append({'attempt': index, **measured})
                if not spoken['ok']:
                    if spoken['setupFailure'] or not spoken['retryable']:
                        break
                    continue
            trusted, _ = post('trust', f'/api/session/{sid}/trust')
            if trusted['ok']:
                issued, _ = post('certificate', f'/api/session/{sid}/certificate')
                completed = issued['ok']
            break
    total = time.perf_counter() - started
    session = models.get_session(sid) if sid else None
    result = models.get_result(sid) if sid else None
    decision = stored_decision(result['detail_json']) if result and profile == 'v2' else None
    label = session['machine_risk_label'] if session else None
    failure = next((s for s in reversed(stages) if not s['ok']), None) if not completed else None
    row = {'caseId': case.case_id, 'fixtureCategory': case.fixture_category, 'split': case.split,
           'timingProvenance': case.timing_provenance, 'groundTruth': case.truth, 'profile': profile,
           'expectedWord': case.expected_word, 'flashStartMs': case.flash_start_ms,
           'repetition': repetition, 'orderInRun': order, 'inputSha256': case.input_hash,
           'completed': completed, 'acceptedSafe': completed and label == 'SAFE',
           'machineRiskLabel': label, 'machineTrustScore': session['machine_trust_score'] if session else None,
           'safeEligible': decision['safeEligible'] if decision else None,
           'safeEligibilityStatus': 'measured' if decision else 'not_required' if profile == 'legacy' else 'not_recorded',
           'failureStage': failure['stage'] if failure else None, 'failureReason': failure['reason'] if failure else None,
           'retryRequested': any(not s['ok'] and s['retryable'] and not s['setupFailure'] for s in stages),
           'speakSubmissionsSpent': session['speak_attempts'] if session and profile == 'v2' else None,
           'wordAttempts': words, 'stages': stages, 'processingSeconds': total, 'diagnostics': []}
    if probes:
        # Independent service diagnostics never save fabricated Look or decision evidence.
        # They can measure Speak/word components even when the actual flow stopped at Look.
        payload = (next((event['payload'] for event in case.attempts if event.get('stage') == 'speak'), None)
                   if 'stage' in case.attempts[0] else case.attempts[0]['speak'])
        if payload is None:
            row['diagnostics'].append({'stage': 'speak_component', 'includedInAcceptance': False,
                                      'ok': False, 'reason': 'no_original_speak', 'seconds': None, 'speech': None})
            return row
        begun = time.perf_counter()
        try:
            with app.test_request_context(json=deepcopy(payload)):
                from flask import request
                original = request.get_json()  # Enforce the same 8 MiB request bound.
                if profile == 'v2':
                    frames = uploads.frames(original)
                    samples, rate = uploads.wav(original)
                    options = {'audio_start_ms': uploads.audio_start_ms(original),
                               'embedding': models.get_user_by_username('avinash')['face_embedding'], 'expected_word': case.expected_word}
                else:
                    samples, rate, error = verification._wav_from_request()
                    if error:
                        raise uploads.UploadError(error)
                    frames = verification._optional_frames()
                    options = {}
                scored = get_profile(profile).score_speak(frames, samples, rate, **options)
            detail = scored.get('detail') if isinstance(scored.get('detail'), dict) else {}
            row['diagnostics'].append({'stage': 'speak_component', 'includedInAcceptance': False,
                'ok': scored['ok'] is True, 'reason': scored.get('reason'), 'seconds': time.perf_counter() - begun,
                'speech': speech_summary(scored.get('speech') or detail.get('speech'), case.expected_word)})
        except (uploads.UploadError, RequestEntityTooLarge) as exc:
            row['diagnostics'].append({'stage': 'speak_component', 'includedInAcceptance': False,
                'ok': False, 'reason': getattr(exc, 'reason', 'upload_too_large'), 'seconds': time.perf_counter() - begun, 'speech': None})
        except Exception as exc:
            row['diagnostics'].append({'stage': 'speak_component', 'includedInAcceptance': False,
                'ok': False, 'reason': 'component_exception', 'exceptionType': type(exc).__name__,
                'seconds': time.perf_counter() - begun, 'speech': None})
        # The legacy policy has no word check; measuring a diagnostic word does not change it.
        begun = time.perf_counter()
        try:
            samples, rate = uploads.wav(payload)
            verified = speech.verify_word(samples, rate, case.expected_word)
            row['diagnostics'].append({'stage': 'word_component', 'includedInAcceptance': False,
                'ok': verified['ok'], 'reason': verified.get('reason'), 'seconds': time.perf_counter() - begun,
                'speech': speech_summary(verified.get('speech'), case.expected_word)})
        except uploads.UploadError as exc:
            row['diagnostics'].append({'stage': 'word_component', 'includedInAcceptance': False,
                'ok': False, 'reason': exc.reason, 'seconds': time.perf_counter() - begun, 'speech': None})
        except Exception as exc:
            row['diagnostics'].append({'stage': 'word_component', 'includedInAcceptance': False,
                'ok': False, 'reason': 'component_exception', 'exceptionType': type(exc).__name__,
                'seconds': time.perf_counter() - begun, 'speech': None})
    return row


def rate(numerator, denominator, reason):
    return {'numerator': numerator, 'denominator': denominator,
            'rate': numerator / denominator if denominator else None,
            'unavailableReason': None if denominator else reason}


def timing(values):
    values = sorted(v for v in values if finite(v) and v >= 0)
    return {'n': len(values), 'meanSeconds': sum(values) / len(values) if values else None,
            'medianSeconds': (values[(len(values)-1)//2] + values[len(values)//2]) / 2 if values else None,
            'p95Seconds': values[math.ceil(.95 * len(values))-1] if values else None,
            'percentileMethod': 'nearest-rank', 'unavailableReason': None if values else 'No measured processing times'}


def aggregate(rows):
    output = {}
    for profile in PROFILES:
        group = [r for r in rows if r['profile'] == profile]
        genuine = [r for r in group if r['groundTruth'].get('category') == 'genuine' and r['groundTruth'].get('safeExpected') is True]
        negative = [r for r in group if r['groundTruth'].get('safeExpected') is False]
        measured = [w for r in group for w in r['wordAttempts']]
        known_words = [(w, r['groundTruth']['wordMatch']) for r in group for w in r['wordAttempts']
                       if r['groundTruth'].get('wordMatch') is not None]
        submissions = [s for r in group for s in r['stages'] if s['stage'] in ('look', 'speak')]
        diagnostics = [d for r in group for d in r['diagnostics'] if d['stage'] == 'word_component' and d.get('speech')]
        known_diagnostics = [(d['speech'], r['groundTruth']['wordMatch']) for r in group for d in r['diagnostics']
                             if d['stage'] == 'word_component' and d.get('speech') and r['groundTruth'].get('wordMatch') is not None]
        output[profile] = {'caseRuns': len(group), 'uniqueCases': len({r['caseId'] for r in group}),
            'completion': rate(sum(r['completed'] for r in group), len(group), 'No case runs'),
            'safeAcceptance': rate(sum(r['acceptedSafe'] for r in group), len(group), 'No case runs'),
            'machineSafeOutcomes': sum(r['machineRiskLabel'] == 'SAFE' for r in group),
            'genuineCompletion': rate(sum(r['completed'] for r in genuine), len(genuine), 'No known genuine cases'),
            'genuineSafeAcceptance': rate(sum(r['acceptedSafe'] for r in genuine), len(genuine), 'No known genuine cases'),
            'genuineSafeWithinTwoCaptures': rate(sum(r['acceptedSafe'] and max((s['attempt'] or 0 for s in r['stages']), default=0) <= 2
                                                    for r in genuine), len(genuine), 'No known genuine cases'),
            'incorrectSafe': rate(sum(r['machineRiskLabel'] == 'SAFE' for r in negative), len(negative), 'No cases with known negative SAFE ground truth'),
            'knownNegativeCompleted': sum(r['completed'] for r in negative),
            'unknownSafeGroundTruth': sum(r['groundTruth'].get('safeExpected') is None for r in group),
            'retryCaseRate': rate(sum(r['retryRequested'] for r in group), len(group), 'No case runs'),
            'retrySubmissionRate': rate(sum(not s['ok'] and s['retryable'] and not s['setupFailure'] for s in submissions),
                                        len(submissions), 'No capture submissions'),
            'wordExactMatch': rate(sum(w['exactTokenMatch'] for w in measured), len(measured), 'No word recognition measured in the full flow'),
            'wordVerified': rate(sum(w['wordVerified'] for w in measured), len(measured), 'No word verification measured in the full flow'),
            'wordAgreementAccuracy': rate(sum(w['exactTokenMatch'] == truth for w, truth in known_words), len(known_words), 'No full-flow measured words with known word-agreement truth'),
            'diagnosticWordVerified': rate(sum(d['speech']['wordVerified'] for d in diagnostics), len(diagnostics), 'No diagnostic word evidence'),
            'diagnosticWordAgreementAccuracy': rate(sum(w['exactTokenMatch'] == truth for w, truth in known_diagnostics),
                                                     len(known_diagnostics), 'No diagnostic words with known agreement truth'),
            'fullFlowTiming': timing([r['processingSeconds'] for r in group]),
            'completedFlowTiming': timing([r['processingSeconds'] for r in group if r['completed']]),
            'stageTiming': {name: timing([s['seconds'] for r in group for s in r['stages'] if s['stage'] == name])
                            for name in ('start', 'look', 'speak', 'trust', 'certificate')},
            'diagnosticTiming': {name: timing([d['seconds'] for r in group for d in r['diagnostics'] if d['stage'] == name])
                                 for name in ('speak_component', 'word_component')}}
    return output


def metadata(app):
    keys = [key for key in app.config if key.startswith('V2_')]
    keys += ['COSINE_MATCH', 'WEIGHT_FACE', 'WEIGHT_BLINK', 'WEIGHT_VOICE', 'VOICE_ACOUSTIC', 'VOICE_LIP',
             'SAFE_MIN', 'SUSPICIOUS_MIN', 'FLASH_ADJUST', 'FLASH_DURATION_MS', 'FACE_SAFE_CAP', 'FACE_CAP_TRUST']
    return {'python': sys.version.split()[0], 'defaultProfile': 'legacy',
            'harnessSha256': digest(Path(__file__).read_bytes()),
            'dependencies': {name: version(name) for name in ('Flask', 'numpy', 'opencv-contrib-python', 'mediapipe', 'vosk')},
            'gateVersion': 'v2-decision-gates-1', 'wordVersion': 'single-token-confidence-1',
            'config': {key: app.config[key] for key in sorted(set(keys))},
            'sourceSha256': digest(canonical({str(p.relative_to(ROOT)).replace('\\', '/'): digest(p.read_bytes())
                                            for p in sorted((ROOT / 'app').rglob('*.py'))})),
            'timingScope': 'Synchronous test-client routes from session start through certificate or failure; excludes dataset IO, common enrollment, live capture/device/browser delays, and diagnostics.',
            'orderPolicy': 'Alternate profile order per case and repetition; shared model caches, no guaranteed cold/warm isolation.',
            'metricUnit': 'case run; repetitions are repeated measurements, not additional independent recordings'}


def run_dataset(path, *, repetitions=1, probes=False):
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 1:
        raise ValueError('Repetitions must be a positive integer')
    dataset = load_dataset(path)
    before = original_inventory()
    started = time.perf_counter()
    rows, enrollment_outcomes = [], {}
    try:
        with isolated_app() as app:
            from app import models
            from app.services.face_embedding import unit_vector
            import jwt
            setup_seconds = time.perf_counter() - started
            client = app.test_client()
            user = models.get_user_by_username('avinash')
            token = jwt.encode({'sub': str(user['id'])}, app.config['JWT_SECRET'], algorithm='HS256')
            headers = {'Authorization': 'Bearer ' + token}
            for name, reference in dataset['enrollments'].items():
                began = time.perf_counter()
                if reference['method'] == 'legacy_single_image':
                    response = client.post('/api/face/enroll', headers=headers,
                                           json={'image': base64.b64encode(reference['blob']).decode('ascii')})
                    body = response.get_json()
                    ok, reason = body.get('ok') is True, body.get('reason')
                    embedding = models.get_user_by_username('avinash')['face_embedding'] if ok else None
                else:
                    embedding = reference['blob'].decode('utf-8')
                    ok = unit_vector(embedding) is not None
                    reason = None if ok else 'invalid_face_embedding'
                enrollment_outcomes[name] = {'ok': ok, 'reason': reason, 'method': reference['method'],
                                             'seconds': time.perf_counter() - began, 'embedding': embedding}
            order = 0
            for repetition in range(1, repetitions + 1):
                for index, case in enumerate(dataset['cases']):
                    enrollment = enrollment_outcomes[case.enrollment_id]
                    profiles = PROFILES if (index + repetition) % 2 else PROFILES[::-1]
                    for profile in profiles:
                        order += 1
                        models.save_face_embedding(user['id'], enrollment['embedding'])
                        if not enrollment['ok']:
                            rows.append({'caseId': case.case_id, 'fixtureCategory': case.fixture_category, 'split': case.split,
                                'timingProvenance': case.timing_provenance, 'groundTruth': case.truth, 'profile': profile,
                                'expectedWord': case.expected_word, 'flashStartMs': case.flash_start_ms,
                                'repetition': repetition, 'orderInRun': order, 'inputSha256': case.input_hash,
                                'completed': False, 'acceptedSafe': False, 'machineRiskLabel': None, 'machineTrustScore': None,
                                'safeEligible': None, 'safeEligibilityStatus': 'not_recorded', 'failureStage': 'enrollment',
                                'failureReason': enrollment['reason'], 'retryRequested': False, 'speakSubmissionsSpent': None,
                                'wordAttempts': [], 'stages': [], 'processingSeconds': None, 'diagnostics': []})
                        else:
                            rows.append(run_case(app, client, headers, case, profile, repetition, order, probes))
                    # Driver only provides independent copies of these same original payloads.
                    check_hash = digest(canonical({'enrollment': digest(dataset['enrollments'][case.enrollment_id]['blob']),
                                                  'word': case.expected_word, 'flash': case.flash_start_ms, 'attempts': case.attempts}))
                    assert check_hash == case.input_hash, 'Prepared original media mutated'
            meta = metadata(app)
    finally:
        after = original_inventory()
        if after != before:
            raise AssertionError('Protected original inventory changed')
    return {'schemaVersion': REPORT_VERSION, 'createdAt': datetime.now(timezone.utc).isoformat(),
            'datasetId': dataset['datasetId'], 'datasetManifestSha256': dataset['manifestSha256'],
            'repetitions': repetitions, 'uniqueCases': len(dataset['cases']), 'metadata': meta,
            'setupSeconds': setup_seconds,
            'enrollments': {name: {key: value for key, value in row.items() if key != 'embedding'}
                            for name, row in enrollment_outcomes.items()},
            'preservation': {'protectedFiles': len(before['fileHashes']), 'allOriginalFilesUnchanged': True,
                             'allOriginalRowsUnchanged': True, 'inventory': before},
            'results': rows, 'aggregate': aggregate(rows)}


def csv_safe(value):
    return "'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value


def write_report(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'results.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    fields = ['caseId', 'profile', 'repetition', 'fixtureCategory', 'split', 'expectedWord', 'flashStartMs', 'completed', 'acceptedSafe',
              'machineRiskLabel', 'machineTrustScore', 'safeEligible', 'failureStage', 'failureReason',
              'retryRequested', 'speakSubmissionsSpent', 'processingSeconds', 'transcript', 'confidence', 'wordVerified', 'inputSha256']
    with (output / 'results.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in report['results']:
            word = row['wordAttempts'][-1] if row['wordAttempts'] else {}
            writer.writerow({key: csv_safe(word.get(key) if key in ('transcript', 'confidence', 'wordVerified') else row.get(key))
                             for key in fields})
    diagnostic_fields = ['caseId', 'profile', 'repetition', 'stage', 'includedInAcceptance', 'ok', 'reason',
                         'seconds', 'transcript', 'confidence', 'exactTokenMatch', 'wordVerified']
    with (output / 'diagnostics.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=diagnostic_fields)
        writer.writeheader()
        for row in report['results']:
            for item in row['diagnostics']:
                speech = item.get('speech') or {}
                merged = {**row, **item, **speech}
                writer.writerow({key: csv_safe(merged.get(key)) for key in diagnostic_fields})
    with (output / 'aggregate.csv').open('w', newline='', encoding='utf-8') as handle:
        fields = ['profile', 'metric', 'numerator', 'denominator', 'rate', 'unavailableReason', 'n', 'meanSeconds', 'medianSeconds', 'p95Seconds']
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        def visit(profile, name, value):
            if not isinstance(value, dict):
                return
            if 'rate' in value or 'meanSeconds' in value:
                writer.writerow({key: csv_safe(profile if key == 'profile' else name if key == 'metric' else value.get(key)) for key in fields})
            else:
                for key, child in value.items():
                    visit(profile, name + '/' + key, child)
        for profile, metrics in report['aggregate'].items():
            for name, value in metrics.items():
                visit(profile, name, value)
    lines = [f"# Comparison: {report['datasetId']}", '',
             f"{report['uniqueCases']} unique cases; {report['repetitions']} repetitions. Repeats are not independent recordings.", '',
             '| Profile | Completed | SAFE accepted | Incorrect SAFE | Retry cases | Full-flow word verified | Mean processing |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    def display(metric):
        return f"{metric['numerator']}/{metric['denominator']}" if metric['denominator'] else 'Unavailable: ' + metric['unavailableReason']
    for profile, metrics in report['aggregate'].items():
        seconds = metrics['fullFlowTiming']['meanSeconds']
        duration = f'{seconds:.4f} s' if seconds is not None else 'Unavailable: no flow was processed'
        lines.append(f"| {profile} | {display(metrics['completion'])} | {display(metrics['safeAcceptance'])} | {display(metrics['incorrectSafe'])} | "
                     f"{display(metrics['retryCaseRate'])} | {display(metrics['wordVerified'])} | {duration} |")
    lines += ['', report['metadata']['timingScope'], '',
              '| Independent word diagnostics (excluded from acceptance) | Verified | Known token agreement |',
              '| --- | --- | --- |']
    for profile, metrics in report['aggregate'].items():
        lines.append(f"| {profile} | {display(metrics['diagnosticWordVerified'])} | {display(metrics['diagnosticWordAgreementAccuracy'])} |")
    lines += ['',
              'Separate diagnostics never count as completed or SAFE verification. Legacy does not measure the challenge word. '
              'Unknown SAFE ground truth is excluded from incorrect-SAFE rates. Missing evidence has null metrics, never invented success.', '',
              'Model/configuration versions, per-stage timings, denominators and component diagnostics are in results.json. '
              'No raw media, embeddings, credentials, OTPs or local dataset paths appear in these reports.']
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repetitions', type=int, default=1)
    parser.add_argument('--probes', action='store_true', help='Independent Speak/word diagnostics, excluded from acceptance')
    args = parser.parse_args()
    report = run_dataset(args.manifest, repetitions=args.repetitions, probes=args.probes)
    write_report(report, args.output)
    print(f"Compared {report['uniqueCases']} cases; {len(report['results'])} profile runs; originals preserved.")


if __name__ == '__main__':
    main()
