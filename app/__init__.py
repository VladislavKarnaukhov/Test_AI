import os
import uuid

from flask import Flask, g, session, url_for

from .consent import POLICY_VERSION, analytics_allowed
from .db import init_db
from .scoring import METHOD_VERSION


def assign_visitor_id():
    session.permanent = True
    session["visitor_id"] = uuid.uuid4().hex


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        DATABASE_PATH=os.environ.get(
            "DATABASE_PATH", os.path.join(app.instance_path, "vitascore.db")
        ),
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
        # на сервере с HTTPS задайте SESSION_COOKIE_SECURE=1: cookie входа не уйдёт по http
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 365,
    )
    if config:
        app.config.update(config)

    init_db(app)

    @app.before_request
    def ensure_visitor_id():
        # Анонимный идентификатор — аналитическая cookie, выдаём только после согласия
        if analytics_allowed() and "visitor_id" not in session:
            assign_visitor_id()

    from . import account, auth, routes

    @app.before_request
    def load_user():
        auth.load_current_user()

    def static_url(filename):
        """Адрес статики с версией по времени изменения: после обновления браузер не возьмёт старый файл из кеша."""
        try:
            version = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            version = None
        return url_for("static", filename=filename, v=version)

    @app.context_processor
    def inject_globals():
        return {"policy_version": POLICY_VERSION, "current_user": g.get("user"),
                "csrf_token": auth.csrf_token, "static_url": static_url, "method_version": METHOD_VERSION}

    app.add_template_filter(account.to_msk, "msk")
    app.add_template_filter(account.plural, "plural")
    app.register_blueprint(routes.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(account.bp)

    return app
