"""Server measurement records and strict v2 SAFE eligibility (no media storage)."""
import json
import math

from flask import current_app

from app.services.speech import stored_word_verified

GATE_VERSION = 'v2-decision-gates-1'


def object_json(value):
    try:
        parsed = json.loads(value or '{}') if isinstance(value, (str, type(None))) else value
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def number(value, low, high):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and low <= value <= high)


def count(value, minimum=0):
    return type(value) is int and minimum <= value <= 90


def identity_matches(cosine, minimum=None):
    threshold = max(.363, current_app.config['COSINE_MATCH']) if minimum is None else minimum
    return number(cosine, -1, 1) and number(threshold, .363, 1) and cosine >= threshold


def gate_config():
    cfg = current_app.config
    return {key: cfg[key] for key in (
        'V2_FRAME_MIN_COUNT', 'V2_FACE_QUALITY_MIN_RATIO', 'V2_LIP_MIN_SAMPLES',
        'V2_LANDMARK_MIN_RATIO', 'V2_FLASH_MIN_SAMPLES', 'V2_FLASH_MIN_SPAN_MS',
        'V2_LANDMARK_MAX_GAP_MS',
    )} | {'identityMinimum': max(.363, cfg['COSINE_MATCH'])}


def capture_evidence(frames, face, flash_start_ms=None, *, samples=None, rate=None, audio_start_ms=0):
    eligible = sum(1 for stamp, _ in frames if flash_start_ms is None or stamp < flash_start_ms)
    approved = face.get('approvedFrames')
    usable = len(approved) if isinstance(approved, list) else 0
    cfg = current_app.config
    stamps = [stamp for stamp, _ in frames]
    video_valid = (cfg['V2_FRAME_MIN_COUNT'] <= len(stamps) <= cfg['V2_FRAME_MAX_COUNT']
                   and all(number(stamp, 0, cfg['V2_CLIP_MAX_MS']) for stamp in stamps)
                   and stamps[0] <= cfg['V2_FIRST_FRAME_MAX_MS']
                   and all(b > a for a, b in zip(stamps, stamps[1:]))
                   and cfg['V2_CLIP_MIN_MS'] <= stamps[-1] - stamps[0] <= cfg['V2_CLIP_MAX_MS'])
    result = {'usable': face.get('ok') is True and usable >= max(
        cfg['V2_FRAME_MIN_COUNT'], math.ceil(eligible * cfg['V2_FACE_QUALITY_MIN_RATIO'])),
        'eligibleFrames': eligible, 'usableFrames': usable, 'videoValidated': video_valid,
        'frameCount': len(frames), 'firstFrameMs': stamps[0] if stamps else None,
        'spanMs': stamps[-1] - stamps[0] if stamps else None}
    if samples is not None:
        import numpy as np
        duration = len(samples) * 1000 / rate if number(rate, 1, 48000) else None
        result.update(audioValidated=(rate in cfg['V2_WAV_RATES'] and number(duration, cfg['V2_CLIP_MIN_MS'], cfg['V2_CLIP_MAX_MS'])
                                      and bool(np.isfinite(samples).all()) and number(audio_start_ms, 0, 250)),
                      audioDurationMs=duration, audioStartMs=audio_start_ms, sampleRate=rate)
    return result


def step_record(capture, **checks):
    return {'version': GATE_VERSION, 'config': gate_config(), 'capture': capture, **checks}


def _record(detail, name):
    record = detail.get(name)
    return record if isinstance(record, dict) and record.get('version') == GATE_VERSION else {}


def _config_valid(cfg):
    return (count(cfg.get('V2_FRAME_MIN_COUNT'), 8)
            and number(cfg.get('V2_FACE_QUALITY_MIN_RATIO'), .8, 1)
            and count(cfg.get('V2_LIP_MIN_SAMPLES'), 12)
            and number(cfg.get('V2_LANDMARK_MIN_RATIO'), .8, 1)
            and count(cfg.get('V2_FLASH_MIN_SAMPLES'), 4)
            and number(cfg.get('V2_FLASH_MIN_SPAN_MS'), 150, 400)
            and number(cfg.get('V2_LANDMARK_MAX_GAP_MS'), 1, 150)
            and number(cfg.get('identityMinimum'), .363, 1))


