"""Данные из приложений здоровья (Health Connect), которые присылает приложение Del Health для Android.

Подключение — отдельное согласие (health_connections). Без него и без входа данные не принимаются.
Запросы JSON, защита от CSRF — заголовок X-CSRF-Token (токен из data-csrf страницы настроек).
Пока данные только хранятся и показываются в кабинете, в расчёт индекса они не попадают.
"""
import hmac
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, flash, g, jsonify, redirect, request, session, url_for

from .auth import check_csrf
from .consent import POLICY_VERSION
from .db import get_db

bp = Blueprint("health_sync", __name__)

SOURCES = {"health_connect"}
MAX_DAYS = 31
# (поле, минимум, максимум, целое?)
FIELDS = (("steps", 0, 200_000, True), ("sleep_minutes", 0, 1440, True),
          ("exercise_minutes", 0, 1440, True), ("heart_rate_avg", 20, 250, False))


def clean_day(raw, today):
    """Проверенный день {date, поля…} или None, если дата неверна или нет ни одного показателя."""
    if not isinstance(raw, dict):
        return None
    try:
        day = date.fromisoformat(raw.get("date", ""))
    except (TypeError, ValueError):
        return None
    if day > today or day < today - timedelta(days=MAX_DAYS):
        return None
    out = {"date": day.isoformat()}
    for name, low, high, integer in FIELDS:
        value = raw.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if not low <= value <= high:
            continue
        out[name] = int(round(value)) if integer else round(float(value), 1)
    return out if len(out) > 1 else None


def overview(user_id, days=7):
    """Подключение и последние дни для страницы настроек."""
    db = get_db()
    conn = db.execute("SELECT * FROM health_connections WHERE user_id = ?", (user_id,)).fetchone()
    rows = db.execute("SELECT * FROM health_sync_days WHERE user_id = ? ORDER BY date DESC LIMIT ?",
                      (user_id, days)).fetchall() if conn else []
    return {"connected": conn is not None, "connected_at": conn["connected_at"] if conn else None,
            "last_sync_at": conn["last_sync_at"] if conn else None, "days": [dict(r) for r in rows]}


def _api_guard():
    """Ответ-ошибка для JSON API или None, если запрос можно выполнять."""
    if g.user is None:
        return jsonify(error="login_required"), 401
    sent = request.headers.get("X-CSRF-Token", "")
    if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
        return jsonify(error="csrf"), 400
    return None


@bp.post("/api/health-sync/connect")
def connect():
    if (err := _api_guard()):
        return err
    data = request.get_json(silent=True) or {}
    if data.get("consent") is not True:
        return jsonify(error="consent_required"), 400
    source = data.get("source", "health_connect")
    if source not in SOURCES:
        return jsonify(error="bad_source"), 400
    db = get_db()
    db.execute("INSERT INTO health_connections (user_id, source, consent_version) VALUES (?, ?, ?)"
               " ON CONFLICT(user_id) DO UPDATE SET source = excluded.source, consent_version = excluded.consent_version",
               (g.user["id"], source, POLICY_VERSION))
    db.commit()
    return jsonify(ok=True)


@bp.post("/api/health-sync")
def sync():
    if (err := _api_guard()):
        return err
    db = get_db()
    if db.execute("SELECT 1 FROM health_connections WHERE user_id = ?", (g.user["id"],)).fetchone() is None:
        return jsonify(error="not_connected"), 403
    raw_days = (request.get_json(silent=True) or {}).get("days")
    if not isinstance(raw_days, list) or len(raw_days) > MAX_DAYS + 1:
        return jsonify(error="bad_request"), 400
    today = datetime.now(timezone.utc).date() + timedelta(days=1)  # запас на часовые пояса
    days = [d for d in (clean_day(r, today) for r in raw_days) if d]
    for d in days:
        db.execute(
            "INSERT INTO health_sync_days (user_id, date, steps, sleep_minutes, exercise_minutes, heart_rate_avg)"
            " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, date) DO UPDATE SET"
            " steps = excluded.steps, sleep_minutes = excluded.sleep_minutes,"
            " exercise_minutes = excluded.exercise_minutes, heart_rate_avg = excluded.heart_rate_avg,"
            " synced_at = datetime('now')",
            (g.user["id"], d["date"], d.get("steps"), d.get("sleep_minutes"), d.get("exercise_minutes"),
             d.get("heart_rate_avg")))
    db.execute("UPDATE health_connections SET last_sync_at = datetime('now') WHERE user_id = ?", (g.user["id"],))
    db.commit()
    return jsonify(ok=True, saved=len(days))


@bp.post("/account/health/disconnect")
def disconnect():
    if g.user is None:
        return redirect(url_for("auth.login", next=request.path))
    check_csrf()
    db = get_db()
    db.execute("DELETE FROM health_sync_days WHERE user_id = ?", (g.user["id"],))
    db.execute("DELETE FROM health_connections WHERE user_id = ?", (g.user["id"],))
    db.commit()
    flash("Подключение отключено, данные из приложений здоровья удалены.")
    return redirect(url_for("account.settings") + "#health-sync")
