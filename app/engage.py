"""Недельный ритм поверх месячного индекса: журнал активности (DAU/WAU/MAU), шаг недели,
«пульс» самочувствия за 30 секунд и недельное письмо с шагом недели.

Активным за день считается вошедший пользователь, который открыл кабинет (или вошёл в аккаунт), отметил шаг
(недели или плана) или прошёл недельную отметку. «Пульс» — самооценка, она не входит в индекс и не меняет расчёт.
Всё, что показывается пользователю, берётся только по g.user["id"].
"""
import html
import os
from datetime import datetime, timedelta, timezone

import click
from flask import Blueprint, current_app, flash, g, redirect, request, url_for

from . import mailer
from .auth import check_csrf, login_required
from .db import get_db
from .plus import unsubscribe_token
from .results import SELECT_COLUMNS, present

bp = Blueprint("engage", __name__)

KINDS = ("cabinet", "step", "pulse")
KIND_LABELS = {"cabinet": "Открыли кабинет", "step": "Отметили шаг", "pulse": "Прошли пульс"}
PULSE_FIELDS = (("sleep", "Сон"), ("activity", "Движение"), ("nutrition", "Питание"), ("mood", "Настроение"))
PULSE_WORDS = {1: "Плохо", 2: "Так себе", 3: "Нормально", 4: "Хорошо", 5: "Отлично"}
CHART_WEEKS = 26
REPEAT_ANKETA_DAYS = 21
MSK = timedelta(hours=3)
FMT = "%Y-%m-%d %H:%M:%S"


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today_utc(now=None):
    return (now or _utcnow()).strftime("%Y-%m-%d")


def week_start(now=None):
    """Понедельник текущей недели по Москве, 'YYYY-MM-DD'."""
    d = ((now or _utcnow()) + MSK).date()
    return (d - timedelta(days=d.weekday())).isoformat()


# ---------- Журнал активности и DAU / WAU / MAU ----------

def record(user_id, kind, now=None):
    """Одна запись на пользователя, день и вид действия."""
    get_db().execute("INSERT OR IGNORE INTO activity (user_id, day, kind) VALUES (?, ?, ?)",
                     (user_id, today_utc(now), kind))
    get_db().commit()


def _active(days_back, kind=None, end=None):
    """Уникальные пользователи с активностью за `days_back` дней, включая `end` (по умолчанию сегодня)."""
    end_day = end or today_utc()
    start = (datetime.strptime(end_day, "%Y-%m-%d") - timedelta(days=days_back - 1)).strftime("%Y-%m-%d")
    sql = "SELECT count(DISTINCT user_id) FROM activity WHERE day >= ? AND day <= ?"
    args = [start, end_day]
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    return get_db().execute(sql, args).fetchone()[0]


def activity_block(days):
    """Метрики активности для дашборда. `days` — список дат ряда по дням ('YYYY-MM-DD')."""
    dau, wau, mau = _active(1), _active(7), _active(30)
    daily = {r["day"]: r["n"] for r in get_db().execute(
        "SELECT day, count(DISTINCT user_id) AS n FROM activity WHERE day >= ? GROUP BY day", (days[0],)).fetchall()}
    today = datetime.strptime(today_utc(), "%Y-%m-%d")
    weeks = []
    for i in range(11, -1, -1):
        end = (today - timedelta(days=7 * i)).strftime("%Y-%m-%d")
        weeks.append({"label": (today - timedelta(days=7 * i)).strftime("%d.%m"), "n": _active(7, end=end)})
    return {
        "dau": dau, "wau": wau, "mau": mau,
        "dau_mau": round(100.0 * dau / mau, 1) if mau else 0.0,
        "wau_mau": round(100.0 * wau / mau, 1) if mau else 0.0,
        "by_kind": [{"name": KIND_LABELS[k], "n": _active(7, kind=k)} for k in KINDS],
        "dau_series": [daily.get(d, 0) for d in days],
        "wau_series": weeks,
    }


