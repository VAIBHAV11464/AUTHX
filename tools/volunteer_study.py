"""Private volunteer registry, pre-run freeze, held-out analysis and retain-legacy gate.

Declarations and private signed records must be reviewed by the operator. This tool
cannot obtain consent, authenticate a human, or turn fixture data into human evidence.
"""
import argparse
import base64
from collections import Counter, defaultdict
from datetime import datetime, timezone
from importlib.metadata import distributions
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import Config
from tools import comparison as harness

VERSION = 'authx-volunteer-study-1'
FREEZE_VERSION = 'authx-volunteer-freeze-1'
CATEGORIES = ('genuine', 'wrong_person', 'wrong_word', 'photo', 'screen_replay')
LIGHTING = ('normal', 'dim')
ATTEMPT_UNIT = 'fresh_server_session_with_up_to_four_speak_submissions'
TIMING_SCOPE = 'sum_look_speak_trust_certificate_route_seconds_per_fresh_session'
TIMING_POPULATION = 'all_predeclared_genuine_evaluation_session_attempts'
LIMITATION = ('The paired harness holds one common enrollment vector fixed. It does not compare '
              'legacy single-image against v2 five-image enrollment; original v2 enrollment collection is reported separately.')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON value')))


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, allow_nan=False)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(value):
    require(isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value), 'Invalid SHA256')
    return value


def private_path(base, name):
    require(isinstance(name, str) and name and not Path(name).is_absolute(), 'Private references must be relative')
    path = (base / name).resolve()
    require(path.is_relative_to(base.resolve()) and path.is_file(), 'Missing private reference or outside study directory')
    return path


def runtime_fingerprint():
    # No username, host name, serial number, IP or dataset pathname is exported.
    return harness.digest(harness.canonical({'system': platform.system(), 'release': platform.release(),
        'machine': platform.machine(), 'processor': platform.processor(), 'python': platform.python_version()}))


def source_inventory():
    files = {p for folder in ('app', 'tools') for p in (ROOT / folder).rglob('*')
             if p.is_file() and p.suffix in ('.py', '.js', '.html', '.css') and '__pycache__' not in p.parts}
    files.add(ROOT / 'config.py')
    return {p.relative_to(ROOT).as_posix(): harness.digest(p.read_bytes()) for p in sorted(files)}


def config_inventory():
    names = [key for key in vars(Config) if key.startswith('V2_')]
    names += ['COSINE_MATCH', 'WEIGHT_FACE', 'WEIGHT_BLINK', 'WEIGHT_VOICE', 'VOICE_ACOUSTIC', 'VOICE_LIP',
              'SAFE_MIN', 'SUSPICIOUS_MIN', 'FLASH_ADJUST', 'FLASH_DURATION_MS', 'CHALLENGE_WORDS',
              'FLASH_START_MIN_MS', 'FLASH_START_MAX_MS', 'MAX_CONTENT_LENGTH', 'FRAME_LONG_SIDE', 'JPEG_QUALITY']
    # Canonical JSON normalizes tuple values and integer keys consistently.
    return json.loads(harness.canonical({key: getattr(Config, key) for key in sorted(names)}))


def study_template():
    return {'schemaVersion': VERSION, 'studyId': 'authx-volunteers', 'datasetManifest': None,
        'protocol': {'attemptUnit': ATTEMPT_UNIT, 'maxSessionAttempts': 2, 'maxSpeakSubmissions': 4,
                     'timingScope': TIMING_SCOPE, 'declaredBeforeCollection': False,
                     'timingPopulation': TIMING_POPULATION,
                     'groundTruthMethod': 'operator_recorded_conditions_before_scoring',
                     'thresholdTuningPerformed': False},
        'referenceLaptop': {'id': None, 'specification': None, 'confirmedThisMachine': False,
                            'runtimeFingerprintSha256': None},
        'cameras': [], 'subjects': [], 'plannedTrials': [], 'cases': [],
        'notes': 'Template only. No consent obtained, volunteers recorded, or reference laptop confirmed.'}


def declared_word_truth(trial):
    default = True if trial['category'] in ('genuine', 'wrong_person') else False if trial['category'] == 'wrong_word' else None
    value = trial.get('wordMatch', default)
    require(value is None or type(value) is bool, 'Independently declared word truth must be boolean or null')
    if trial['category'] in ('genuine', 'wrong_person', 'wrong_word'):
        require(value is default, 'Word truth contradicts the declared genuine/wrong-person/wrong-word condition')
    return value


