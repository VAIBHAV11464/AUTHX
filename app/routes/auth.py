import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from flask import Blueprint, current_app, g, jsonify, render_template, request

from app.auth.decorators import role_required, token_required
from app.models import (
    create_otp,
    get_user_by_username,
    latest_unused_otp,
    mark_otp_used,
    consume_otp,
)
from app.services.otp import deliver_otp

bp = Blueprint("auth", __name__)


def _utc_now():
    return datetime.now(timezone.utc)


def _issue_token(user):
    expires = _utc_now() + timedelta(hours=current_app.config["JWT_HOURS"])
    return jwt.encode(
        {
            "sub": str(user["id"]),
            "username": user["username"],
            "role": user["role"],
            "exp": expires,
        },
        current_app.config["JWT_SECRET"],
        algorithm="HS256",
    )


def _token_payload(user, token):
    return {
        "ok": True,
        "token": token,
        "username": user["username"],
        "role": user["role"],
    }


def _credentials_match(value, stored_hash):
    try:
        encoded = value.encode('utf-8')
        return len(encoded) <= 72 and bcrypt.checkpw(encoded, stored_hash.encode('utf-8'))
    except (ValueError, TypeError, UnicodeError):
        return False


def _otp_expiry(row):
    try:
        expires = datetime.fromisoformat(row['expires_at'])
        return expires.replace(tzinfo=timezone.utc) if expires.tzinfo is None else expires
    except (ValueError, TypeError, OverflowError):
        return None


@bp.get("/login")
def login_page():
    return render_template("login.html", creators=current_app.config["CREATORS"])


@bp.get("/otp")
def otp_page():
    return render_template("otp.html", creators=current_app.config["CREATORS"])


@bp.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="invalid_credentials"), 401
    username = data.get("username") or ""
    password = data.get("password") or ""
    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify(ok=False, error="invalid_credentials"), 401
    username = username.strip()
    user = get_user_by_username(username)
    if user is None:
        return jsonify(ok=False, error="invalid_credentials"), 401
    if not _credentials_match(password, user["password_hash"]):
        return jsonify(ok=False, error="invalid_credentials"), 401
    if user["role"] == "student":
        return jsonify(_token_payload(user, _issue_token(user)))
    code = f"{secrets.randbelow(1000000):06d}"
    expires = (_utc_now() + timedelta(minutes=current_app.config["OTP_MINUTES"])).replace(
        microsecond=0
    ).isoformat()
    otp_hash = bcrypt.hashpw(code.encode(), bcrypt.gensalt()).decode()
    create_otp(user["id"], otp_hash, expires)
    channel = deliver_otp(user["username"], code)
    return jsonify(
        ok=True,
        otp_required=True,
        username=user["username"],
        role=user["role"],
        otp_channel=channel,
    )


@bp.post("/api/auth/otp")
def verify_otp():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error="invalid_otp"), 401
    username = data.get("username") or ""
    code = data.get("otp") or ""
    if not isinstance(username, str) or not isinstance(code, str):
        return jsonify(ok=False, error="invalid_otp"), 401
    username = username.strip()
    code = code.strip()
    user = get_user_by_username(username)
    if user is None or user["role"] == "student":
        return jsonify(ok=False, error="invalid_otp"), 401
    row = latest_unused_otp(user["id"])
    if row is None:
        return jsonify(ok=False, error="invalid_otp"), 401
    expires = _otp_expiry(row)
    if expires is None:
        mark_otp_used(row['id'])
        return jsonify(ok=False, error="invalid_otp"), 401
    if expires <= _utc_now():
        mark_otp_used(row["id"])
        return jsonify(ok=False, error="otp_expired"), 401
    if not _credentials_match(code, row["otp_hash"]):
        return jsonify(ok=False, error="invalid_otp"), 401
    # Hash verification is outside the short write lock; consumption rechecks
    # unused state and expiry after waiting for any competing writer/login.
    error = consume_otp(row['id'], now=_utc_now)
    if error:
        return jsonify(ok=False, error=error), 401
    return jsonify(_token_payload(user, _issue_token(user)))


@bp.get("/api/auth/me")
@token_required
def me():
    return jsonify(
        ok=True,
        username=g.user["username"],
        role=g.user["role"],
        enrolled=bool(g.user["face_embedding"]),
    )


@bp.get("/api/faculty/ping")
@role_required("faculty", "admin")
def faculty_ping():
    return jsonify(ok=True)