def _state(check, flag, valid):
    if not isinstance(check, dict) or type(check.get(flag)) is not bool:
        return 'not_recorded'
    return 'passed' if check[flag] and valid else 'failed'


def _capture(record, *, audio=False):
    cfg = record.get('config', {})
    check = record.get('capture', {})
    if not isinstance(cfg, dict) or not isinstance(check, dict):
        return 'not_recorded'
    eligible, usable = check.get('eligibleFrames'), check.get('usableFrames')
    valid = (_config_valid(cfg) and count(eligible, 8) and count(usable, 8)
             and usable <= eligible and usable >= cfg['V2_FRAME_MIN_COUNT']
             and usable >= eligible * cfg['V2_FACE_QUALITY_MIN_RATIO']
             and check.get('videoValidated') is True and count(check.get('frameCount'), 8)
             and eligible <= check['frameCount'] and number(check.get('firstFrameMs'), 0, 500)
             and number(check.get('spanMs'), 2000, 4000))
    if audio:
        valid = (valid and check.get('audioValidated') is True and number(check.get('audioDurationMs'), 2000, 4000)
                 and number(check.get('audioStartMs'), 0, 250)
                 and type(check.get('sampleRate')) is int and check['sampleRate'] in (8000, 16000, 22050, 32000, 44100, 48000))
    return _state(check, 'usable', valid)


def evaluate_gates(detail_json, *, cosine=None, speak_cosine=None, expected_word=None):
    """Never infer successful measurements from scores or historical placeholders."""
    detail = object_json(detail_json)
    look, speak = _record(detail, 'lookGateEvidence'), _record(detail, 'speakGateEvidence')
    lc, sc = look.get('config', {}), speak.get('config', {})
    lc = lc if isinstance(lc, dict) else {}
    sc = sc if isinstance(sc, dict) else {}
    blink, flash, lip = look.get('blink', {}), look.get('flash', {}), speak.get('lip', {})
    blink = blink if isinstance(blink, dict) else {}
    flash = flash if isinstance(flash, dict) else {}
    lip = lip if isinstance(lip, dict) else {}
    blink_valid = (_config_valid(lc) and count(blink.get('cycles'), 1)
                   and count(blink.get('samples'), 8) and count(blink.get('totalFrames'), 8)
                   and blink['samples'] <= blink['totalFrames']
                   and blink['samples'] >= blink['totalFrames'] * lc['V2_LANDMARK_MIN_RATIO']
                   and blink['cycles'] * 3 <= blink['samples']
                   and number(blink.get('maxGapMs'), 1, lc['V2_LANDMARK_MAX_GAP_MS']))
    flash_valid = (_config_valid(lc) and count(flash.get('beforeSamples'), lc.get('V2_FLASH_MIN_SAMPLES', 4))
                   and count(flash.get('duringSamples'), lc.get('V2_FLASH_MIN_SAMPLES', 4))
                   and number(flash.get('beforeSpanMs'), lc.get('V2_FLASH_MIN_SPAN_MS', 150), 400)
                   and number(flash.get('duringSpanMs'), lc.get('V2_FLASH_MIN_SPAN_MS', 150), 400)
                   and number(flash.get('maxGapMs'), 1, lc.get('V2_LANDMARK_MAX_GAP_MS', 150))
                   and number(flash.get('delta'), -1, 50) and number(flash.get('correlation'), -1, 1))
    lip_valid = (_config_valid(sc) and count(lip.get('samples'), sc.get('V2_LIP_MIN_SAMPLES', 12))
                 and count(lip.get('totalFrames'), 12) and lip['samples'] <= lip['totalFrames']
                 and lip['samples'] >= lip['totalFrames'] * sc['V2_LANDMARK_MIN_RATIO']
                 and number(lip.get('maxGapMs'), 1, sc['V2_LANDMARK_MAX_GAP_MS'])
                 and number(lip.get('correlation'), -1, 1)
                 and number(lip.get('mouthVariance'), 0, 1))
    def identity_state(value, cfg):
        if not number(value, -1, 1):
            return 'not_recorded'
        minimum = cfg.get('identityMinimum', max(.363, current_app.config['COSINE_MATCH']))
        minimum = max(minimum, .363, current_app.config['COSINE_MATCH']) if number(minimum, .363, 1) else None
        return 'passed' if minimum is not None and identity_matches(value, minimum) else 'failed'
    speech = detail.get('speech')
    gates = {
        'lookCapture': _capture(look), 'speakCapture': _capture(speak, audio=True),
        'lookIdentity': identity_state(cosine, lc), 'speakIdentity': identity_state(speak_cosine, sc),
        'blink': _state(blink, 'completed', blink_valid),
        'flash': _state(flash, 'measured', flash_valid),
        'word': ('passed' if isinstance(speech, dict) and speech.get('ok') is True
                 and speech.get('speechVersion') == 'vosk-unrestricted-1'
                 and stored_word_verified(json.dumps(detail), expected_word) else
                 'failed' if isinstance(speech, dict) else 'not_recorded'),
        'lips': _state(lip, 'usable', lip_valid),
    }
    return {'version': GATE_VERSION, 'safeEligible': all(state == 'passed' for state in gates.values()),
            'gates': gates}