def plan(path, output, *, declare_protocol=False):
    info = load_study(path, dataset_required=False)
    require(Path(output).resolve().parent == info['path'].parent, 'Keep planned registry beside private consent records')
    require(not info['cases'] and not info['trials'], 'Planning must precede collection; choose an untouched registry')
    require(len(info['cameras']) == 2 and len(info['subjects']) >= 10, 'Plan requires two cameras and at least ten reviewed consenting volunteers')
    require(declare_protocol, 'Review and explicitly declare the protocol before planning collection')
    value = info['study']
    trials = []
    for split in ('tuning', 'evaluation'):
        ids = sorted(sid for sid, row in info['subjects'].items() if row['split'] == split)
        if not ids:
            continue
        require(len(ids) >= 2, 'Each collected split needs at least two separate wrong-person source identities')
        for index, sid in enumerate(ids):
            for camera in info['cameras']:
                for light in LIGHTING:
                    for category in CATEGORIES:
                        trials.append({'id': f'T{len(trials)+1:04}', 'subjectId': sid, 'cameraId': camera,
                            'lighting': light, 'category': category, 'split': split,
                            'wordMatch': True if category in ('genuine', 'wrong_person') else False if category == 'wrong_word' else None,
                            'sourceSubjectIds': [ids[(index+1) % len(ids)]] if category == 'wrong_person' else [sid]})
    value.update(plannedTrials=trials, notes='Predeclared collection matrix. No recordings or human results yet.')
    value['protocol'].update(declaredBeforeCollection=True, declaredAt=datetime.now(timezone.utc).isoformat())
    write_json(output, value)
    return value


