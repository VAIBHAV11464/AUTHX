import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me")
    JWT_SECRET = os.getenv("JWT_SECRET", "dev-jwt-change-me-use-32-bytes-min")
    JWT_HOURS = 8
    OTP_MINUTES = 10

    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

    DATABASE_PATH = BASE_DIR / "authx.db"
    YUNET_PATH = BASE_DIR / "models" / "face_detection_yunet_2023mar.onnx"
    SFACE_PATH = BASE_DIR / "models" / "face_recognition_sface_2021dec.onnx"
    LANDMARK_PATH = BASE_DIR / "models" / "face_landmarker.task"
    LANDMARK_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
    MEDIAPIPE_VERSION = "0.10.35"
    SPEECH_MODEL_PATH = BASE_DIR / "models" / "vosk-model-small-en-us-0.15"
    SPEECH_MANIFEST_PATH = BASE_DIR / "models" / "vosk-model-small-en-us-0.15.json"
    SPEECH_MANIFEST_SHA256 = "54e9e66b9592bbf3489d59a8b2d3460327671d25ee5f263f1e3280e1ea9cad29"
    VOSK_VERSION = "0.3.45"
    V2_WORD_MIN_CONFIDENCE = 0.80
    V2_CAPTURE_FRAME_MS = 50
    # Provisional geometry/evidence thresholds; volunteer evaluation is deferred.
    V2_EAR_OPEN = 0.21
    V2_EAR_CLOSED = 0.17
    V2_BLINK_MIN_CLOSED_MS = 40
    V2_BLINK_MAX_CLOSED_MS = 500
    V2_LANDMARK_MAX_GAP_MS = 150
    V2_LANDMARK_MIN_RATIO = 0.80
    V2_LIP_MIN_SAMPLES = 12
    V2_MOUTH_VAR_FLOOR = 0.0001
    V2_AUDIO_ENERGY_VAR_FLOOR = 0.00000001
    V2_FLASH_MIN_SAMPLES = 4
    V2_FLASH_MIN_SPAN_MS = 150
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
    VERIFICATION_PROFILE = os.getenv("VERIFICATION_PROFILE", "legacy")

    # v2 upload bounds cover the current three-second browser captures.
    V2_IMAGE_MIN_SIDE = 64
    V2_IMAGE_MAX_SIDE = 1280
    V2_IMAGE_MAX_PIXELS = 1280 * 720
    V2_CLIP_MAX_PIXELS = 30_000_000
    V2_FRAME_MIN_COUNT = 8
    V2_FRAME_MAX_COUNT = 90
    V2_CLIP_MIN_MS = 2000
    V2_CLIP_MAX_MS = 4000
    V2_FIRST_FRAME_MAX_MS = 500
    V2_WAV_RATES = (8000, 16000, 22050, 32000, 44100, 48000)
    # Initial demo quality thresholds; volunteer tuning remains Task 23.
    V2_FACE_MIN_PX = 80
    V2_FACE_MIN_AREA_RATIO = 0.02
    V2_FACE_MIN_CONFIDENCE = 0.6
    V2_FACE_MIN_VISIBLE_RATIO = 0.90
    V2_FACE_MIN_BRIGHTNESS = 40
    V2_FACE_MAX_BRIGHTNESS = 225
    V2_FACE_MAX_CLIPPED_RATIO = 0.60
    V2_FACE_MIN_SHARPNESS = 25
    V2_FACE_QUALITY_MIN_RATIO = 0.80
    V2_ENROLL_SAMPLE_COUNT = 5
    V2_ENROLL_MIN_USABLE = 3
    V2_ENROLL_CONSISTENCY_COSINE = 0.60

    CREATORS = ("Vaibhav", "Sriram", "Avinash")
    CERT_PREFIX = "AX-"

    WEIGHT_FACE = 0.45
    WEIGHT_BLINK = 0.30
    WEIGHT_VOICE = 0.25
    VOICE_ACOUSTIC = 0.75
    VOICE_LIP = 0.25
    ACOUSTIC_PRESENCE = 0.30
    ACOUSTIC_VARIATION = 0.70

    SAFE_MIN = 75
    SUSPICIOUS_MIN = 45
    FACE_SAFE_CAP = 50
    FACE_CAP_TRUST = 74

    FLASH_ADJUST = {90: 8, 60: 3, 50: 0, 25: -8}

    YUNET_SCORE = 0.6
    YUNET_SCORE_RETRY = 0.4
    MIN_FACE_PX = 60
    ENROLL_YUNET_SCORE = 0.7
    ENROLL_MIN_FACE_PX = 80
    COSINE_MATCH = 0.363

    BLINK_DIP_PERCENT = 8
    BLINK_RETURN_PERCENT = 4

    FLASH_START_MIN_MS = 1900
    FLASH_START_MAX_MS = 2400
    FLASH_DURATION_MS = 400
    FLASH_DELTA_HIGH = 0.08
    FLASH_DELTA_MID = 0.03

    SILENCE_RMS = 0.01
    SPEECH_RATIO_MIN = 0.35
    SAMPLE_RATE = 16000
    MFCC_COUNT = 13
    MFCC_PREEMPH = 0.97
    MFCC_FLAT_SCORE = 15
    MFCC_VARIED_SCORE = 90
    MFCC_RAW_HIGH = 74
    LIP_CORR_HIGH = 0.45
    LIP_CORR_MID = 0.25
    MOUTH_VAR_FLOOR = 1.0

    FRAME_LONG_SIDE = 640
    JPEG_QUALITY = 0.7

    CHALLENGE_WORDS = (
        "amber",
        "bridge",
        "citrus",
        "delta",
        "ember",
        "falcon",
        "granite",
        "harbor",
        "ivory",
        "juniper",
    )
