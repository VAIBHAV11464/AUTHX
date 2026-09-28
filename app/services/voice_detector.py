import io
import wave

import numpy as np
from flask import current_app


def read_wav(blob):
    try:
        with wave.open(io.BytesIO(blob), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            raw = handle.readframes(handle.getnframes())
    except Exception as exc:
        raise ValueError("bad_wav") from exc
    if channels != 1 or width != 2 or rate <= 0 or not raw:
        raise ValueError("bad_wav")
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    target = int(current_app.config["SAMPLE_RATE"])
    if rate != target and rate > 0:
        duration = samples.size / rate
        grid = np.linspace(0, duration, int(duration * target), endpoint=False)
        source = np.linspace(0, duration, samples.size, endpoint=False)
        samples = np.interp(grid, source, samples)
        rate = target
    return samples, rate


def score_wave(samples, sample_rate=None):
    cfg = current_app.config
    rate = int(sample_rate or cfg["SAMPLE_RATE"])
    if rate <= 0:
        rate = int(cfg["SAMPLE_RATE"])
    audio = np.asarray(samples, dtype=np.float64).reshape(-1)
    rms = float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0
    if rms < cfg["SILENCE_RMS"]:
        return _acoustic(10, rms, None, None, "silence")
    ratio = _speech_ratio(audio, rate)
    if ratio < cfg["SPEECH_RATIO_MIN"]:
        return _acoustic(10, rms, round(ratio, 4), None, "not_speech")
    raw = _mfcc_variance(audio, rate)
    variation = _map_variation(raw)
    presence = 100.0
    acoustic = cfg["ACOUSTIC_PRESENCE"] * presence + cfg["ACOUSTIC_VARIATION"] * variation
    return _acoustic(round(acoustic, 2), rms, round(ratio, 4), round(variation, 2), None)


def combine_voice(acoustic_score, lip_score):
    cfg = current_app.config
    voice = cfg["VOICE_ACOUSTIC"] * float(acoustic_score) + cfg["VOICE_LIP"] * float(lip_score)
    return round(voice, 2)


def _acoustic(score, rms, ratio, variation, detail):
    return {
        "ok": True,
        "acousticScore": score,
        "rms": round(float(rms), 5),
        "speechRatio": ratio,
        "mfccVariation": variation,
        "detail": detail,
    }


def _speech_ratio(audio, rate):
    spectrum = np.abs(np.fft.rfft(audio)) ** 2
    freqs = np.fft.rfftfreq(audio.size, 1 / rate)
    speech = spectrum[(freqs >= 300) & (freqs <= 3400)].sum()
    band = spectrum[(freqs >= 80) & (freqs <= rate / 2)].sum()
    if band <= 0:
        return 0.0
    return float(speech / band)


def _mfcc_variance(audio, rate):
    cfg = current_app.config
    emphasized = np.empty_like(audio)
    emphasized[0] = audio[0]
    emphasized[1:] = audio[1:] - cfg["MFCC_PREEMPH"] * audio[:-1]
    frame_len = int(0.025 * rate)
    hop = int(0.010 * rate)
    if emphasized.size < frame_len:
        return 0.0
    window = np.hamming(frame_len)
    n_fft = 512
    bank = _mel_bank(n_fft, 26, rate)
    frames = []
    for start in range(0, emphasized.size - frame_len + 1, hop):
        frame = emphasized[start : start + frame_len] * window
        power = np.abs(np.fft.rfft(frame, n=n_fft)) ** 2
        frames.append(power)
    if not frames:
        return 0.0
    mel = np.maximum(np.vstack(frames) @ bank.T, 1e-10)
    coeffs = _dct(np.log(mel), cfg["MFCC_COUNT"])
    if coeffs.shape[0] < 2:
        return 0.0
    return float(np.mean(np.var(coeffs, axis=0)))


def _map_variation(raw):
    cfg = current_app.config
    flat = float(cfg["MFCC_FLAT_SCORE"])
    varied = float(cfg["MFCC_VARIED_SCORE"])
    span = float(cfg["MFCC_RAW_HIGH"])
    if span <= 0:
        return flat
    score = flat + (raw / span) * (varied - flat)
    if score < flat:
        return flat
    if score > 100:
        return 100.0
    return float(score)


def _mel_bank(n_fft, n_mels, rate):
    n_freqs = n_fft // 2 + 1
    low = 2595.0 * np.log10(1.0)
    high = 2595.0 * np.log10(1.0 + (rate / 2) / 700.0)
    mels = np.linspace(low, high, n_mels + 2)
    hz = 700.0 * (10 ** (mels / 2595.0) - 1.0)
    bins = np.floor((n_fft + 1) * hz / rate).astype(int)
    bank = np.zeros((n_mels, n_freqs))
    for index in range(n_mels):
        left, center, right = int(bins[index]), int(bins[index + 1]), int(bins[index + 2])
        if center <= left:
            center = left + 1
        if right <= center:
            right = center + 1
        for bin_index in range(left, center):
            if 0 <= bin_index < n_freqs:
                bank[index, bin_index] = (bin_index - left) / (center - left)
        for bin_index in range(center, right):
            if 0 <= bin_index < n_freqs:
                bank[index, bin_index] = (right - bin_index) / (right - center)
    return bank


def _dct(rows, count):
    filters = rows.shape[1]
    coeffs = np.arange(count)[:, None]
    bins = np.arange(filters)[None, :]
    basis = np.cos(np.pi * coeffs * (bins + 0.5) / filters)
    return rows @ basis.T