def load_study(path, *, dataset_required=True):
    path = Path(path).resolve()
    study = read_json(path)
    require(study.get('schemaVersion') == VERSION, 'Unsupported volunteer study version')
    harness.identifier(study.get('studyId'))
    protocol = study.get('protocol', {})
    require(protocol.get('attemptUnit') == ATTEMPT_UNIT and protocol.get('maxSessionAttempts') == 2
            and protocol.get('maxSpeakSubmissions') == 4, 'Declare two fresh sessions and the real four-Speak policy')
    require(protocol.get('timingScope') == TIMING_SCOPE, 'Unsupported or undeclared latency boundary')
    require(protocol.get('timingPopulation') == TIMING_POPULATION, 'Declare complete genuine scoring benchmark population before collection')
    require(protocol.get('groundTruthMethod') == 'operator_recorded_conditions_before_scoring', 'Ground truth must precede scoring')
    require(isinstance(protocol.get('thresholdTuningPerformed'), bool), 'Declare threshold tuning')
    subjects, identities, private_hashes = {}, set(), {}
    for row in study.get('subjects', []):
        sid = harness.identifier(row.get('id'))
        require(sid not in subjects, 'Duplicate anonymous subject')
        require(row.get('split') in ('tuning', 'evaluation'), 'Subject needs an immutable tuning/evaluation split')
        identity = sha(row.get('identityKeySha256'))
        require(identity not in identities, 'Aliased identity is not a held-out subject')
        identities.add(identity)
        require(row.get('consentReviewed') is True and row.get('withdrawn') is False, 'Missing reviewed consent or withdrawn subject')
        consent = private_path(path.parent, row.get('consentDocument'))
        require(harness.digest(consent.read_bytes()) == sha(row.get('consentSha256')), 'Private consent record changed')
        try:
            signed = datetime.fromisoformat(row['consentRecordedAt'])
        except (KeyError, TypeError, ValueError):
            raise ValueError('Consent time is required') from None
        require(signed.tzinfo is not None and signed.utcoffset().total_seconds() == 0, 'Consent time must be UTC')
        require(row.get('recordingPermitted') is True, 'Recording permission missing')
        subjects[sid] = row
        private_hashes['consent/' + sid] = row['consentSha256']
    cameras = {}
    for row in study.get('cameras', []):
        cid = harness.identifier(row.get('id'))
        require(cid not in cameras and isinstance(row.get('description'), str) and row['description'].strip(), 'Duplicate/missing camera description')
        key = sha(row.get('deviceKeySha256'))
        require(key not in {c['deviceKeySha256'] for c in cameras.values()}, 'Two labels for the same camera do not count as two cameras')
        cameras[cid] = row
    trials = {}
    for row in study.get('plannedTrials', []):
        tid = harness.identifier(row.get('id'))
        require(tid not in trials, 'Duplicate planned trial')
        require(row.get('subjectId') in subjects and row.get('cameraId') in cameras, 'Unknown trial subject or camera')
        require(row.get('lighting') in LIGHTING and row.get('category') in CATEGORIES, 'Unknown study condition')
        declared_word_truth(row)
        require(row.get('split') == subjects[row['subjectId']]['split'], 'Trial split differs from subject registry')
        trials[tid] = row
    dataset = None
    if study.get('datasetManifest'):
        manifest = private_path(path.parent, study['datasetManifest'])
        dataset = harness.load_dataset(manifest)
    elif dataset_required:
        raise ValueError('No volunteer dataset manifest supplied')
    cases, trial_attempts, media_owners = {}, defaultdict(set), {}
    prepared = {c.case_id: c for c in dataset['cases']} if dataset else {}
    current_source = source_inventory() if study.get('cases') else {}
    expected_scoring_source = {k: v for k, v in current_source.items() if k.startswith('app/') or k == 'config.py'}
    expected_config = config_inventory()
    expected_protected = harness.original_inventory()['fileHashes'] if study.get('cases') else {}
    for row in study.get('cases', []):
        cid = harness.identifier(row.get('caseId'))
        require(cid not in cases and cid in prepared, 'Duplicate or unknown study case')
        case = prepared[cid]
        tid = row.get('trialId')
        require(tid in trials, 'Case must belong to a predeclared trial')
        trial = trials[tid]
        number = row.get('sessionAttempt')
        require(type(number) is int and 1 <= number <= 2 and number not in trial_attempts[tid], 'Two distinct ordered server sessions maximum')
        trial_attempts[tid].add(number)
        require(row.get('enrollmentSubjectId') == trial['subjectId'], 'Enrollment identity must match primary trial identity')
        sources = row.get('sourceSubjectIds')
        require(isinstance(sources, list) and sources and len(set(sources)) == len(sources), 'All attack/capture source identities are required')
        ids = {row['enrollmentSubjectId'], *sources}
        require(all(s in subjects and subjects[s]['split'] == trial['split'] for s in ids), 'Subject leakage across enrollment, attack source or capture split')
        if trial['category'] == 'wrong_person':
            require(any(s != row['enrollmentSubjectId'] for s in sources), 'Wrong-person source must include a different consenting person')
        elif trial['category'] in ('genuine', 'wrong_word'):
            require(ids == {trial['subjectId']}, 'Genuine/wrong-word trial must use its enrolled person')
        if trial['category'] in ('photo', 'screen_replay'):
            require(all(subjects[s].get('replayPermitted') is True for s in sources), 'Photo/replay source permission missing')
        require(case.fixture_category == 'consented' and case.timing_provenance == 'captured_sample_clock'
                and case.split == trial['split'], 'Fixtures, synthetic timing and case/subject split mismatch cannot validate v2')
        require(case.truth['category'] == trial['category'] and case.truth['safeExpected'] is (trial['category'] == 'genuine')
                and case.truth['wordMatch'] is declared_word_truth(trial), 'Predeclared truth differs from manifest truth')
        require(row.get('authenticity') == 'original_browser_uploads' and row.get('terminalOutcomeRecorded') is True,
                'Original capture provenance and an explicit terminal outcome are required')
        ledger = private_path(path.parent, row.get('captureLedger'))
        require(harness.digest(ledger.read_bytes()) == sha(row.get('captureLedgerSha256')), 'Original capture ledger changed')
        require(case.input_hash == sha(row.get('originalInputSha256')), 'Original input fingerprint differs')
        captured = read_json(ledger)
        require(captured.get('schemaVersion') == 'authx-private-capture-1'
                and captured.get('studyId') == study['studyId'] and captured.get('trialId') == tid
                and captured.get('terminalOutcomeRecorded') is True and captured.get('trial') == trial,
                'Capture ledger conditions differ from predeclared study trial')
        protocol_pin = private_path(ledger.parent, 'protocol-freeze.json')
        require(harness.digest(protocol_pin.read_bytes()) == sha(captured.get('protocolFreezeSha256')), 'Precollection protocol freeze changed')
        pin = read_json(protocol_pin)
        require(pin.get('phase') == 'before_collection' and pin.get('schemaVersion') == FREEZE_VERSION
                and pin.get('inventory', {}).get('studySha256') == captured.get('studySha256BeforeCapture')
                and pin['inventory'].get('source') == captured.get('sourceBeforeCapture')
                and pin['inventory'].get('config') == captured.get('configBeforeCapture')
                and pin['inventory'].get('protected', {}).get('fileHashes') == captured.get('protectedBeforeCapture'),
                'Capture is not bound to its original precollection source/config/protocol pin')
        require(all(pin['inventory']['privateRecordSha256'].get('consent/' + s) == subjects[s]['consentSha256'] for s in ids),
                'Source/enrollment consent differs from precollection pin')
        require(captured.get('cameraDeviceKeySha256') == cameras[trial['cameraId']]['deviceKeySha256'], 'Original selected camera differs from registry')
        if trial['split'] == 'evaluation':
            capture_source = {k: v for k, v in captured.get('sourceBeforeCapture', {}).items() if k.startswith('app/') or k == 'config.py'}
            require(capture_source == expected_scoring_source and captured.get('configBeforeCapture') == expected_config
                    and captured.get('protectedBeforeCapture') == expected_protected,
                    'Evaluation captures predate a scoring/model/config change; collect fresh untouched evaluation after tuning')
        enrollment = captured.get('enrollment') or {}
        require(enrollment.get('method') == 'v2_five_image' and enrollment.get('ok') is True
                and enrollment.get('subjectId') == trial['subjectId'], 'Actual v2 enrollment path has not been captured')
        common = dataset['enrollments'][case.enrollment_id]
        require(common['method'] == 'existing_embedding'
                and harness.digest(common['blob']) == sha(enrollment.get('embeddingSha256')), 'Common enrollment differs from actual captured enrollment')
        enroll_raw = private_path(ledger.parent, enrollment.get('upload')).read_bytes()
        enroll_event = next((e for e in captured.get('events', []) if e.get('upload') == enrollment['upload']), {})
        require(harness.digest(enroll_raw) == enroll_event.get('uploadSha256'), 'Original enrollment upload changed')
        require(len(json.loads(enroll_raw).get('images', [])) == 5, 'Original enrollment did not submit five images')
        try:
            acknowledged = datetime.fromisoformat(captured['consentAcknowledgedAt'])
            ended = datetime.fromisoformat(captured['endedAt'])
            require(acknowledged.tzinfo is not None and ended >= acknowledged, 'Invalid original consent/collection times')
            require(all(datetime.fromisoformat(subjects[s]['consentRecordedAt']) <= acknowledged for s in ids),
                    'Consent was recorded after collection started')
        except (KeyError, TypeError, ValueError):
            raise ValueError('Consent and terminal collection times must precede/be consistent with capture') from None
        sessions = [s for s in captured.get('sessions', []) if s.get('sessionAttempt') == number]
        require(len(sessions) == 1 and sessions[0].get('word') == case.expected_word
                and sessions[0].get('flashStartMs') == case.flash_start_ms
                and sessions[0].get('verificationProfile') == 'v2', 'Original server challenge/flash/session provenance differs')
        original_events = [e for e in captured.get('events', [])
                           if e.get('sessionId') == sessions[0]['id'] and e.get('stage') in ('look', 'speak')]
        require(len(original_events) == len(case.attempts), 'Original submission sequence changed')
        for original, event in zip(original_events, case.attempts):
            raw = private_path(ledger.parent, original.get('upload')).read_bytes()
            require(harness.digest(raw) == original.get('uploadSha256'), 'Original upload JSON bytes changed')
            payload = json.loads(raw)
            from tools.comparison_import import blob
            normalized = {'frames': [{'tMs': f.get('tMs'), 'image': base64.b64encode(blob(f['image'])).decode('ascii')}
                                     for f in payload['frames']]}
            if original['stage'] == 'speak':
                normalized.update(wav=base64.b64encode(blob(payload['wav'])).decode('ascii'),
                                  audioStartMs=payload.get('audioStartMs', 0))
            require(original['stage'] == event.get('stage') and normalized == event.get('payload'),
                    'Prepared media/timestamps/audio offset differ from original browser upload')
        private_hashes['capture/' + cid] = row['captureLedgerSha256']
        # Distinct recording IDs map to original submission fingerprints. A saved
        # Look can be reused inside a session; Speak retries require fresh media.
        recordings = row.get('recordings')
        require(isinstance(recordings, list) and len(recordings) == len(case.attempts), 'Every original submission needs a recording identity')
        require(all('stage' in event for event in case.attempts), 'Study requires exact original submission sequence')
        speak_count = 0
        for record, event in zip(recordings, case.attempts):
            rid = harness.identifier(record.get('id'))
            require(record.get('stage') == event['stage'], 'Recording stage mismatch')
            media_hash = harness.digest(harness.canonical(event['payload']))
            require(record.get('sha256') == media_hash, 'Recording hash mismatch')
            for key in ('id/' + rid, 'bytes/' + media_hash):
                require(key not in media_owners, 'Reused recording is not an independent human submission')
                media_owners[key] = cid
            speak_count += event['stage'] == 'speak'
        require(speak_count <= 4, 'Original capture exceeds four Speak submissions')
        cases[cid] = row
    require(not dataset or set(prepared) == set(cases), 'Every dataset case must be registered; demo/tuning cannot sneak into evaluation')
    require(all(numbers == set(range(1, max(numbers)+1)) for numbers in trial_attempts.values()), 'Missing first authentic session attempt')
    return {'path': path, 'study': study, 'dataset': dataset, 'subjects': subjects, 'cameras': cameras,
            'trials': trials, 'cases': cases, 'privateHashes': private_hashes}


