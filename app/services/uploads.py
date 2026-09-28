"""Bounded decoding for v2 captures; no recordings are persisted here."""

import base64
import binascii
import io
import math
import struct
import warnings
import wave

import numpy as np
from flask import current_app
from PIL import Image

from app.services.voice_detector import read_wav


class UploadError(ValueError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def payload(data):
    if not isinstance(data, dict):
        raise UploadError("bad_payload")
    return data


def _blob(raw, reason):
    if not isinstance(raw, str) or not raw:
        raise UploadError(reason)
    if raw.startswith("data:"):
        header, separator, raw = raw.partition(",")
        if not separator or not header.endswith(";base64"):
            raise UploadError(reason)
    try:
        return base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        raise UploadError(reason) from None


def image(raw, remaining_pixels=None):
    blob = _blob(raw, "bad_image")
    cfg = current_app.config
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(blob)) as picture:
                width, height = picture.size
                if (min(width, height) < cfg["V2_IMAGE_MIN_SIDE"]
                        or max(width, height) > cfg["V2_IMAGE_MAX_SIDE"]
                        or width * height > cfg["V2_IMAGE_MAX_PIXELS"]):
                    raise UploadError("bad_image_dimensions")
                if remaining_pixels is not None and width * height > remaining_pixels:
                    raise UploadError("capture_too_large")
                if picture.format not in ("JPEG", "PNG") or getattr(picture, "n_frames", 1) != 1:
                    raise UploadError("bad_image")
                array = np.asarray(picture.convert("RGB"))
                return array[:, :, ::-1].copy()
    except UploadError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise UploadError("bad_image") from None


def frames(data):
    raw_frames = payload(data).get("frames")
    cfg = current_app.config
    if not isinstance(raw_frames, list):
        raise UploadError("bad_frames")
    if not cfg["V2_FRAME_MIN_COUNT"] <= len(raw_frames) <= cfg["V2_FRAME_MAX_COUNT"]:
        raise UploadError("bad_frame_count")
    # Check the entire time series before allocating decoded image arrays.
    stamps = []
    for item in raw_frames:
        if not isinstance(item, dict):
            raise UploadError("bad_frames")
        stamp = item.get("tMs")
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
            raise UploadError("bad_timestamps")
        try:
            stamp = float(stamp)
        except (ValueError, OverflowError):
            raise UploadError("bad_timestamps") from None
        if (not math.isfinite(stamp) or stamp < 0 or stamp > cfg["V2_CLIP_MAX_MS"]
                or (stamps and stamp <= stamps[-1])):
            raise UploadError("bad_timestamps")
        stamps.append(stamp)
    if (stamps[0] > cfg["V2_FIRST_FRAME_MAX_MS"]
            or not cfg["V2_CLIP_MIN_MS"] <= stamps[-1] - stamps[0] <= cfg["V2_CLIP_MAX_MS"]):
        raise UploadError("bad_capture_duration")
    remaining = cfg["V2_CLIP_MAX_PIXELS"]
    decoded = []
    for stamp, item in zip(stamps, raw_frames):
        frame = image(item.get("image"), remaining)
        remaining -= frame.shape[0] * frame.shape[1]
        decoded.append((stamp, frame))
    return decoded


def enrollment_images(data):
    data = payload(data)
    if "images" not in data:
        return [image(data.get("image"))]
    raw = data["images"]
    if "image" in data or not isinstance(raw, list):
        raise UploadError("bad_enrollment_images")
    if len(raw) != current_app.config["V2_ENROLL_SAMPLE_COUNT"]:
        raise UploadError("bad_enrollment_count")
    remaining = current_app.config["V2_CLIP_MAX_PIXELS"]
    decoded = []
    for value in raw:
        frame = image(value, remaining)
        remaining -= frame.shape[0] * frame.shape[1]
        decoded.append(frame)
    return decoded


def _wav_container(blob):
    if (len(blob) < 12 or blob[:4] != b"RIFF" or blob[8:12] != b"WAVE"
            or int.from_bytes(blob[4:8], "little") + 8 != len(blob)):
        raise UploadError("bad_wav")
    seen = set()
    offset = 12
    while offset + 8 <= len(blob):
        kind = blob[offset:offset + 4]
        size = int.from_bytes(blob[offset + 4:offset + 8], "little")
        start = offset + 8
        end = start + size
        if end + (size % 2) > len(blob):
            raise UploadError("bad_wav")
        if kind in (b"fmt ", b"data"):
            if kind in seen:
                raise UploadError("bad_wav_format")
            seen.add(kind)
        if kind == b"fmt ":
            if size < 16:
                raise UploadError("bad_wav_format")
            encoding, channels, rate, byte_rate, align, bits = struct.unpack_from("<HHIIHH", blob, start)
            if encoding != 1 or channels != 1 or bits != 16 or align != 2 or byte_rate != rate * 2:
                raise UploadError("bad_wav_format")
        if kind == b"data" and (size == 0 or size % 2):
            raise UploadError("bad_wav_format")
        offset = end + (size % 2)
    if offset != len(blob) or seen != {b"fmt ", b"data"}:
        raise UploadError("bad_wav")


def wav(data):
    blob = _blob(payload(data).get("wav"), "bad_wav")
    _wav_container(blob)
    cfg = current_app.config
    try:
        with wave.open(io.BytesIO(blob), "rb") as handle:
            channels, width, rate = handle.getnchannels(), handle.getsampwidth(), handle.getframerate()
            count = handle.getnframes()
            if (handle.getcomptype() != "NONE" or channels != 1 or width != 2
                    or rate not in cfg["V2_WAV_RATES"] or count <= 0):
                raise UploadError("bad_wav_format")
            if not cfg["V2_CLIP_MIN_MS"] <= count * 1000 / rate <= cfg["V2_CLIP_MAX_MS"]:
                raise UploadError("bad_audio_duration")
            # wave can otherwise accept a truncated data chunk with its old header.
            if len(handle.readframes(count)) != count * channels * width:
                raise UploadError("bad_wav")
        return read_wav(blob)
    except UploadError:
        raise
    except (wave.Error, EOFError, OSError, ValueError):
        raise UploadError("bad_wav") from None


def audio_start_ms(data):
    """Optional sample-clock offset, in the same epoch as video tMs."""
    value = payload(data).get("audioStartMs", 0)
    if (isinstance(value, bool) or not isinstance(value, (int, float))):
        raise UploadError("bad_audio_timing")
    try:
        value = float(value)
    except (ValueError, OverflowError):
        raise UploadError("bad_audio_timing") from None
    if not math.isfinite(value) or not 0 <= value <= 250:
        raise UploadError("bad_audio_timing")
    return value
