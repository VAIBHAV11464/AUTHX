"""Bounded presentation of server evidence; certificate summaries are issued snapshots."""
from app.services.decision_evidence import GATE_VERSION, evaluate_gates, number, object_json, stored_decision
from app.services.session_lifecycle import expired

CHECK_LABELS = {
    'lookCapture': 'Look capture', 'speakCapture': 'Speak capture',
    'lookIdentity': 'Look identity', 'speakIdentity': 'Speak identity',
    'blink': 'Blink cycle', 'flash': 'Flash measured', 'word': 'Challenge word', 'lips': 'Lip evidence',
}
GATE_CONFIG_KEYS = ('V2_FRAME_MIN_COUNT', 'V2_FACE_QUALITY_MIN_RATIO', 'V2_LIP_MIN_SAMPLES',
                    'V2_LANDMARK_MIN_RATIO', 'V2_FLASH_MIN_SAMPLES', 'V2_FLASH_MIN_SPAN_MS',
                    'V2_LANDMARK_MAX_GAP_MS', 'identityMinimum')
DECISION_CONFIG_KEYS = ('WEIGHT_FACE', 'WEIGHT_BLINK', 'WEIGHT_VOICE', 'VOICE_ACOUSTIC', 'VOICE_LIP',
                        'SAFE_MIN', 'SUSPICIOUS_MIN', 'FACE_SAFE_CAP', 'FACE_CAP_TRUST', 'COSINE_MATCH')


def _config(value, keys):
    value = object_json(value)
    return {key: value[key] for key in keys if number(value.get(key), 0, 1000000)}


def _text(value, limit=1000):
    return value[:limit] if isinstance(value, str) else None


def _speech(value, source):
    if not isinstance(value, dict):
        return None
    words = value.get('words')
    words = words[:16] if isinstance(words, list) else []
    return {'transcript': _text(value.get('transcript')), 'expectedWord': _text(value.get('expectedWord'), 64),
            'verified': value.get('wordVerified') is True, 'source': source,
            'confidence': value.get('matchedConfidence') if number(value.get('matchedConfidence'), 0, 1) else None,
            'minimumConfidence': value.get('minimumConfidence') if number(value.get('minimumConfidence'), .8, 1) else None,
            'words': [{'word': _text(word.get('word'), 64),
                       'confidence': word.get('confidence') if number(word.get('confidence'), 0, 1) else None}
                      for word in words if isinstance(word, dict)],
            **{key: _text(value.get(key), 128) for key in (
                'speechVersion', 'wordConfigVersion', 'voskVersion', 'speechModel', 'speechManifestSha256')}}


def _measurement(value):
    if not isinstance(value, dict):
        return None
    result = {key: _text(value.get(key), 128) for key in (
        'measurementVersion', 'mediapipeVersion', 'landmarkModelSha256', 'faceDetectorModel', 'faceIdentityModel')}
    for name in ('measurementConfig', 'qualityConfig'):
        cfg = value.get(name)
        result[name] = {str(key)[:64]: item for key, item in cfg.items()
                        if number(item, 0, 1000000)} if isinstance(cfg, dict) else {}
    return result


_UNSET = object()


