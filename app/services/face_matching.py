"""v2 matches approved detections; Look excludes flash, Speak uses all times."""

import cv2
import numpy as np

from app.services.face_quality import inspect_clip
from app.services.face_embedding import unit_vector
from app.services.face_detector import embed_row, cosine_to_score


def match_quality_frames(frames, flash_start_ms, embedding):
    reason, approved = inspect_clip(frames, flash_start_ms)
    if reason:
        return {"ok": False, "reason": reason}
    enrolled = unit_vector(embedding)
    if enrolled is None:
        return {"ok": False, "reason": "not_enrolled"}
    approved.sort(key=lambda item: float(item[2][-1]), reverse=True)
    cosines = []
    for _, image, face in approved[:3]:
        try:
            feature = unit_vector(embed_row(image, face))
        except cv2.error:
            return {"ok": False, "reason": "model_missing"}
        except ValueError:
            return {"ok": False, "reason": "invalid_face_embedding"}
        if feature is None:
            return {"ok": False, "reason": "invalid_face_embedding"}
        cosines.append(float(np.clip(np.dot(enrolled, feature), -1.0, 1.0)))
    # Store the unrounded cosine in the existing REAL column. Rounding is
    # inappropriate for the independent 0.363 SAFE eligibility boundary.
    cosine = float(np.median(cosines))
    return {
        "ok": True,
        "faceScore": round(cosine_to_score(cosine), 2),
        "cosine": cosine,
        # Transient detections for subsequent geometry; never serialized/stored.
        "approvedFrames": approved,
    }
