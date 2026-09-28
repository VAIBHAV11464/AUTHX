"""Measured-word fixtures for earlier suites isolating face/lip/profile behavior.

Real recognition and word/retry enforcement are tested separately. These fixtures
never alter the application's evidence checks or speech threshold.
"""
from unittest.mock import patch
from config import Config


def evidence(word='amber', confidence=.9):
    return {'ok': True, 'transcript': word, 'words': [{'word': word, 'confidence': confidence}],
            'speechVersion': 'vosk-unrestricted-1', 'voskVersion': Config.VOSK_VERSION,
            'speechModel': 'vosk-model-small-en-us-0.15',
            'speechManifestSha256': Config.SPEECH_MANIFEST_SHA256,
            'recognizerRate': 16000, 'grammarRestricted': False,
            'expectedWord': word, 'wordVerified': True,
            'wordConfigVersion': 'single-token-confidence-1', 'minimumConfidence': .8,
            'matchedConfidence': confidence}


def install(testcase):
    from app.services import verification_profiles as profiles
    from app.routes import verification
    ready = patch.object(verification, 'speech_availability', return_value={'ok': True})
    measured = patch.object(profiles, 'verify_word', side_effect=lambda samples, rate, expected_word:
                            {'ok': True, 'matchedConfidence': .9, 'speech': evidence(expected_word)})
    for mock in (ready, measured):
        mock.start()
        testcase.addCleanup(mock.stop)
