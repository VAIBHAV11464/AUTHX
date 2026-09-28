import base64
import io

import numpy as np
from flask import Blueprint, current_app, g, jsonify, request
from PIL import Image

from app.auth.decorators import token_required
from app.models import save_face_embedding
from app.services.face_detector import enroll_image, models_ready
from app.services.verification_profiles import get_profile
from app.services import uploads
from app.services.enrollment import enroll_samples

bp = Blueprint("face", __name__)


@bp.post("/api/face/enroll")
@token_required
def enroll():
    if not models_ready():
        return jsonify(ok=False, reason="model_missing"), 503
    profile = get_profile(current_app.config["VERIFICATION_PROFILE"])
    if profile.name == "v2":
        try:
            data = uploads.payload(request.get_json(silent=True))
            images = uploads.enrollment_images(data)
        except uploads.UploadError as exc:
            return jsonify(ok=False, reason=exc.reason), 400
        reason, embedding = enroll_samples(images)
    else:
        image = _image_from_request()
        if image is None:
            return jsonify(ok=False, reason="bad_image"), 400
        reason, embedding = enroll_image(image)
    if reason:
        status = 503 if reason == "model_missing" else 422
        return jsonify(ok=False, reason=reason), status
    save_face_embedding(g.user["id"], embedding)
    return jsonify(ok=True, enrolled=True)


def _image_from_request():
    data = request.get_json(silent=True) or {}
    raw = data.get("image") or ""
    if not isinstance(raw, str):
        return None
    if "," in raw:
        raw = raw.split(",", 1)[1]
    if not raw:
        return None
    try:
        blob = base64.b64decode(raw)
        picture = Image.open(io.BytesIO(blob)).convert("RGB")
    except Exception:
        return None
    array = np.asarray(picture)
    return array[:, :, ::-1].copy()