def validation(info):
    study, subjects, trials = info['study'], info['subjects'], info['trials']
    reasons = []
    if len(subjects) < 10:
        reasons.append('Fewer than ten consenting unique volunteers')
    if len(info['cameras']) != 2:
        reasons.append('Exactly two distinct declared cameras are required by this study protocol')
    if study['protocol'].get('declaredBeforeCollection') is not True:
        reasons.append('Protocol, attempt unit and latency boundary have not been declared before collection')
    evaluation = {sid for sid, s in subjects.items() if s['split'] == 'evaluation'}
    if not evaluation:
        reasons.append('No held-out evaluation volunteers')
    if study['protocol']['thresholdTuningPerformed'] and not any(s['split'] == 'tuning' for s in subjects.values()):
        reasons.append('Tuning declared without separate tuning volunteers')
    required = {(sid, cam, light, cat) for sid in evaluation for cam in info['cameras'] for light in LIGHTING for cat in CATEGORIES}
    planned = {(r['subjectId'], r['cameraId'], r['lighting'], r['category']) for r in trials.values() if r['split'] == 'evaluation'}
    if not required or not required <= planned:
        reasons.append('Held-out subject/camera/lighting/attack matrix is incomplete')
    observed = {r['trialId'] for r in info['cases'].values()}
    missing = [tid for tid, r in trials.items() if r['split'] == 'evaluation' and tid not in observed]
    if missing or not observed:
        reasons.append('Predeclared evaluation trials have missing recordings or outcomes')
    laptop = study.get('referenceLaptop', {})
    laptop_ok = (isinstance(laptop.get('id'), str) and isinstance(laptop.get('specification'), str)
                 and bool(laptop.get('specification', '').strip()) and laptop.get('confirmedThisMachine') is True
                 and laptop.get('runtimeFingerprintSha256') == runtime_fingerprint())
    if not laptop_ok:
        reasons.append('Reference laptop has not been identified and confirmed on this runtime')
    return {'readyForValidation': not reasons, 'reasons': reasons, 'consentingUniqueVolunteers': len(subjects),
            'tuningVolunteers': sum(s['split'] == 'tuning' for s in subjects.values()),
            'evaluationVolunteers': len(evaluation), 'distinctCameras': len(info['cameras']),
            'plannedEvaluationTrials': sum(r['split'] == 'evaluation' for r in trials.values()),
            'missingEvaluationTrials': len(missing), 'registeredSessionAttempts': len(info['cases']),
            'uniqueRecordings': sum(len(r['recordings']) for r in info['cases'].values()), 'referenceLaptopConfirmed': laptop_ok}


