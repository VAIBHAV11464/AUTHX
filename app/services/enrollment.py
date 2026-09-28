"""v2 single-image compatibility and consistent multi-image enrollment."""

import json

import numpy as np
from flask import current_app

from app.services.face_quality import enroll_image
from app.services.face_embedding import unit_vector


def enroll_samples(images):
    cfg = current_app.config
    if len(images) not in (1, cfg["V2_ENROLL_SAMPLE_COUNT"]):
        return "bad_enrollment_count", None
    usable = []
    for image in images:
        reason, embedding = enroll_image(image)
        # Do not silently drop another person's frame or model failures.
        if reason in ("multiple_faces", "model_missing"):
            return reason, None
        if reason:
            if len(images) == 1:
                return reason, None
            continue
        feature = unit_vector(embedding)
        if feature is None:
            return "invalid_face_embedding", None
        usable.append(feature)
    minimum = 1 if len(images) == 1 else cfg["V2_ENROLL_MIN_USABLE"]
    if len(usable) < minimum:
        return "too_few_enrollment_samples", None
    for index, left in enumerate(usable):
        for right in usable[index + 1:]:
            if float(np.dot(left, right)) < cfg["V2_ENROLL_CONSISTENCY_COSINE"]:
                return "inconsistent_enrollment", None
    average = unit_vector(np.mean(usable, axis=0))
    if average is None:
        return "invalid_face_embedding", None
    return None, json.dumps(average.tolist(), allow_nan=False)
