import os
import uuid

from flask import Flask, session

from .consent import analytics_allowed
from .db import init_db


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

    from .routes import bp
    app.register_blueprint(bp)

    return app
