import hashlib
import secrets
import time
from urllib.parse import urlsplit

from flask import abort, current_app, jsonify, request, session
from flask_login import current_user
from sqlalchemy import text

from . import db


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_login_rate():
    """Persistent atomic counters shared by workers. No passwords or email plaintext."""
    bucket = int(time.time()) // 900
    db.session.execute(text("DELETE FROM login_throttle WHERE bucket < :old"), {"old": bucket - 2})
    identities = [("ip:" + request.remote_addr, 15),
                  ("email:" + request.form.get("email", "").strip().lower(), 25)]
    for identity, limit in identities:
        key = hashlib.sha256(identity.encode()).hexdigest()
        db.session.execute(text("""INSERT INTO login_throttle (key, bucket, attempts)
            VALUES (:key, :bucket, 1)
            ON CONFLICT (key) DO UPDATE SET
            attempts = CASE WHEN login_throttle.bucket = :bucket THEN login_throttle.attempts + 1 ELSE 1 END,
            bucket = :bucket"""), {"key": key, "bucket": bucket})
        count = db.session.execute(text("SELECT attempts FROM login_throttle WHERE key=:key"), {"key": key}).scalar_one()
        db.session.commit()
        if count > limit:
            abort(429, "Muitas tentativas. Aguarde 15 minutos antes de tentar novamente.")


def init_security(app):
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def protect():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            expected = session.get("csrf", "")
            actual = request.form.get("csrf_token") or request.headers.get("X-CSRFToken", "")
            if not expected or not secrets.compare_digest(expected, actual):
                abort(400, "Sessão expirada ou formulário inválido. Recarregue a página.")
            for name in ("website", "external_url", "external_video_url", "url"):
                value = request.form.get(name, "").strip()
                if value and (urlsplit(value).scheme not in {"http", "https"} or not urlsplit(value).netloc):
                    abort(400, "Links devem usar http:// ou https://.")
        if request.path.startswith("/admin") and request.endpoint != "admin.login" and current_user.is_authenticated:
            from .models import User
            user = db.session.get(User, int(current_user.id))
            if not user or not user.is_active:
                session.clear()
                abort(403, "Esta conta está desativada.")

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if current_app.config.get("PRODUCTION"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.path.startswith("/admin"):
            response.headers["Cache-Control"] = "no-store"
        return response

    from werkzeug.exceptions import HTTPException

    @app.errorhandler(HTTPException)
    def error(exc):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(error=exc.description), exc.code
        return exc
