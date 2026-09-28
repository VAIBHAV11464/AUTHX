import json

from flask import Blueprint, current_app, render_template

from app.models import get_certificate, get_session
from app.services.certificate import chain_status
from app.services.evidence_summary import certificate_fields, display_lines

bp = Blueprint("pages", __name__)


def _home(role, heading):
    return render_template(
        "home.html",
        role=role,
        heading=heading,
        creators=current_app.config["CREATORS"],
        frame_long_side=current_app.config["FRAME_LONG_SIDE"],
        jpeg_quality=current_app.config["JPEG_QUALITY"],
        flash_ms=current_app.config["FLASH_DURATION_MS"],
        sample_rate=current_app.config["SAMPLE_RATE"],
        enrollment_samples=(current_app.config["V2_ENROLL_SAMPLE_COUNT"]
                            if current_app.config["VERIFICATION_PROFILE"] == "v2" else 1),
    )


@bp.get("/student")
def student_home():
    return _home("student", "Student home")


@bp.get("/faculty")
def faculty_home():
    return _home("faculty", "Faculty home")


@bp.get("/admin")
def admin_home():
    return _home("admin", "Admin home")


@bp.get("/faculty/session/<session_id>")
def faculty_session_page(session_id):
    if get_session(session_id) is None:
        return render_template(
            "faculty_session.html",
            missing=True,
            creators=current_app.config["CREATORS"],
        ), 404
    return render_template(
        "faculty_session.html",
        missing=False,
        session_id=session_id,
        creators=current_app.config["CREATORS"],
    )


@bp.get("/certificate/<cert_id>")
def certificate_page(cert_id):
    row = get_certificate(cert_id)
    if row is None:
        return render_template(
            "certificate.html",
            missing=True,
            creators=current_app.config["CREATORS"],
        ), 404
    try:
        record = json.loads(row["score_json"])
    except json.JSONDecodeError:
        record = {}
    if not isinstance(record, dict):
        record = {}
    return render_template(
        "certificate.html",
        missing=False,
        cert=row,
        record=record,
        evidence_lines=display_lines(certificate_fields(record)),
        chain=chain_status(cert_id),
        creators=current_app.config["CREATORS"],
    )
