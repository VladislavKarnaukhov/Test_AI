"""SQLite: соединение на запрос, схема и запись событий."""
import json
import os
import sqlite3

from flask import current_app, g, request, session

from .consent import analytics_allowed

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visitor_id TEXT,
    name TEXT NOT NULL,
    path TEXT,
    referrer TEXT,
    payload TEXT,
    ip TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visitor_id TEXT,
    email TEXT NOT NULL,
    plan TEXT NOT NULL,
    policy_version TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS score_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visitor_id TEXT,
    answers TEXT NOT NULL,
    total INTEGER NOT NULL,
    breakdown TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS cookie_consents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visitor_id TEXT,
    choice TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_visitor ON events(visitor_id);
CREATE INDEX IF NOT EXISTS idx_events_name ON events(name);
"""


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    if "db" not in g:
        g.db = _connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    path = app.config["DATABASE_PATH"]
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = _connect(path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()
    app.teardown_appcontext(close_db)


def _migrate(conn):
    # Колонки, добавленные после первого деплоя: CREATE TABLE IF NOT EXISTS их не создаст
    lead_columns = {row["name"] for row in conn.execute("PRAGMA table_info(leads)")}
    if "policy_version" not in lead_columns:
        conn.execute("ALTER TABLE leads ADD COLUMN policy_version TEXT")


def to_json(value):
    return json.dumps(value, ensure_ascii=False)


def log_event(name, payload=None, path=None, referrer=None):
    """Пишет событие в лог, только если посетитель согласился на аналитические cookie."""
    if not analytics_allowed():
        return
    db = get_db()
    db.execute(
        "INSERT INTO events (visitor_id, name, path, referrer, payload, ip, user_agent)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            session.get("visitor_id"),
            name,
            path if path is not None else request.path,
            referrer if referrer is not None else request.referrer,
            to_json(payload) if payload is not None else None,
            request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip() or None,
            (request.user_agent.string or None),
        ),
    )
    db.commit()
