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
CREATE TABLE IF NOT EXISTS visitors (
    visitor_id TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen TEXT NOT NULL DEFAULT (datetime('now')),
    landing_path TEXT,
    referrer TEXT,
    source TEXT,
    utm_source TEXT,
    utm_medium TEXT,
    utm_campaign TEXT,
    utm_content TEXT,
    utm_term TEXT,
    language TEXT,
    timezone TEXT,
    country TEXT,
    screen TEXT,
    device_type TEXT,
    os TEXT,
    browser TEXT
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT,
    ip TEXT,
    success INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_email ON login_attempts(email, created_at);
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


# Колонки, добавленные после первого деплоя: CREATE TABLE IF NOT EXISTS их не создаст
MIGRATIONS = [
    ("leads", "policy_version", "TEXT"),
    ("leads", "user_id", "INTEGER REFERENCES users(id)"),
    ("score_results", "user_id", "INTEGER REFERENCES users(id)"),
    ("score_results", "recommendations", "TEXT"),
    ("score_results", "method_version", "TEXT"),        # NULL — старая формула (scoring_v0)
    ("score_results", "flags", "TEXT"),                 # красные флаги, JSON
    ("score_results", "focus", "TEXT"),                 # фокус недели, JSON
    ("score_results", "health_consent_version", "TEXT"),  # редакция политики, по которой дано согласие
]


def _migrate(conn):
    for table, column, decl in MIGRATIONS:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_user ON leads(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_score_results_user ON score_results(user_id, created_at)")


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
