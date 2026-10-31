"""Отчёт месяца по e-mail: раз в месяц Plus-подписчикам, которые сами включили рассылку.

Письмо уходит один раз за календарный месяц (по Москве), команда `flask send-monthly` запускается по расписанию
раз в сутки. Согласие — users.report_opt_in, отписка — ссылка в письме (та же, что у остальных писем).
"""
import html
import os
from datetime import datetime, timedelta, timezone

import click
from flask import Blueprint, current_app, flash, g, redirect, request, url_for

from . import mailer
from .account import _load_results, report_data
from .auth import check_csrf
from .db import get_db
from .plus import FMT, plus_required, report_required, unsubscribe_token

bp = Blueprint("monthly", __name__)

MSK = timedelta(hours=3)


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def month_key(now=None):
    return ((now or _utcnow()) + MSK).strftime("%Y-%m")


@bp.post("/account/report-mail")
@plus_required
def set_report_mail():
    check_csrf()
    on = 1 if request.form.get("report") == "on" else 0
    get_db().execute("UPDATE users SET report_opt_in = ? WHERE id = ?", (on, g.user["id"]))
    get_db().commit()
    flash("Отчёт месяца будет приходить на e-mail." if on else "Рассылка отчёта месяца выключена.")
    return redirect(url_for("account.dashboard") + "#plus")


SEND_LIMIT_PER_DAY = 3


@bp.post("/account/report/send")
@report_required
def send_report_now():
    """Отправить отчёт на e-mail аккаунта по кнопке. Адрес берётся только из аккаунта; не больше SEND_LIMIT_PER_DAY в сутки."""
    check_csrf()
    back = redirect(request.form.get("back") if (request.form.get("back") or "").startswith("/account") else url_for("account.report"))
    if not mailer.configured():
        flash("Отправка писем пока не настроена. Отчёт можно сохранить в PDF.", "error")
        return back
    db = get_db()
    sent_today = db.execute("SELECT count(*) FROM report_sends WHERE user_id = ? AND sent_at > datetime('now', '-1 day')",
                            (g.user["id"],)).fetchone()[0]
    if sent_today >= SEND_LIMIT_PER_DAY:
        flash("Сегодня вы уже отправляли отчёт несколько раз. Попробуйте завтра.", "error")
        return back
    data = report_data(g.user, _load_results(g.user["id"]))
    if data is None:
        flash("Отчёт появится после первой оценки по действующей методике.", "error")
        return back
    unsub = url_for("plus.unsubscribe", token=unsubscribe_token(g.user["id"]), _external=True)
    page, text = _email(g.user["name"], data, request.url_root, unsub)
    ok, info = mailer.send_email(g.user["email"], g.user["name"], "Ваш отчёт — Del Health", page, text, unsubscribe_url=unsub)
    if not ok:
        current_app.logger.warning("report not sent (user %s): %s", g.user["id"], info)
        flash("Не удалось отправить письмо. Попробуйте позже или сохраните отчёт в PDF.", "error")
        return back
    db.execute("INSERT INTO report_sends (user_id) VALUES (?)", (g.user["id"],))
    db.commit()
    flash(f"Отчёт отправлен на {g.user['email']}.")
    return back


def due_monthly(now=None):
    """Plus-подписчики с включённым отчётом, у которых есть оценка и нет письма за этот месяц."""
    now = now or _utcnow()
    db = get_db()
    month = month_key(now)
    out = []
    users = db.execute("SELECT * FROM users WHERE report_opt_in = 1 AND plus_until > ?", (now.strftime(FMT),)).fetchall()
    for u in users:
        if db.execute("SELECT 1 FROM monthly_mail WHERE user_id = ? AND month = ?", (u["id"], month)).fetchone():
            continue
        data = report_data(u, _load_results(u["id"]))
        if data is None:
            continue
        out.append({"user": u, "data": data})
    return out


