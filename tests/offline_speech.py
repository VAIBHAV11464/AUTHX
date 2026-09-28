"""Task 15: actual offline runtime plus isolated rate/integrity/state checks."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import Config
from app.services import speech


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.from_object(Config)
        ctx = self.app.app_context()
        ctx.push()
        self.addCleanup(ctx.pop)

    def test_actual_model_and_public_audio_without_network(self):
        fixture = ROOT / '.runtime/fixtures/vosk-test.wav'
        if not fixture.is_file():
            self.fail('Setup the official upstream fixture before runtime verification')
        with wave.open(str(fixture), 'rb') as wav:
            audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2') / 32768.
            rate = wav.getframerate()
        with patch('socket.create_connection', side_effect=AssertionError('network forbidden')), \
                patch('socket.socket.connect', side_effect=AssertionError('network forbidden')), \
                patch.object(speech, '_model', None), patch.object(speech, '_model_key', None):
            self.assertTrue(speech.availability()['ok'])
            first = speech.transcribe(audio, rate)
            shared = speech._model
            silence = speech.transcribe(np.zeros(48000), 16000)
            self.assertIs(speech._model, shared)
            second = speech.transcribe(audio, rate)
        self.assertTrue(first['ok'], first)
        self.assertIn('one zero zero zero one', first['transcript'])
        self.assertTrue(first['words'])
        self.assertTrue(all(0 <= word['confidence'] <= 1 for word in first['words']))
        self.assertEqual(silence['transcript'], '')
        self.assertEqual(first['transcript'], second['transcript'])
        self.assertFalse(first['grammarRestricted'])
        output = Path(os.environ.get('AUTHX_TEST_OUTPUT_DIR', tempfile.gettempdir()))
        output.mkdir(parents=True, exist_ok=True)
        (output / 'offline-inference.json').write_text(json.dumps(first, indent=2))

    def test_rates_duration_pcm_and_fresh_unrestricted_recognizer(self):
        instances = []
        class Decoder:
            def __init__(self, model, rate):
                self.rate = rate
                self.raw = b''
                instances.append(self)
            def SetWords(self, enabled):
                self.enabled = enabled
            def AcceptWaveform(self, data):
                self.raw += data
                return False
            def FinalResult(self):
                return '{"text":"amber","result":[{"word":"amber","conf":0.9}]}'
        with patch.object(speech, '_load', return_value=(object(), Decoder)):
            for rate in Config.V2_WAV_RATES:
                out = speech.transcribe(np.full(rate * 3, .25), rate)
                self.assertTrue(out['ok'])
                self.assertEqual(len(instances[-1].raw), 16000 * 3 * 2)
                self.assertEqual(np.frombuffer(instances[-1].raw, dtype='<i2')[0], 8192)
                self.assertTrue(instances[-1].enabled)
                self.assertEqual(instances[-1].rate, 16000)
        self.assertEqual(len({id(rec) for rec in instances}), 6)

    def test_endpoint_segments_are_not_lost(self):
        class Decoder:
            def SetWords(self, enabled): pass
            def AcceptWaveform(self, data): return True
            def Result(self): return '{"text":"amber","result":[{"word":"amber","conf":0.9}]}'
            def FinalResult(self): return '{"text":"bridge","result":[{"word":"bridge","conf":0.8}]}'
        with patch.object(speech, '_load', return_value=(None, lambda *args: Decoder())):
            result = speech.transcribe(np.zeros(4000), 16000)
        self.assertEqual(result['transcript'], 'amber bridge')
        self.assertEqual(len(result['words']), 2)

    def test_missing_corrupt_manifest_and_native_failure_are_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = root / 'manifest.json'
            self.app.config.update(SPEECH_MODEL_PATH=root / 'missing')
            self.assertEqual(speech.availability()['reason'], 'speech_model_missing')
            self.app.config.update(SPEECH_MODEL_PATH=root, SPEECH_MANIFEST_PATH=manifest)
            manifest.write_text('{}')
            self.assertEqual(speech.availability()['reason'], 'speech_model_invalid')
            (root / 'data').write_bytes(b'valid')
            manifest.write_text(json.dumps({'files': {'data': hashlib.sha256(b'valid').hexdigest()}}))
            self.app.config['SPEECH_MANIFEST_SHA256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
            with patch.object(speech, '_model', None), patch('vosk.Model', side_effect=OSError('native load')):
                self.assertEqual(speech.availability()['reason'], 'speech_runtime_unavailable')
            (root / 'data').write_bytes(b'corrupt')
            self.assertEqual(speech.availability()['reason'], 'speech_model_invalid')

    def test_bad_audio_and_invalid_confidence_fail_without_fake_evidence(self):
        for samples, rate in (([], 16000), ([float('nan')], 16000), ([2], 16000), ([0], 12345)):
            self.assertEqual(speech.transcribe(samples, rate)['reason'], 'invalid_speech_audio')
        class Decoder:
            def SetWords(self, enabled): pass
            def AcceptWaveform(self, data): return False
            def FinalResult(self): return '{"text":"amber","result":[{"word":"amber","conf":NaN}]}'
        with patch.object(speech, '_load', return_value=(None, lambda *args: Decoder())):
            result = speech.transcribe(np.zeros(100), 16000)
        self.assertIsNone(result['words'][0]['confidence'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
