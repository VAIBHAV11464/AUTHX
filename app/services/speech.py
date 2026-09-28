"""Local unrestricted Vosk recognition. No downloads or session decisions here."""
import hashlib
import json
import math
import re
from importlib.metadata import version
from pathlib import Path
from threading import RLock

import numpy as np
from flask import current_app

_lock = RLock()
_model = None
_model_key = None
_recognizer = None


class SpeechError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _load():
    global _model, _model_key, _recognizer
    cfg = current_app.config
    root = Path(cfg['SPEECH_MODEL_PATH']).resolve()
    manifest = Path(cfg['SPEECH_MANIFEST_PATH'])
    if not root.is_dir() or not manifest.is_file():
        raise SpeechError('speech_model_missing')
    try:
        blob = manifest.read_bytes()
        if hashlib.sha256(blob).hexdigest() != cfg['SPEECH_MANIFEST_SHA256']:
            raise ValueError('manifest checksum')
        inventory = json.loads(blob)['files']
        if not inventory:
            raise ValueError('empty inventory')
        paths = [(root / name).resolve() for name in inventory]
        if any(not path.is_relative_to(root) for path in paths):
            raise ValueError('invalid inventory path')
        key = (str(root), cfg['SPEECH_MANIFEST_SHA256'], cfg['VOSK_VERSION'],
               tuple((path.stat().st_size, path.stat().st_mtime_ns) for path in paths))
        if _model is not None and key == _model_key:
            return _model, _recognizer
        for path, expected in zip(paths, inventory.values()):
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('model checksum')
    except FileNotFoundError as exc:
        raise SpeechError('speech_model_missing') from exc
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SpeechError('speech_model_invalid') from exc
    try:
        if version('vosk') != cfg['VOSK_VERSION']:
            raise ValueError('unsupported Vosk version')
        from vosk import Model, KaldiRecognizer
        # A path is mandatory: lang/model_name constructors can download models.
        candidate = Model(str(root))
        probe = KaldiRecognizer(candidate, 16000)
        probe.SetWords(True)
        probe.FinalResult()
    except Exception as exc:
        raise SpeechError('speech_runtime_unavailable') from exc
    _model, _model_key, _recognizer = candidate, key, KaldiRecognizer
    return _model, _recognizer


def availability():
    """Validate integrity and native initialization, without recognizing user audio."""
    with _lock:
        try:
            _load()
            return {'ok': True, **_metadata()}
        except SpeechError as exc:
            return {'ok': False, 'reason': exc.reason}


def _metadata():
    cfg = current_app.config
    return {'speechVersion': 'vosk-unrestricted-1', 'voskVersion': cfg['VOSK_VERSION'],
            'speechModel': 'vosk-model-small-en-us-0.15',
            'speechManifestSha256': cfg['SPEECH_MANIFEST_SHA256'],
            'recognizerRate': 16000, 'grammarRestricted': False}


def transcribe(samples, rate):
    """Normalized audio -> PCM16 at 16 kHz, preserving elapsed time at all upload rates."""
    audio = np.asarray(samples, dtype=np.float64)
    if (audio.ndim != 1 or not audio.size or isinstance(rate, bool)
            or rate not in current_app.config['V2_WAV_RATES'] or not np.isfinite(audio).all()
            or np.max(np.abs(audio)) > 1):
        return {'ok': False, 'reason': 'invalid_speech_audio'}
    if rate != 16000:
        count = round(audio.size * 16000 / rate)
        audio = np.interp(np.arange(count) / 16000, np.arange(audio.size) / rate, audio)
    pcm = np.clip(np.rint(audio * 32768), -32768, 32767).astype('<i2').tobytes()
    with _lock:
        try:
            model, factory = _load()
            # Every attempt gets a new decoder. Never pass a grammar/expected word.
            recognizer = factory(model, 16000)
            recognizer.SetWords(True)
            segments = []
            for offset in range(0, len(pcm), 8000):
                if recognizer.AcceptWaveform(pcm[offset:offset + 8000]):
                    segments.append(json.loads(recognizer.Result()))
            segments.append(json.loads(recognizer.FinalResult()))
            text = ' '.join(segment.get('text', '') for segment in segments).strip()
            words = [word for segment in segments for word in segment.get('result', [])]
            if len(text) > 1000 or len(words) > 128:
                raise ValueError('unexpected result size')
            # JSON-safe small evidence only; an invalid confidence is never a match.
            measured = []
            for word in words:
                conf = word.get('conf')
                if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not np.isfinite(conf):
                    conf = None
                measured.append({'word': word.get('word'), 'confidence': conf})
            return {'ok': True, 'transcript': text, 'words': measured, **_metadata()}
        except SpeechError as exc:
            return {'ok': False, 'reason': exc.reason}
        except Exception:
            return {'ok': False, 'reason': 'speech_runtime_unavailable'}


