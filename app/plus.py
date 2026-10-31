"""Del Health Plus (99 ₽ в месяц): план на месяц с отметками, сравнение оценок, напоминания по e-mail.

Доступ определяет users.plus_until (UTC). Пока нет онлайн-оплаты, доступ выдаёт администратор на странице /admin;
позже его сможет выставлять вебхук платёжного провайдера. Всё платное проверяется на сервере (plus_required).
"""
import html
import os
from datetime import datetime, timedelta, timezone
from functools import wraps

import click
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeSerializer

from . import mailer
from .auth import check_csrf, login_required
from .db import get_db
from .results import SELECT_COLUMNS, present
from .scoring import CORE_DOMAINS, DOMAIN_SHORT

bp = Blueprint("plus", __name__)

PRICE_RUB = 99
TRIAL_DAYS = 7
PLAN_SIZE = 3
REMIND_AFTER_DAYS = 21      # первое напоминание: столько дней после последней оценки
REMIND_REPEAT_DAYS = 14     # повтор, если человек так и не вернулся
REMIND_MAX_PER_RESULT = 2
FMT = "%Y-%m-%d %H:%M:%S"


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_plus(user):
    until = user["plus_until"] if user is not None and "plus_until" in user.keys() else None
    return bool(until) and datetime.strptime(until, FMT) > _now()


def grant(user_id, days=30):
    """Продлевает Plus: от текущего конца срока (если он ещё идёт) или от сейчас."""
    row = get_db().execute("SELECT plus_until FROM users WHERE id = ?", (user_id,)).fetchone()
    start = _now()
    if row and row["plus_until"]:
        start = max(start, datetime.strptime(row["plus_until"], FMT))
    until = (start + timedelta(days=days)).strftime(FMT)
    get_db().execute("UPDATE users SET plus_until = ?, plus_is_trial = 0 WHERE id = ?", (until, user_id))
    get_db().commit()
    return until


