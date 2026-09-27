"""Личный кабинет: динамика оценок, рекомендации, профиль и управление данными."""
import json
from datetime import datetime, timedelta

from flask import Blueprint, Response, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from .auth import (NAME_MAX, check_csrf, hash_password, login_user, login_required, logout_user,
                   validate_password)
from .db import get_db
from .scoring import SPHERE_NAMES, WEIGHTS, build_recommendations, summary_for

bp = Blueprint("account", __name__, url_prefix="/account")

MSK = timedelta(hours=3)
CHART = {"width": 640, "height": 230, "left": 34, "right": 14, "top": 14, "bottom": 30}
CHART_LIMIT = 20
SERIES_COLORS = {"total": "#172d29", "sleep": "#4c9374", "activity": "#8fb339",
                 "nutrition": "#c98b3a", "recovery": "#6c8fb3"}


def to_msk(value, fmt="%d.%m.%Y"):
    """created_at в SQLite хранится в UTC; на страницах показываем московское время."""
    if not value:
        return ""
    return (datetime.strptime(value, "%Y-%m-%d %H:%M:%S") + MSK).strftime(fmt)


def _load_results(user_id):
    rows = get_db().execute(
        "SELECT id, answers, total, breakdown, recommendations, created_at FROM score_results"
        " WHERE user_id = ? ORDER BY created_at, id", (user_id,)).fetchall()
    results, previous = [], None
    for row in rows:
        breakdown = json.loads(row["breakdown"])
        recs = json.loads(row["recommendations"]) if row["recommendations"] else build_recommendations(breakdown)
        results.append({
            "id": row["id"],
            "created_at": row["created_at"],
            "total": row["total"],
            "breakdown": breakdown,
            "answers": json.loads(row["answers"]),
            "recommendations": recs,
            "delta": None if previous is None else row["total"] - previous,
        })
        previous = row["total"]
    return results


def group_recommendations(recs):
    """[{sphere, sphere_name, level, level_name, recs}] в исходном порядке — от самой слабой сферы."""
    groups = []
    for rec in recs:
        if not groups or groups[-1]["sphere"] != rec["sphere"]:
            groups.append({k: rec[k] for k in ("sphere", "sphere_name", "level", "level_name")} | {"recs": []})
        groups[-1]["recs"].append(rec)
    return groups


def build_chart(results):
    """Координаты линий для SVG-графика: итог и четыре сферы, последние CHART_LIMIT оценок."""
    points = results[-CHART_LIMIT:]
    c = CHART
    inner_w = c["width"] - c["left"] - c["right"]
    inner_h = c["height"] - c["top"] - c["bottom"]
    n = len(points)

    def x(i):
        return c["left"] + (inner_w / 2 if n == 1 else i * inner_w / (n - 1))

    def y(v):
        return c["top"] + (100 - v) * inner_h / 100

    series = []
    for key in ("total", *WEIGHTS):
        values = [p["total"] if key == "total" else p["breakdown"][key] for p in points]
        coords = [(round(x(i), 1), round(y(v), 1)) for i, v in enumerate(values)]
        series.append({
            "key": key,
            "name": "Итог" if key == "total" else SPHERE_NAMES[key],
            "color": SERIES_COLORS[key],
            "path": " ".join(f"{px},{py}" for px, py in coords),
            "dots": [{"x": px, "y": py, "value": v} for (px, py), v in zip(coords, values)],
        })
    grid = [{"y": round(y(v), 1), "label": v} for v in (0, 25, 50, 75, 100)]
    # подписи дат: не больше 6, чтобы не слипались
    step = max(1, -(-n // 6))
    labels = [{"x": round(x(i), 1), "text": to_msk(p["created_at"], "%d.%m")}
              for i, p in enumerate(points) if i % step == 0 or i == n - 1]
    return {**c, "series": series, "grid": grid, "labels": labels, "count": n, "hidden": len(results) - n}


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
        summary=summary_for(latest["total"]) if latest else None,
        groups=group_recommendations(latest["recommendations"]) if latest else [],
        chart=build_chart(results) if results else None,
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


@bp.get("/export")
@login_required
def export():
    user = g.user
    db = get_db()
    data = {
        "user": {"email": user["email"], "name": user["name"], "created_at": user["created_at"],
                 "policy_version": user["policy_version"]},
        "score_results": [
            {k: r[k] for k in ("created_at", "total", "breakdown", "answers", "recommendations")}
            for r in _load_results(user["id"])
        ],
        "leads": [dict(r) for r in db.execute(
            "SELECT email, plan, policy_version, created_at FROM leads WHERE user_id = ?", (user["id"],))],
    }
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=vitascore-data.json"},
    )


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