def session_fields(session, result, *, override=_UNSET):
    """Read-only: display does not recalculate or rewrite a stored session label."""
    profile = session['verification_profile']
    retryable = not expired(session) and session['status'] == 'open' and (result is None or result['voice_score'] is None) and (
        profile == 'legacy' or session['speak_attempts'] < 4)
    if override is _UNSET:
        from app.models import get_active_override
        override = get_active_override(session)
    label_note = (f"Faculty override: {override['selectedLabel']} · {override['actorRole']} #{override['actorId']} · {override['createdAt']}. "
                  'Machine checks remain separate.') if override else (
                  'No recorded override for this attempt; historical label provenance may be unavailable.')
    if profile == 'legacy':
        return {'verificationVersion': 'legacy', 'retryable': retryable,
                'evidence': {'policyVersion': None, 'safeEligible': None, 'checks': [], 'speech': None,
                             'machineDecision': {'trustScore': session['machine_trust_score'], 'riskLabel': session['machine_risk_label']}
                             if session['machine_trust_score'] is not None else None,
                             'facultyOverride': override, 'measurements': {},
                             'summary': 'Legacy verification; v2 evidence checks were not required.',
                             'labelNote': label_note}}
    detail = object_json(result['detail_json'] if result is not None else None)
    machine = stored_decision(detail)
    eligibility = machine or evaluate_gates(detail, cosine=result['cosine'] if result else None,
                                          speak_cosine=result['speak_cosine'] if result else None,
                                          expected_word=session['challenge_word'])
    speech = _speech(detail.get('speech'), 'savedSpeak')
    last = object_json(session['speak_last_evidence'])
    if speech is None:
        speech = _speech(last.get('speech'), 'lastAttempt')
    checks = [{'key': key, 'label': label, 'status': eligibility['gates'][key]}
              for key, label in CHECK_LABELS.items()]
    lines = [f"{check['label']}: {check['status'].replace('_', ' ')}" for check in checks]
    evidence = {'policyVersion': GATE_VERSION, 'safeEligible': eligibility['safeEligible'], 'checks': checks,
                'summary': ' · '.join(lines), 'speech': speech, 'lastSpeakReason': _text(last.get('reason'), 64),
                'machineDecision': {key: machine.get(key) for key in ('trustScore', 'riskLabel', 'base', 'flashAdjust')}
                if machine else None,
                'measurements': {'look': _measurement(detail.get('lookMeasurement')),
                                 'speak': _measurement(detail.get('speakMeasurement'))},
                'gateConfig': {step: _config(object_json(detail.get(name)).get('config'), GATE_CONFIG_KEYS) for step, name in (
                    ('look', 'lookGateEvidence'), ('speak', 'speakGateEvidence'))},
                'decisionConfig': _config(machine.get('config'), DECISION_CONFIG_KEYS) | {
                    'FLASH_ADJUST': {str(key): value for key, value in object_json(machine['config'].get('FLASH_ADJUST')).items()
                                     if str(key) in ('90', '60', '50', '25') and number(value, -100, 100)}} if machine else None,
                'facultyOverride': override, 'labelNote': label_note}
    return {'verificationVersion': 'v2', 'evidence': evidence, 'retryable': retryable}


def certificate_fields(record):
    """Use only immutable score_json; never look up mutable current-session measurements."""
    record = object_json(record)
    evidence = record.get('evidence')
    if record.get('verificationVersion') == 'v2' and isinstance(evidence, dict):
        return {'verificationVersion': 'v2', 'evidence': evidence, 'retryable': False}
    return {'verificationVersion': 'not_recorded', 'retryable': False,
            'evidence': {'summary': 'Evidence snapshot not recorded for this historical or legacy certificate.',
                         'checks': [], 'speech': None, 'machineDecision': None, 'measurements': {},
                         'labelNote': 'This view retains the issued label and scores.'}}


def display_lines(fields):
    """Shared readable content for Jinja and JSON clients; strings must be escaped by views."""
    evidence = fields['evidence']
    lines = [f"Verification: {fields['verificationVersion']}", evidence.get('summary', '')]
    speech = evidence.get('speech')
    if isinstance(speech, dict):
        transcript = speech.get('transcript') or '(no word heard)'
        confidence = speech.get('confidence')
        if confidence is None:
            words = speech.get('words') or []
            confidence = words[0].get('confidence') if len(words) == 1 else None
        conf = f'{confidence:.2f}' if number(confidence, 0, 1) else 'not recorded'
        lines.append(f"{'Last word attempt' if speech.get('source') == 'lastAttempt' else 'Word'}: {transcript} · confidence {conf}")
    machine = evidence.get('machineDecision')
    lines.append(f"Machine decision: {machine['trustScore']} {machine['riskLabel']}" if isinstance(machine, dict)
                 else 'Machine decision snapshot: not recorded.')
    lines.append(evidence.get('labelNote', ''))
    return [line for line in lines if line]