def _summary(data):
    """Короткие факты для письма: итог, рост, резерв, шаги, пульс."""
    gain = max(data["spheres"], key=lambda s: s["delta_prev"] if s["delta_prev"] is not None else -999)
    weak = min(data["spheres"], key=lambda s: s["now"])
    lines = [f"Итог: {data['now']['total']} из 100"
             + (f" ({data['delta_prev']:+d} к прошлой оценке)" if data["delta_prev"] else "")]
    if gain["delta_prev"] and gain["delta_prev"] > 0:
        lines.append(f"Сильнее всего выросла сфера «{gain['name']}»: {gain['delta_prev']:+d}")
    lines.append(f"Больше всего резерва: «{weak['name']}», сейчас {weak['now']}")
    lines.append(f"Шагов плана выполнено: {data['plan_done']} из {len(data['plan'])}")
    if data["pulses"]:
        lines.append(f"Пульс недели: {data['pulses'][-1]}"
                     + (f" ({data['pulse_delta']:+d} за период)" if data["pulse_delta"] else ""))
    return lines


def _email(name, data, site, unsub):
    link = site.rstrip("/") + "/account/report"
    facts = _summary(data)
    hi = f"{name}, " if name else ""
    text = "\n".join([f"Здравствуйте! {hi}ваш отчёт за месяц.", ""] + facts +
                     ["", f"Полный отчёт и печать в PDF: {link}", "",
                      "Это образовательный индекс, не диагноз.", f"Отписаться от писем: {unsub}"])
    safe = html.escape
    page = (f"<p>Здравствуйте! {safe(hi)}ваш отчёт за месяц.</p><ul>"
            + "".join(f"<li>{safe(f)}</li>" for f in facts) + "</ul>"
            f'<p><a href="{safe(link)}">Открыть полный отчёт</a> (можно сохранить в PDF).</p>'
            f'<p style="color:#6A665D;font-size:13px">Это образовательный индекс, не диагноз. '
            f'<a href="{safe(unsub)}">Отписаться от писем</a></p>')
    return page, text


def send_monthly(site_url, send=None, dry_run=False, now=None):
    """→ (отправлено, ошибок, к отправке в dry-run). Неудачная отправка не записывается и повторится при следующем запуске."""
    send = send or mailer.send_email
    db = get_db()
    ok = bad = dry = 0
    month = month_key(now)
    for item in due_monthly(now):
        u = item["user"]
        unsub = site_url.rstrip("/") + url_for("plus.unsubscribe", token=unsubscribe_token(u["id"]))
        page, text = _email(u["name"], item["data"], site_url, unsub)
        if dry_run:
            dry += 1
            continue
        sent, info = send(u["email"], u["name"], "Ваш отчёт за месяц — Del Health", page, text, unsubscribe_url=unsub)
        if sent:
            db.execute("INSERT OR IGNORE INTO monthly_mail (user_id, month) VALUES (?, ?)", (u["id"], month))
            db.commit()
            ok += 1
        else:
            bad += 1
            current_app.logger.warning("monthly mail not sent (user %s): %s", u["id"], info)
    return ok, bad, dry


@click.command("send-monthly")
@click.option("--dry-run", is_flag=True, help="Только посчитать, письма не отправлять.")
def send_monthly_command(dry_run):
    """Отправить отчёт месяца подписчикам Plus (запускать раз в сутки; письмо уходит один раз за календарный месяц)."""
    site = os.environ.get("SITE_URL", "").strip()
    if not site:
        raise click.ClickException("Задайте SITE_URL (например https://example.pythonanywhere.com).")
    if not dry_run and not mailer.configured():
        raise click.ClickException("Не заданы BREVO_API_KEY и BREVO_SENDER_EMAIL.")
    with current_app.test_request_context(base_url=site):
        ok, bad, dry = send_monthly(site, dry_run=dry_run)
    click.echo(f"Отправлено: {ok}, ошибок: {bad}" + (f", к отправке (dry-run): {dry}" if dry_run else ""))