def tokens(text):
    return re.findall(r'\w+', text.casefold()) if isinstance(text, str) else []


def verify_transcript(result, expected_word, minimum=0.80):
    """Exactly one transcript token and one aligned measured word; no phrase guessing."""
    expected = tokens(expected_word)
    if len(expected) != 1:
        return {'ok': False, 'reason': 'speech_configuration_invalid'}
    if not result.get('ok'):
        return result
    transcript = tokens(result.get('transcript'))
    if not transcript:
        return {'ok': False, 'reason': 'word_not_heard'}
    if len(transcript) != 1:
        return {'ok': False, 'reason': 'ambiguous_word'}
    if transcript != expected:
        return {'ok': False, 'reason': 'wrong_word'}
    words = result.get('words')
    if (not isinstance(words, list) or len(words) != 1 or not isinstance(words[0], dict)
            or tokens(words[0].get('word')) != transcript):
        return {'ok': False, 'reason': 'word_confidence_missing'}
    confidence = words[0].get('confidence')
    if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence) or not 0 <= confidence <= 1):
        return {'ok': False, 'reason': 'word_confidence_missing'}
    if confidence < minimum:
        return {'ok': False, 'reason': 'word_confidence_low'}
    return {'ok': True, 'matchedConfidence': confidence}


def verify_word(samples, rate, expected_word):
    minimum = current_app.config['V2_WORD_MIN_CONFIDENCE']
    if (isinstance(minimum, bool) or not isinstance(minimum, (int, float))
            or not math.isfinite(minimum) or not 0.80 <= minimum <= 1):
        return {'ok': False, 'reason': 'speech_configuration_invalid'}
    result = transcribe(samples, rate)
    decision = verify_transcript(result, expected_word, minimum)
    evidence = {**result, 'expectedWord': expected_word, 'wordVerified': decision['ok'],
                'wordConfigVersion': 'single-token-confidence-1', 'minimumConfidence': minimum,
                'matchedConfidence': decision.get('matchedConfidence')}
    # Preserve measured transcript/confidence even for a wrong or unclear word.
    return {**decision, 'speech': evidence}


def stored_word_verified(detail_json, expected_word):
    """Historical v2 scores are not evidence of recognition; keep issued certs intact."""
    try:
        evidence = json.loads(detail_json or '{}').get('speech')
        if not isinstance(evidence, dict):
            return False
        minimum = evidence.get('minimumConfidence')
        if (isinstance(minimum, bool) or not isinstance(minimum, (int, float))
                or not math.isfinite(minimum) or not 0.8 <= minimum <= 1):
            return False
        return (evidence.get('wordConfigVersion') == 'single-token-confidence-1'
                and evidence.get('grammarRestricted') is False
                and evidence.get('wordVerified') is True
                and tokens(evidence.get('expectedWord')) == tokens(expected_word)
                and verify_transcript(evidence, expected_word, minimum)['ok'])
    except (ValueError, AttributeError, TypeError):
        return False