def freeze_inventory(info):
    return {'studySha256': harness.digest(info['path'].read_bytes()),
            'datasetManifestSha256': info['dataset']['manifestSha256'] if info['dataset'] else None,
            'inputSha256': {c.case_id: c.input_hash for c in info['dataset']['cases']} if info['dataset'] else {},
            'privateRecordSha256': info['privateHashes'], 'source': source_inventory(), 'config': config_inventory(),
            'protected': harness.original_inventory(), 'runtimeFingerprintSha256': runtime_fingerprint(),
            'dependencies': {d.metadata['Name']: d.version for d in sorted(distributions(), key=lambda d: d.metadata['Name'])}}


def freeze(path, output):
    info = load_study(path)
    require(info['study']['protocol'].get('declaredBeforeCollection') is True, 'Declare protocol before freezing evaluation')
    value = {'schemaVersion': FREEZE_VERSION, 'createdAt': datetime.now(timezone.utc).isoformat(),
             'inventory': freeze_inventory(info), 'readiness': validation(info)}
    write_json(output, value)
    return value


def freeze_protocol(path, output):
    info = load_study(path, dataset_required=False)
    require(info['study']['protocol'].get('declaredBeforeCollection') is True and info['trials']
            and not info['cases'] and not info['dataset'], 'Pin collection protocol before any captures are attached')
    value = {'schemaVersion': FREEZE_VERSION, 'phase': 'before_collection',
             'createdAt': datetime.now(timezone.utc).isoformat(), 'inventory': freeze_inventory(info)}
    write_json(output, value)
    return value


def assert_frozen(info, frozen):
    require(frozen.get('schemaVersion') == FREEZE_VERSION and frozen.get('inventory') == freeze_inventory(info),
            'Source/config/models/dependencies/consent/splits/truth/media changed since pre-run freeze; fresh evaluation required')


