import sqlite3

import pytest

from app import create_app
from app.consent import POLICY_VERSION


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE_PATH": str(tmp_path / "test.db")})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def consented(client):
    """Посетитель, который нажал «Принять все»."""
    client.set_cookie("vs_consent", "all")
    client.set_cookie("vs_consent_v", POLICY_VERSION)
    return client


@pytest.fixture
def query(app):
    def run(sql, *args):
        conn = sqlite3.connect(app.config["DATABASE_PATH"])
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]
        finally:
            conn.close()
    return run
