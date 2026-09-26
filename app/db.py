"""SQLite: соединение на запрос, схема и запись событий."""
import json
import os
import sqlite3

from flask import current_app, g, request, session

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
        conn.commit()
    finally:
        conn.close()
    app.teardown_appcontext(close_db)


def to_json(value):
    return json.dumps(value, ensure_ascii=False)


def log_event(name, payload=None, path=None, referrer=None):
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
