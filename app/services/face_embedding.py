"""Validate SFace vectors without changing existing stored embeddings."""

import json

import numpy as np


def unit_vector(value):
    try:
        if isinstance(value, str):
            value = json.loads(value)
        vector = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError, OverflowError):
        return None
    if vector.shape != (128,) or not np.isfinite(vector).all():
        return None
    with np.errstate(over="ignore", invalid="ignore"):
        norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm <= 0:
        return None
    return vector / norm