def metrics(rows):
    genuine = [r for r in rows if r['category'] == 'genuine']
    negatives = [r for r in rows if r['category'] in ('wrong_person', 'wrong_word')]
    words = [(w, r['wordMatch']) for r in rows if r['wordMatch'] is not None
             for result in r['sessions'] for w in result['wordAttempts']]
    measured_words = [w for r in rows for result in r['sessions'] for w in result['wordAttempts']]
    latency = [r['scoringSeconds'] for r in rows if r['scoringSeconds'] is not None]
    return {'trials': len(rows), 'genuineCompletionWithinTwo': harness.rate(sum(r['completedWithinTwo'] for r in genuine), len(genuine), 'No held-out genuine trials'),
            'genuineSafeCompletionWithinTwo': harness.rate(sum(r['safeWithinTwo'] for r in genuine), len(genuine), 'No held-out genuine trials'),
            'incorrectMachineSafe': harness.rate(sum(r['machineSafe'] for r in negatives), len(negatives), 'No held-out wrong-person/wrong-word trials'),
            'allCategoryMachineSafe': harness.rate(sum(r['machineSafe'] for r in rows), len(rows), 'No observed trials'),
            'allCategoryCertificateCompletion': harness.rate(sum(r['completedWithinTwo'] for r in rows), len(rows), 'No observed trials'),
            'allCategorySafeCompletion': harness.rate(sum(r['safeWithinTwo'] for r in rows), len(rows), 'No observed trials'),
            'retryTrials': harness.rate(sum(r['retry'] for r in rows), len(rows), 'No observed trials'),
            'wordAgreement': harness.rate(sum(w['exactTokenMatch'] == truth for w, truth in words), len(words), 'No measured full-flow word agreement'),
            'wordVerified': harness.rate(sum(w['wordVerified'] for w in measured_words), len(measured_words), 'No full-flow word verification'),
            'terminalProcessingTiming': harness.timing(latency)}


