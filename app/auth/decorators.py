from functools import wraps

import jwt
from flask import current_app, g, jsonify, request

from app.models import get_user_by_id


def token_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify(ok=False, error="missing_token"), 401
        token = header[7:].strip()
        try:
            payload = jwt.decode(
                token,
                current_app.config["JWT_SECRET"],
                algorithms=["HS256"],
            )
        except jwt.ExpiredSignatureError:
            return jsonify(ok=False, error="token_expired"), 401
        except jwt.InvalidTokenError:
            return jsonify(ok=False, error="invalid_token"), 401
        try:
            user_id = int(payload.get("sub"))
        except (TypeError, ValueError):
            return jsonify(ok=False, error="invalid_token"), 401
        user = get_user_by_id(user_id)
        if user is None:
            return jsonify(ok=False, error="invalid_token"), 401
        g.user = user
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @token_required
        def wrapped(*args, **kwargs):
            if g.user["role"] not in roles:
                return jsonify(ok=False, error="forbidden"), 403
            return view(*args, **kwargs)

        return wrapped

    return decorator