def grant_trial(user_id, days=TRIAL_DAYS):
    """Пробный период: один раз на аккаунт и только тем, у кого сейчас нет Plus. → дата окончания или None."""
    db = get_db()
    row = db.execute("SELECT plus_until, trial_used_at FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or row["trial_used_at"] or is_plus(row):
        return None
    until = (_now() + timedelta(days=days)).strftime(FMT)
    db.execute("UPDATE users SET plus_until = ?, plus_is_trial = 1, trial_used_at = ? WHERE id = ?",
               (until, _now().strftime(FMT), user_id))
    db.commit()
    return until


def revoke(user_id):
    get_db().execute("UPDATE users SET plus_until = NULL, plus_is_trial = 0, reminders_opt_in = 0, report_opt_in = 0 WHERE id = ?", (user_id,))
    get_db().commit()


def plus_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not is_plus(g.user):
            flash("Эта функция входит в Del Health Plus.", "error")
            return redirect(url_for("account.dashboard") + "#plus")
        return view(*args, **kwargs)
    return wrapped


# ---------- План на месяц ----------

def build_plan(recommendations):
    """3 шага по приоритету: по одному на сферу, начиная с самой слабой; «поддерживайте» и пустые шаги — в последнюю очередь."""
    seen, steps = set(), []
    def filler(r):          # «Поддерживайте» без конкретного шага (item = None) — только если больше нечего предложить
        return "item" in r and r["item"] is None
    ordered = sorted(recommendations, key=lambda r: (filler(r), r.get("level") == "high"))
    for rec in ordered:
        if rec["sphere"] in seen:
            continue
        seen.add(rec["sphere"])
        steps.append({"sphere": rec["sphere"], "sphere_name": rec.get("sphere_name", rec["sphere"]),
                      "level_name": rec.get("level_name", ""), "title": rec["title"], "text": rec["text"]})
        if len(steps) == PLAN_SIZE:
            break
    return steps


def plan_for(user_id, result):
    """План по оценке `result` (словарь из account._load_results) и отметки о выполнении."""
    steps = build_plan(result["recommendations"])
    done = {r["idx"] for r in get_db().execute(
        "SELECT idx FROM plan_steps WHERE result_id = ? AND user_id = ?", (result["id"], user_id)).fetchall()}
    scores = result.get("breakdown") or {}
    for i, s in enumerate(steps):
        s["idx"], s["done"], s["score"] = i, i in done, scores.get(s["sphere"])
    return steps


def compare_rows(results):
    """Сравнение по действующей методике: сначала / прошлая / сейчас / лучшая — итог и сферы."""
    cur = [r for r in results if r["current"]]
    if len(cur) < 2:
        return None
    def row(key, name, getter):
        vals = [getter(r) for r in cur]
        return {"key": key, "name": name, "first": vals[0], "prev": vals[-2], "now": vals[-1], "best": max(vals),
                "delta": vals[-1] - vals[-2]}
    rows = [row("total", "Итог", lambda r: r["total"])]
    rows += [row(k, DOMAIN_SHORT[k], lambda r, k=k: r["breakdown"].get(k, 0)) for k in CORE_DOMAINS]
    return rows


@bp.post("/account/plan/<int:result_id>/<int:idx>")
@plus_required
def toggle_step(result_id, idx):
    check_csrf()
    row = get_db().execute(f"SELECT {SELECT_COLUMNS} FROM score_results WHERE id = ? AND user_id = ?",
                           (result_id, g.user["id"])).fetchone()
    if row is None or idx >= len(build_plan(present(row)["recommendations"])):
        abort(404)
    db = get_db()
    cur = db.execute("DELETE FROM plan_steps WHERE result_id = ? AND idx = ? AND user_id = ?", (result_id, idx, g.user["id"]))
    if not cur.rowcount:
        db.execute("INSERT INTO plan_steps (result_id, idx, user_id) VALUES (?, ?, ?)", (result_id, idx, g.user["id"]))
        db.commit()
        from .engage import record
        record(g.user["id"], "step")
    db.commit()
    return redirect(url_for("account.dashboard") + "#plus")


# ---------- Напоминания ----------

@bp.post("/account/reminders")
@plus_required
def set_reminders():
    check_csrf()
    on = 1 if request.form.get("reminders") == "on" else 0
    get_db().execute("UPDATE users SET reminders_opt_in = ? WHERE id = ?", (on, g.user["id"]))
    get_db().commit()
    flash("Напоминания включены." if on else "Напоминания выключены.")
    return redirect(url_for("account.settings") + "#plus")


def _serializer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="unsubscribe")


def unsubscribe_token(user_id):
    return _serializer().dumps({"u": user_id})


@bp.get("/unsubscribe/<token>")
def unsubscribe(token):
    """Отписка по ссылке из письма: без входа, токен подписан SECRET_KEY."""
    try:
        user_id = _serializer().loads(token)["u"]
    except (BadSignature, KeyError, TypeError):
        abort(404)
    get_db().execute("UPDATE users SET reminders_opt_in = 0, weekly_opt_in = 0, report_opt_in = 0 WHERE id = ?", (user_id,))
    get_db().commit()
    return render_template("account/unsubscribed.html")


def _email_text(name, total, weeks, done, size, link, unsub):
    hi = f"{name}, " if name else ""
    text = (f"Здравствуйте! {hi}прошло около {weeks} нед. с вашей последней оценки (индекс {total}).\n\n"
            f"Выполнено шагов плана: {done} из {size}. Пройти анкету заново — 3–4 минуты: {link}\n\n"
            f"Это образовательный индекс, не диагноз. Отписаться от напоминаний: {unsub}\n")
    safe = html.escape
    page = (f"<p>Здравствуйте! {safe(hi)}прошло около {weeks} нед. с вашей последней оценки (индекс <b>{total}</b>).</p>"
            f"<p>Выполнено шагов плана: <b>{done} из {size}</b>.</p>"
            f'<p><a href="{safe(link)}">Пройти анкету заново</a> — 3–4 минуты, и вы увидите, что изменилось.</p>'
            f'<p style="color:#6A665D;font-size:13px">Это образовательный индекс, не диагноз. '
            f'<a href="{safe(unsub)}">Отписаться от напоминаний</a></p>')
    return page, text


