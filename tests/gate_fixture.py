"""Explicit measured evidence for tests isolating other policies; no runtime patches."""
import json

from config import Config
from app.services.decision_evidence import GATE_VERSION
from speech_fixture import evidence as word_evidence


def blink():
    return {'completed': True, 'cycles': 1, 'samples': 40, 'totalFrames': 40, 'maxGapMs': 50}


def flash():
    return {'measured': True, 'beforeSamples': 8, 'duringSamples': 8,
            'beforeSpanMs': 350, 'duringSpanMs': 350, 'maxGapMs': 50, 'delta': .1, 'correlation': .8}


def lip():
    return {'usable': True, 'samples': 58, 'totalFrames': 60, 'maxGapMs': 50,
            'correlation': .8, 'mouthVariance': .01}


def record(**checks):
    keys = ('V2_FRAME_MIN_COUNT', 'V2_FACE_QUALITY_MIN_RATIO', 'V2_LIP_MIN_SAMPLES',
            'V2_LANDMARK_MIN_RATIO', 'V2_FLASH_MIN_SAMPLES', 'V2_FLASH_MIN_SPAN_MS', 'V2_LANDMARK_MAX_GAP_MS')
    return {'version': GATE_VERSION, 'config': {k: getattr(Config, k) for k in keys} | {'identityMinimum': .363},
            'capture': {'usable': True, 'eligibleFrames': 60, 'usableFrames': 60,
                        'videoValidated': True, 'frameCount': 60, 'firstFrameMs': 0, 'spanMs': 2950,
                        'audioValidated': True, 'audioDurationMs': 3000, 'audioStartMs': 0, 'sampleRate': 16000}, **checks}


def look_detail():
    return {'lookGateEvidence': record(blink=blink(), flash=flash())}


def speak_detail(word='amber'):
    return {'speakGateEvidence': record(lip=lip()), 'speech': word_evidence(word)}


def all_detail(word='amber'):
    return json.dumps({**look_detail(), **speak_detail(word)})


def fusion_options(word='amber'):
    return {'detail_json': all_detail(word), 'expected_word': word}