def analyze(info, report=None, *, freeze_sha256=None):
    readiness = validation(info)
    require(report is None or report.get('repetitions') == 1, 'Repeat measurements cannot inflate volunteer denominators')
    if report:
        require(report['datasetManifestSha256'] == info['dataset']['manifestSha256'], 'Report dataset differs from frozen study')
    by_case, observed = {}, []
    for row in report['results'] if report else []:
        key = row['caseId'], row['profile']
        require(key not in by_case and row['caseId'] in info['cases'] and row['profile'] in harness.PROFILES and row['repetition'] == 1,
                'Duplicate, unregistered or repeated case result')
        require(row['inputSha256'] == info['cases'][row['caseId']]['originalInputSha256'], 'Measured input differs from study')
        original = next(c for c in info['dataset']['cases'] if c.case_id == row['caseId'])
        require(row.get('groundTruth') == original.truth and row.get('split') == original.split
                and row.get('fixtureCategory') == original.fixture_category and row.get('timingProvenance') == original.timing_provenance,
                'Measured truth/split/provenance differs from frozen dataset')
        require(all(harness.finite(s.get('seconds')) and s['seconds'] >= 0 for s in row['stages']), 'Invalid measured route time')
        by_case[key] = row
    if report:
        require(set(by_case) == {(cid, p) for cid in info['cases'] for p in harness.PROFILES}, 'Missing paired profile outcomes')
    profile_metrics, grouped, latency_metrics = {}, {}, {}
    for profile in harness.PROFILES:
        trial_rows, all_sessions = [], []
        for tid, trial in info['trials'].items():
            if trial['split'] != 'evaluation':
                continue
            refs = sorted((r for r in info['cases'].values() if r['trialId'] == tid), key=lambda r: r['sessionAttempt'])
            sessions = [by_case[(ref['caseId'], profile)] for ref in refs if (ref['caseId'], profile) in by_case]
            if not sessions:
                continue
            all_sessions.extend(sessions)
            scoring = [sum(s['seconds'] for s in r['stages'] if s['stage'] in ('look', 'speak', 'trust', 'certificate')) for r in sessions]
            item = {'trialId': tid, **{k: trial[k] for k in ('subjectId', 'cameraId', 'lighting', 'category')},
                'wordMatch': declared_word_truth(trial), 'profile': profile, 'sessions': sessions,
                'completedWithinTwo': any(r['completed'] for r in sessions),
                'safeWithinTwo': any(r['acceptedSafe'] for r in sessions),
                'machineSafe': any(r['machineRiskLabel'] == 'SAFE' for r in sessions),
                'retry': len(sessions) > 1 or any(r['retryRequested'] for r in sessions),
                'scoringSeconds': sum(scoring) if scoring and all(r['stages'] for r in sessions) else None}
            trial_rows.append(item)
            observed.append({k: v for k, v in item.items() if k != 'sessions'})
        profile_metrics[profile] = metrics(trial_rows)
        groups = {}
        for dimension in ('subjectId', 'cameraId', 'lighting', 'category'):
            groups[dimension] = {value: metrics([r for r in trial_rows if r[dimension] == value])
                                 for value in sorted({r[dimension] for r in trial_rows})}
        groups['matrix'] = [{**{k: r[k] for k in ('trialId', 'subjectId', 'cameraId', 'lighting', 'category')},
                            **metrics([r])} for r in trial_rows]
        grouped[profile] = groups
        # Partial rejections remain in observed terminal timings, but cannot
        # establish the eight-second *complete scoring* target. Denominators
        # retain every attempted session, and unavailable samples stay null.
        complete, partial = [], 0
        benchmark_sessions = [r for r in all_sessions if r['groundTruth']['category'] == 'genuine']
        for row in benchmark_sessions:
            stages = row['stages']
            if row['completed'] and all(any(s['stage'] == name and s['ok'] for s in stages) for name in ('look', 'speak', 'trust', 'certificate')):
                complete.append(sum(s['seconds'] for s in stages if s['stage'] in ('look', 'speak', 'trust', 'certificate')))
            else:
                partial += 1
        metric = harness.rate(sum(v <= 8 for v in complete), len(benchmark_sessions), 'No reference-laptop scoring attempts')
        if partial or not readiness['referenceLaptopConfirmed']:
            metric.update(rate=None, unavailableReason='Incomplete scoring scope or unconfirmed reference laptop')
        metric.update(completeTiming=harness.timing(complete), partialFailureSamples=partial,
                      scope=TIMING_SCOPE, population=TIMING_POPULATION, distinctSessionAttempts=len(benchmark_sessions),
                      allCategorySessionAttempts=len(all_sessions))
        latency_metrics[profile] = metric
    v2 = profile_metrics['v2']
    reasons = list(readiness['reasons'])
    checks = {}
    criteria = {'genuineCompletionWithinTwo': (v2['genuineCompletionWithinTwo'], lambda r: r >= .9),
                'zeroHeldOutWrongPersonWrongWordSafe': (v2['incorrectMachineSafe'], lambda r: r == 0),
                'referenceLaptop95PercentWithinEightSeconds': (latency_metrics['v2'], lambda r: r >= .95)}
    for name, (value, predicate) in criteria.items():
        status = 'unavailable' if value['rate'] is None else 'passed' if predicate(value['rate']) else 'failed'
        checks[name] = {'status': status, **value}
        if status != 'passed':
            reasons.append(name + ': ' + status)
    # Require both named attack categories and report replay/photo coverage;
    # a zero wrong-word denominator is not a pass from pooled negatives.
    for category in CATEGORIES:
        if not any(r['category'] == category and r['profile'] == 'v2' for r in observed):
            reasons.append('No held-out ' + category + ' outcomes')
    if not freeze_sha256:
        reasons.append('No verified pre-run source/config/ground-truth/split freeze')
    eligible = not reasons
    enrollment_records, collection_samples = {}, defaultdict(Counter)
    for cid, ref in info['cases'].items():
        trial = info['trials'][ref['trialId']]
        collection_samples[trial['split']]['sessionAttempts'] += 1
        collection_samples[trial['split']]['recordings'] += len(ref['recordings'])
        collection_samples[trial['split']][trial['category']] += 1
        ledger_path = private_path(info['path'].parent, ref['captureLedger'])
        captured = read_json(ledger_path)
        enroll_events = [e for e in captured['events'] if e['stage'] == 'enroll']
        enrollment_records.setdefault(ref['captureLedgerSha256'], {'trialId': ref['trialId'],
            'subjectId': trial['subjectId'], 'cameraId': trial['cameraId'], 'lighting': trial['lighting'], 'split': trial['split'],
            'method': 'v2_five_image', 'submissions': len(enroll_events),
            'successfulSubmissions': sum(e['ok'] for e in enroll_events),
            'failedSubmissions': sum(not e['ok'] for e in enroll_events),
            'reasons': [e['reason'] for e in enroll_events if not e['ok']]})
    return {'schemaVersion': 'authx-v2-readiness-1', 'studyId': info['study']['studyId'],
        'createdAt': datetime.now(timezone.utc).isoformat(), 'decision': 'eligible_for_v2' if eligible else 'retain_legacy',
        'defaultProfile': 'legacy', 'defaultChanged': False, 'task23HumanEvaluationComplete': bool(report and readiness['readyForValidation']),
        'evidenceStatus': 'observed' if report else 'pending_actual_consented_recordings', 'reasons': reasons,
        'samples': readiness, 'criteria': checks, 'heldOutProfiles': profile_metrics, 'latency': latency_metrics,
        'groups': grouped, 'anonymousOutcomes': observed, 'freezeSha256': freeze_sha256,
        'collectedSamplesBySplit': {key: dict(value) for key, value in collection_samples.items()},
        'actualEnrollmentCollection': list(enrollment_records.values()),
        'pairedEnrollmentLimitation': LIMITATION,
        'consentMeaning': 'Operator declaration and reviewed private document; software does not obtain consent.',
        'latencyMeaning': 'Predeclared full-scoring benchmark uses every genuine held-out session attempt, including failures as unavailable samples. '
                          'Partial and attack rejection times are separate diagnostics; neither can prove the complete eight-second scoring target.',
        'splitCounts': dict(Counter(s['split'] for s in info['subjects'].values())),
        'repeatedMeasurementsIncluded': False, 'externalOutreach': False}