def decision_snapshot(scored, eligibility):
    cfg = current_app.config
    return {**eligibility, **scored, 'config': {key: cfg[key] for key in (
        'WEIGHT_FACE', 'WEIGHT_BLINK', 'WEIGHT_VOICE', 'VOICE_ACOUSTIC', 'VOICE_LIP',
        'SAFE_MIN', 'SUSPICIOUS_MIN', 'FACE_SAFE_CAP', 'FACE_CAP_TRUST', 'COSINE_MATCH', 'FLASH_ADJUST',
    )}}


def stored_decision(detail_json):
    decision = object_json(detail_json).get('machineDecision')
    if (not isinstance(decision, dict) or decision.get('version') != GATE_VERSION
            or type(decision.get('safeEligible')) is not bool
            or not isinstance(decision.get('gates'), dict)
            or set(decision['gates']) != {'lookCapture', 'speakCapture', 'lookIdentity', 'speakIdentity',
                                         'blink', 'flash', 'word', 'lips'}
            or any(state not in ('passed', 'failed', 'not_recorded') for state in decision['gates'].values())
            or not number(decision.get('trustScore'), 0, 100)
            or decision.get('riskLabel') not in ('SAFE', 'SUSPICIOUS', 'DEEPFAKE')):
        return None
    cfg = decision.get('config')
    if (not isinstance(cfg, dict) or not number(cfg.get('SAFE_MIN'), 75, 100)
            or not number(cfg.get('SUSPICIOUS_MIN'), 0, 74)
            or cfg['SUSPICIOUS_MIN'] >= cfg['SAFE_MIN']
            or decision['safeEligible'] != all(state == 'passed' for state in decision['gates'].values())
            or decision['riskLabel'] == 'SAFE' and not decision['safeEligible']):
        return None
    if (not number(decision.get('base'), 0, 300) or not number(decision.get('flashAdjust'), -100, 100)
            or any(not number(cfg.get(key), 0, 1) for key in (
                'WEIGHT_FACE', 'WEIGHT_BLINK', 'WEIGHT_VOICE', 'VOICE_ACOUSTIC', 'VOICE_LIP', 'COSINE_MATCH'))
            or not number(cfg.get('FACE_SAFE_CAP'), 0, 100) or not number(cfg.get('FACE_CAP_TRUST'), 0, 100)):
        return None
    label = ('SAFE' if decision['trustScore'] >= cfg['SAFE_MIN'] else
             'SUSPICIOUS' if decision['trustScore'] >= cfg['SUSPICIOUS_MIN'] else 'DEEPFAKE')
    if label != decision['riskLabel']:
        return None
    return decision