# ---------- Шаг недели (бесплатно) ----------

def week_step_done(user_id, now=None):
    return get_db().execute("SELECT 1 FROM week_steps WHERE user_id = ? AND week_start = ?",
                            (user_id, week_start(now))).fetchone() is not None


@bp.post("/account/week-step")
@login_required
def toggle_week_step():
    check_csrf()
    db = get_db()
    row = db.execute("SELECT id FROM score_results WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                     (g.user["id"],)).fetchone()
    if row is None:
        flash("Шаг недели появится после первой анкеты.", "error")
        return redirect(url_for("account.dashboard") + "#week")
    week = week_start()
    cur = db.execute("DELETE FROM week_steps WHERE user_id = ? AND week_start = ?", (g.user["id"], week))
    if not cur.rowcount:
        db.execute("INSERT INTO week_steps (user_id, week_start, result_id) VALUES (?, ?, ?)",
                   (g.user["id"], week, row["id"]))
        record(g.user["id"], "step")
    db.commit()
    return redirect(url_for("account.dashboard") + "#week")


# ---------- Пульс недели ----------

def pulse_score(row):
    """Среднее четырёх отметок 1–5, переведённое в 0–100."""
    avg = sum(row[k] for k, _ in PULSE_FIELDS) / len(PULSE_FIELDS)
    return round((avg - 1) / 4 * 100)


def this_week_pulse(user_id, now=None):
    row = get_db().execute("SELECT * FROM pulses WHERE user_id = ? AND week_start = ?",
                           (user_id, week_start(now))).fetchone()
    if row is None:
        return None
    return {"values": [{"key": k, "name": n, "value": row[k], "word": PULSE_WORDS[row[k]]} for k, n in PULSE_FIELDS],
            "score": pulse_score(row)}


@bp.post("/account/pulse")
@login_required
def submit_pulse():
    check_csrf()
    values = {}
    for key, _ in PULSE_FIELDS:
        try:
            v = int(request.form.get(key, ""))
        except ValueError:
            v = 0
        if not 1 <= v <= 5:
            flash("Отметьте все четыре сферы от 1 до 5.", "error")
            return redirect(url_for("account.dashboard") + "#week")
        values[key] = v
    db = get_db()
    if not g.user["pulse_consent_at"]:
        if request.form.get("pulse_consent") != "on":
            flash("Нужно согласие на обработку отметок о самочувствии.", "error")
            return redirect(url_for("account.dashboard") + "#week")
        db.execute("UPDATE users SET pulse_consent_at = datetime('now') WHERE id = ?", (g.user["id"],))
    db.execute(
        "INSERT INTO pulses (user_id, week_start, sleep, activity, nutrition, mood) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id, week_start) DO UPDATE SET sleep = excluded.sleep, activity = excluded.activity, "
        "nutrition = excluded.nutrition, mood = excluded.mood",
        (g.user["id"], week_start(), values["sleep"], values["activity"], values["nutrition"], values["mood"]))
    db.commit()
    record(g.user["id"], "pulse")
    flash("Пульс недели сохранён.")
    return redirect(url_for("account.dashboard") + "#week")


@bp.post("/account/pulse/delete")
@login_required
def delete_pulses():
    check_csrf()
    get_db().execute("DELETE FROM pulses WHERE user_id = ?", (g.user["id"],))
    get_db().execute("UPDATE users SET pulse_consent_at = NULL WHERE id = ?", (g.user["id"],))
    get_db().commit()
    flash("Все недельные отметки удалены.")
    return redirect(url_for("account.settings") + "#weekly")


def streak(user_id, now=None):
    """Недель подряд с шагом или пульсом. Текущая неделя без отметки серию не обрывает."""
    db = get_db()
    weeks = {r[0] for r in db.execute("SELECT week_start FROM pulses WHERE user_id = ? UNION "
                                      "SELECT week_start FROM week_steps WHERE user_id = ?", (user_id, user_id))}
    cur = datetime.strptime(week_start(now), "%Y-%m-%d").date()
    if cur.isoformat() not in weeks:
        cur -= timedelta(days=7)
    n = 0
    while cur.isoformat() in weeks:
        n += 1
        cur -= timedelta(days=7)
    return n


def pulse_chart(user_id, results, now=None):
    """Линия «пульса» между месячными замерами индекса. Чисто серверный SVG: → словарь для шаблона или None."""
    rows = get_db().execute("SELECT * FROM pulses WHERE user_id = ? ORDER BY week_start DESC LIMIT ?",
                            (user_id, CHART_WEEKS)).fetchall()
    if not rows:
        return None
    rows = list(reversed(rows))
    pulses = [{"d": datetime.strptime(r["week_start"], "%Y-%m-%d").date() + timedelta(days=3), "score": pulse_score(r),
               "words": ", ".join(f"{n.lower()} {r[k]}" for k, n in PULSE_FIELDS)} for r in rows]
    first = pulses[0]["d"]
    index = []
    for r in results:
        if not r["current"]:
            continue
        d = (datetime.strptime(r["created_at"], FMT) + MSK).date()
        if d >= first - timedelta(days=14):
            index.append({"d": d, "total": r["total"]})
    today = ((now or _utcnow()) + MSK).date()
    lo = min([first] + [i["d"] for i in index])
    hi = max([today, pulses[-1]["d"]] + [i["d"] for i in index])
    if (hi - lo).days < 28:
        lo = hi - timedelta(days=28)
    W, H, L, R, T, B = 640, 200, 34, 16, 14, 30
    span = max((hi - lo).days, 1)

    def x(d):
        return round(L + (W - L - R) * (d - lo).days / span, 1)

    def y(v):
        return round(T + (H - T - B) * (100 - v) / 100, 1)

    p_pts = [{"x": x(p["d"]), "y": y(p["score"]), "score": p["score"], "label": p["d"].strftime("%d.%m"),
              "words": p["words"]} for p in pulses]
    i_pts = [{"x": x(i["d"]), "y": y(i["total"]), "total": i["total"], "label": i["d"].strftime("%d.%m")} for i in index]
    return {"w": W, "h": H, "left": L, "right": W - R, "top": T, "bottom": H - B,
            "grid": [{"y": y(v), "v": v} for v in (0, 50, 100)],
            "pulse_line": " ".join(f"{p['x']},{p['y']}" for p in p_pts) if len(p_pts) > 1 else "",
            "pulse": p_pts, "index": i_pts,
            "ticks": [{"x": x(lo), "label": lo.strftime("%d.%m")}, {"x": x(hi), "label": hi.strftime("%d.%m")}]}


# ---------- Письма ----------

@bp.post("/account/weekly-mail")
@login_required
def set_weekly_mail():
    check_csrf()
    on = 1 if request.form.get("weekly") == "on" else 0
    get_db().execute("UPDATE users SET weekly_opt_in = ? WHERE id = ?", (on, g.user["id"]))
    get_db().commit()
    flash("Недельное письмо включено." if on else "Недельное письмо выключено.")
    return redirect(url_for("account.settings") + "#weekly")


def _weekly_email(name, step, weeks_since, streak_n, site, unsub, repeat):
    hi = f"{name}, " if name else ""
    link = site.rstrip("/") + "/account#week"
    lines = [f"Здравствуйте! {hi}ваш шаг на эту неделю.", "", f"{step['title']}", f"{step['text']}", "",
             f"Отметить шаг и пройти «пульс недели» (30 секунд): {link}"]
    if streak_n >= 2:
        lines += ["", f"Вы на связи уже {streak_n} нед. подряд."]
    if repeat:
        lines += ["", f"С последней анкеты прошло около {weeks_since} нед. — пора повторить: {site.rstrip('/')}/#try"]
    lines += ["", "Это образовательный индекс, не диагноз.", f"Отписаться от писем: {unsub}"]
    safe = html.escape
    page = (f"<p>Здравствуйте! {safe(hi)}ваш шаг на эту неделю:</p>"
            f"<p><b>{safe(step['title'])}</b><br>{safe(step['text'])}</p>"
            f'<p><a href="{safe(link)}">Отметить шаг и пройти «пульс недели»</a> — 30 секунд.</p>')
    if streak_n >= 2:
        page += f"<p>Вы на связи уже <b>{streak_n}</b> нед. подряд.</p>"
    if repeat:
        page += f'<p>С последней анкеты прошло около {weeks_since} нед. — <a href="{safe(site.rstrip("/"))}/#try">пора повторить</a>.</p>'
    page += (f'<p style="color:#6A665D;font-size:13px">Это образовательный индекс, не диагноз. '
             f'<a href="{safe(unsub)}">Отписаться от писем</a></p>')
    return page, "\n".join(lines)


def due_weekly(now=None):
    """Пользователи с включённым недельным письмом, у которых есть оценка и ещё нет письма на этой неделе."""
    db = get_db()
    week = week_start(now)
    out = []
    for u in db.execute("SELECT id, email, name FROM users WHERE weekly_opt_in = 1").fetchall():
        if db.execute("SELECT 1 FROM weekly_mail WHERE user_id = ? AND week_start = ?", (u["id"], week)).fetchone():
            continue
        row = db.execute(f"SELECT {SELECT_COLUMNS} FROM score_results WHERE user_id = ? "
                         "ORDER BY created_at DESC, id DESC LIMIT 1", (u["id"],)).fetchone()
        if row is None:
            continue
        r = present(row)
        step = r["focus"] or (r["recommendations"][0] if r["recommendations"] else None)
        if step is None:
            continue
        age = (now or _utcnow()) - datetime.strptime(row["created_at"], FMT)
        out.append({"user": u, "step": {"title": step["title"], "text": step["text"]},
                    "weeks": max(1, round(age.days / 7)), "repeat": age.days >= REPEAT_ANKETA_DAYS})
    return out


def send_weekly(site_url, send=None, dry_run=False, now=None):
    """→ (отправлено, ошибок, к отправке в dry-run). Неудачная отправка не записывается, повтор пройдёт при следующем запуске."""
    send = send or mailer.send_email
    db = get_db()
    ok = bad = dry = 0
    week = week_start(now)
    for item in due_weekly(now):
        u = item["user"]
        unsub = site_url.rstrip("/") + url_for("plus.unsubscribe", token=unsubscribe_token(u["id"]))
        page, text = _weekly_email(u["name"], item["step"], item["weeks"], streak(u["id"], now), site_url, unsub,
                                   item["repeat"])
        if dry_run:
            dry += 1
            continue
        sent, info = send(u["email"], u["name"], "Ваш шаг на эту неделю — Del Health", page, text, unsubscribe_url=unsub)
        if sent:
            db.execute("INSERT OR IGNORE INTO weekly_mail (user_id, week_start) VALUES (?, ?)", (u["id"], week))
            db.commit()
            ok += 1
        else:
            bad += 1
            current_app.logger.warning("weekly mail not sent (user %s): %s", u["id"], info)
    return ok, bad, dry


@click.command("send-weekly")
@click.option("--dry-run", is_flag=True, help="Только посчитать, письма не отправлять.")
def send_weekly_command(dry_run):
    """Отправить недельные письма с шагом недели (запускать по расписанию раз в сутки; письмо уходит один раз за неделю)."""
    site = os.environ.get("SITE_URL", "").strip()
    if not site:
        raise click.ClickException("Задайте SITE_URL (например https://example.pythonanywhere.com).")
    if not dry_run and not mailer.configured():
        raise click.ClickException("Не заданы BREVO_API_KEY и BREVO_SENDER_EMAIL.")
    with current_app.test_request_context(base_url=site):
        ok, bad, dry = send_weekly(site, dry_run=dry_run)
    click.echo(f"Отправлено: {ok}, ошибок: {bad}" + (f", к отправке (dry-run): {dry}" if dry_run else ""))