def due_reminders(now=None):
    """Пользователи Plus с включёнными напоминаниями, которым пора напомнить (по последней оценке v2.0)."""
    now = now or _now()
    db = get_db()
    out = []
    users = db.execute("SELECT id, email, name FROM users WHERE reminders_opt_in = 1 AND weekly_opt_in = 0 AND plus_until > ?",
                       (now.strftime(FMT),)).fetchall()
    for u in users:
        last = db.execute("SELECT id, total, created_at FROM score_results WHERE user_id = ? AND method_version = '2.0' "
                          "ORDER BY created_at DESC, id DESC LIMIT 1", (u["id"],)).fetchone()
        if last is None:
            continue
        age = now - datetime.strptime(last["created_at"], FMT)
        if age < timedelta(days=REMIND_AFTER_DAYS):
            continue
        sent = db.execute("SELECT count(*) c, max(sent_at) m FROM reminders WHERE user_id = ? AND result_id = ?",
                          (u["id"], last["id"])).fetchone()
        if sent["c"] >= REMIND_MAX_PER_RESULT:
            continue
        if sent["m"] and now - datetime.strptime(sent["m"], FMT) < timedelta(days=REMIND_REPEAT_DAYS):
            continue
        out.append({"user": u, "result": last, "weeks": max(3, round(age.days / 7))})
    return out


def send_due_reminders(site_url, send=None, dry_run=False, now=None):
    """→ (отправлено, ошибок, пропущено в dry-run). send — подмена отправителя для тестов."""
    send = send or mailer.send_email
    db = get_db()
    ok = bad = dry = 0
    for item in due_reminders(now):
        u, last = item["user"], item["result"]
        row = db.execute(f"SELECT {SELECT_COLUMNS} FROM score_results WHERE id = ?", (last["id"],)).fetchone()
        steps = plan_for(u["id"], {"id": last["id"], "recommendations": present(row)["recommendations"]})
        done = sum(1 for s in steps if s["done"])
        link = site_url.rstrip("/") + "/#try"
        unsub = site_url.rstrip("/") + url_for("plus.unsubscribe", token=unsubscribe_token(u["id"]))
        page, text = _email_text(u["name"], last["total"], item["weeks"], done, len(steps), link, unsub)
        if dry_run:
            dry += 1
            continue
        sent, info = send(u["email"], u["name"], "Пора повторить анкету Del Health", page, text, unsubscribe_url=unsub)
        if sent:
            db.execute("INSERT INTO reminders (user_id, result_id) VALUES (?, ?)", (u["id"], last["id"]))
            db.commit()
            ok += 1
        else:
            bad += 1
            current_app.logger.warning("reminder not sent (user %s): %s", u["id"], info)
    return ok, bad, dry


@click.command("send-reminders")
@click.option("--dry-run", is_flag=True, help="Только посчитать, письма не отправлять.")
def send_reminders_command(dry_run):
    """Отправить напоминания пользователям Plus (запускать по расписанию раз в сутки)."""
    site = os.environ.get("SITE_URL", "").strip()
    if not site:
        raise click.ClickException("Задайте SITE_URL (например https://example.pythonanywhere.com).")
    if not dry_run and not mailer.configured():
        raise click.ClickException("Не заданы BREVO_API_KEY и BREVO_SENDER_EMAIL.")
    with current_app.test_request_context(base_url=site):
        ok, bad, dry = send_due_reminders(site, dry_run=dry_run)
    click.echo(f"Отправлено: {ok}, ошибок: {bad}" + (f", к отправке (dry-run): {dry}" if dry_run else ""))
