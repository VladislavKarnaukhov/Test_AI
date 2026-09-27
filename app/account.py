"""Личный кабинет: интерактивная история оценок, рекомендации и профиль."""
import json
from datetime import datetime, timedelta

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from .auth import (NAME_MAX, check_csrf, hash_password, login_user, login_required, logout_user,
                   validate_password)
from .db import get_db
from .scoring import SPHERE_NAMES, WEIGHTS, build_recommendations, describe_answers, summary_for

bp = Blueprint("account", __name__, url_prefix="/account")

MSK = timedelta(hours=3)
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
          "октября", "ноября", "декабря")


def to_msk(value, fmt="%d.%m.%Y"):
    """created_at в SQLite хранится в UTC; на страницах показываем московское время."""
    if not value:
        return ""
    return (datetime.strptime(value, "%Y-%m-%d %H:%M:%S") + MSK).strftime(fmt)


def human_date(value):
    """«27 сентября 2026, 14:05» по Москве."""
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S") + MSK
    return f"{dt.day} {MONTHS[dt.month - 1]} {dt.year}, {dt:%H:%M}"


def plural(n, one, few, many):
    """plural(3, "оценка", "оценки", "оценок") → "оценки"."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else many


def score_level(total):
    return "high" if total >= 80 else "mid" if total >= 60 else "low"


def group_recommendations(recs):
    """[{sphere, sphere_name, level, level_name, recs}] в исходном порядке — от самой слабой сферы."""
    groups = []
    for rec in recs:
        if not groups or groups[-1]["sphere"] != rec["sphere"]:
            groups.append({k: rec[k] for k in ("sphere", "sphere_name", "level", "level_name")} | {"recs": []})
        groups[-1]["recs"].append(rec)
    return groups


def _load_results(user_id):
    """Оценки клиента по возрастанию даты — со словесными ответами и изменениями к предыдущей."""
    rows = get_db().execute(
        "SELECT id, answers, total, breakdown, recommendations, created_at FROM score_results"
        " WHERE user_id = ? ORDER BY created_at, id", (user_id,)).fetchall()
    results, previous = [], None
    for number, row in enumerate(rows, start=1):
        breakdown = json.loads(row["breakdown"])
        recs = json.loads(row["recommendations"]) if row["recommendations"] else build_recommendations(breakdown)
        results.append({
            "id": row["id"],
            "number": number,
            "created_at": row["created_at"],
            "date": human_date(row["created_at"]),
            "total": row["total"],
            "level": score_level(row["total"]),
            "summary": summary_for(row["total"]),
            "breakdown": breakdown,
            "answers": describe_answers(json.loads(row["answers"])),
            "groups": group_recommendations(recs),
            "delta": None if previous is None else row["total"] - previous["total"],
            "sphere_deltas": {k: None if previous is None else breakdown[k] - previous["breakdown"][k]
                              for k in WEIGHTS},
        })
        previous = {"total": row["total"], "breakdown": breakdown}
    return results


def chart_data(results):
    """Минимум данных для интерактивного графика в браузере."""
    return [{"id": r["id"], "t": r["created_at"].replace(" ", "T") + "Z", "label": to_msk(r["created_at"], "%d.%m"),
             "date": r["date"], "total": r["total"], **r["breakdown"]} for r in results]


def history_stats(results):
    totals = [r["total"] for r in results]
    return {"count": len(totals), "best": max(totals), "avg": round(sum(totals) / len(totals)),
            "change": totals[-1] - totals[0] if len(totals) > 1 else None}


@bp.before_request
def protect_forms():
    if request.method == "POST":
        check_csrf()


@bp.get("")
@login_required
def dashboard():
    user = g.user
    results = _load_results(user["id"])
    leads = get_db().execute(
        "SELECT plan, email, created_at FROM leads WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)
    ).fetchall()
    latest = results[-1] if results else None
    return render_template(
        "account/dashboard.html",
        user=user,
        results=list(reversed(results)),
        latest=latest,
        stats=history_stats(results) if results else None,
        chart_data=chart_data(results),
        leads=leads,
        sphere_names=SPHERE_NAMES,
    )


@bp.post("/profile")
@login_required
def update_profile():
    name = request.form.get("name", "").strip()
    if not name or len(name) > NAME_MAX:
        flash(f"Имя — от 1 до {NAME_MAX} символов.", "error")
    else:
        db = get_db()
        db.execute("UPDATE users SET name = ? WHERE id = ?", (name, g.user["id"]))
        db.commit()
        flash("Имя сохранено.")
    return redirect(url_for("account.dashboard") + "#profile")


@bp.post("/password")
@login_required
def change_password():
    form = request.form
    if not check_password_hash(g.user["password_hash"], form.get("current_password", "")):
        flash("Текущий пароль указан неверно.", "error")
    else:
        error = validate_password(form.get("password", ""), form.get("password_confirm", ""))
        if error:
            flash(error, "error")
        else:
            db = get_db()
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                       (hash_password(form["password"]), g.user["id"]))
            user = db.execute("SELECT * FROM users WHERE id = ?", (g.user["id"],)).fetchone()
            login_user(user)  # эта сессия остаётся, остальные устройства будут разлогинены
            db.commit()
            flash("Пароль изменён. На других устройствах нужно будет войти заново.")
    return redirect(url_for("account.dashboard") + "#security")


@bp.post("/delete")
@login_required
def delete_account():
    user = g.user
    if not check_password_hash(user["password_hash"], request.form.get("password", "")):
        flash("Пароль указан неверно — аккаунт не удалён.", "error")
        return redirect(url_for("account.dashboard") + "#danger")
    db = get_db()
    db.execute("DELETE FROM score_results WHERE user_id = ?", (user["id"],))
    db.execute("DELETE FROM leads WHERE user_id = ?", (user["id"],))
    db.execute("DELETE FROM login_attempts WHERE email = ?", (user["email"],))
    visitor_id = session.get("visitor_id")
    if visitor_id:
        for table in ("events", "visitors", "cookie_consents"):
            db.execute(f"DELETE FROM {table} WHERE visitor_id = ?", (visitor_id,))
    db.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    db.commit()
    logout_user()
    session.pop("visitor_id", None)
    flash("Аккаунт и все связанные с ним данные удалены.")
    return redirect(url_for("main.index"))
