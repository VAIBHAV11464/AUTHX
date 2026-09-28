import math

from flask import current_app
from app.services.decision_evidence import identity_matches, evaluate_gates


def fuse(face, blink, voice, flash):
    cfg = current_app.config
    base = (
        cfg["WEIGHT_FACE"] * float(face)
        + cfg["WEIGHT_BLINK"] * float(blink)
        + cfg["WEIGHT_VOICE"] * float(voice)
    )
    adjust = int(cfg["FLASH_ADJUST"].get(int(flash), 0))
    total = base + adjust
    if total < 0:
        total = 0.0
    if total > 100:
        total = 100.0
    trust = int(math.floor(total + 0.5))
    if trust > 100:
        trust = 100
    if float(face) < cfg["FACE_SAFE_CAP"]:
        trust = min(trust, int(cfg["FACE_CAP_TRUST"]))
    if trust >= cfg["SAFE_MIN"]:
        label = "SAFE"
    elif trust >= cfg["SUSPICIOUS_MIN"]:
        label = "SUSPICIOUS"
    else:
        label = "DEEPFAKE"
    return {
        "trustScore": trust,
        "riskLabel": label,
        "base": round(base, 2),
        "flashAdjust": adjust,
    }


def fuse_v2(face, blink, voice, flash, *, cosine=None, speak_cosine=None, detail_json=None, expected_word=None):
    scored = fuse(face, blink, voice, flash)
    eligibility = evaluate_gates(detail_json, cosine=cosine, speak_cosine=speak_cosine, expected_word=expected_word)
    if scored["riskLabel"] == "SAFE" and not eligibility['safeEligible']:
        cfg = current_app.config
        scored["trustScore"] = min(scored["trustScore"], cfg["FACE_CAP_TRUST"], cfg["SAFE_MIN"] - 1)
        scored["riskLabel"] = "SUSPICIOUS" if scored["trustScore"] >= cfg["SUSPICIOUS_MIN"] else "DEEPFAKE"
    return scored
