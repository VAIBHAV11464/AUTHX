from flask import Flask, jsonify, redirect

from app.models import init_db
from app.routes.auth import bp as auth_bp
from app.routes.face import bp as face_bp
from app.routes.pages import bp as pages_bp
from app.routes.verification import bp as verification_bp
from app.routes.voice import bp as voice_bp
from app.services.verification_profiles import get_profile
from config import Config


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    get_profile(app.config["VERIFICATION_PROFILE"])
    init_db()
    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(face_bp)
    app.register_blueprint(voice_bp)
    app.register_blueprint(verification_bp)

    @app.errorhandler(413)
    def upload_too_large(error):
        return jsonify(ok=False, reason="upload_too_large"), 413

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", name="AuthX")

    @app.get("/")
    def home():
        return redirect("/login")

    return app