def write_decision(decision, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'readiness.json', decision)
    lines = ['# V2 readiness decision', '', decision['decision'], '',
             'Default remains legacy. Actual human evaluation: ' + decision['evidenceStatus'] + '.', '',
             f"Consenting volunteers: {decision['samples']['consentingUniqueVolunteers']}; held out: {decision['samples']['evaluationVolunteers']}; "
             f"recordings: {decision['samples']['uniqueRecordings']}; cameras: {decision['samples']['distinctCameras']}.", '',
             '| Criterion | Status | Observed numerator / denominator |', '| --- | --- | --- |']
    for name, value in decision['criteria'].items():
        lines.append(f"| {name} | {value['status']} | {value['numerator']} / {value['denominator']} |")
    lines.extend(['', *['- ' + reason for reason in decision['reasons']], '', decision['pairedEnrollmentLimitation'], '', decision['latencyMeaning']])
    (output / 'readiness.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def run_study(path, freeze_path, output):
    info, frozen = load_study(path), read_json(freeze_path)
    assert_frozen(info, frozen)
    output = Path(output)
    require(not output.exists(), 'Choose a fresh exclusive study output directory')
    report = harness.run_dataset(private_path(info['path'].parent, info['study']['datasetManifest']), repetitions=1, probes=False)
    assert_frozen(load_study(path), frozen)
    decision = analyze(info, report, freeze_sha256=harness.digest(Path(freeze_path).read_bytes()))
    harness.write_report(report, output)
    write_decision(decision, output / 'decision')
    return decision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init'); init.add_argument('--output', type=Path, required=True)
    validate = sub.add_parser('validate'); validate.add_argument('study', type=Path)
    matrix = sub.add_parser('plan'); matrix.add_argument('study', type=Path); matrix.add_argument('--output', type=Path, required=True)
    matrix.add_argument('--declare-protocol', action='store_true')
    pending = sub.add_parser('pending'); pending.add_argument('study', type=Path); pending.add_argument('--output', type=Path, required=True)
    pin = sub.add_parser('freeze'); pin.add_argument('study', type=Path); pin.add_argument('--output', type=Path, required=True)
    protocol_pin = sub.add_parser('pin-protocol'); protocol_pin.add_argument('study', type=Path); protocol_pin.add_argument('--output', type=Path, required=True)
    run = sub.add_parser('run'); run.add_argument('study', type=Path); run.add_argument('--freeze', type=Path, required=True); run.add_argument('--output', type=Path, required=True)
    sub.add_parser('runtime-fingerprint')
    args = parser.parse_args()
    if args.command == 'init':
        args.output.mkdir(parents=True, exist_ok=False)
        write_json(args.output / 'study.json', study_template())
        print('Created private empty template; no consent or captures declared.')
    elif args.command == 'runtime-fingerprint':
        print(runtime_fingerprint())
    elif args.command == 'plan':
        value = plan(args.study, args.output, declare_protocol=args.declare_protocol)
        print(f"Declared {len(value['plannedTrials'])} volunteer/camera/lighting/category trials before collection.")
    elif args.command == 'validate':
        result = validation(load_study(args.study, dataset_required=False))
        print(json.dumps(result, indent=2)); return 0 if result['readyForValidation'] else 2
    elif args.command == 'pending':
        write_decision(analyze(load_study(args.study, dataset_required=False)), args.output)
        print('Retain legacy: human evaluation remains pending.')
    elif args.command == 'freeze':
        freeze(args.study, args.output); print('Frozen private source/config/model/split/truth/media/consent inventory before scoring.')
    elif args.command == 'pin-protocol':
        freeze_protocol(args.study, args.output); print('Pinned private protocol/split/ground-truth/source/config/model inventory before collection.')
    else:
        result = run_study(args.study, args.freeze, args.output); print(result['decision'])
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ValueError as exc:
        # Validation errors are predefined messages; do not echo private paths.
        print(str(exc), file=sys.stderr); sys.exit(2)
