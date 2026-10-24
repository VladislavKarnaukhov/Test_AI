"""Аналитический дашборд /admin. Доступ — только вошедшим пользователям из ADMIN_EMAILS (через запятую).

Показываются только агрегаты: ни e-mail, ни ответов анкеты, ни отдельных людей. Источники данных:
visitors / events / cookie_consents (только после согласия на аналитические cookie), score_results, users, leads
(эти три таблицы пишутся и без согласия на cookie, поэтому счётчики из них точнее воронки по событиям).
"""
import json
import os
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, g, render_template, request

from .db import get_db
from .scoring import DOMAIN_SHORT, TIER_NAMES

bp = Blueprint("admin", __name__, url_prefix="/admin")

PERIODS = {"7": 7, "30": 30, "90": 90, "all": None}
PERIOD_LABELS = {"7": "7 дней", "30": "30 дней", "90": "90 дней", "all": "Всё время"}
EVENT_LABELS = {
    "hero_start_quiz": "Главная: «Узнать свой индекс»", "header_start_quiz": "Шапка: «Пройти анкету»",
    "band_start_quiz": "Полоса: «Пройти анкету»", "calculate_score": "Анкета: «Рассчитать»",
    "quiz_restart": "Результат: «Пройти ещё раз»", "quiz_save_to_account": "Результат: «Войти и сохранять»",
    "quiz_open_account": "Результат: «Открыть кабинет»", "hero_user_card": "Главная: «Открыть кабинет»",
    "account_retake": "Кабинет: «Пройти анкету»", "account_delete_result": "Кабинет: удаление оценки",
    "header_login": "Шапка: «Войти»", "header_account": "Шапка: «Кабинет»",
}


DEFAULT_ADMINS = ("karnaukhovvlad@gmail.com",)


def admin_emails():
    """Администраторы: встроенный список + переменная окружения ADMIN_EMAILS (через запятую)."""
    extra = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
    return extra | set(DEFAULT_ADMINS)


def is_admin(user):
    return bool(user) and user["email"].lower() in admin_emails()


@bp.before_request
def only_admin():
    # посторонним — 404, чтобы не раскрывать существование раздела
    if not is_admin(g.user):
        abort(404)


def _rows(sql, args=()):
    return [dict(r) for r in get_db().execute(sql, args).fetchall()]


def _one(sql, args=()):
    row = get_db().execute(sql, args).fetchone()
    return row[0] if row and row[0] is not None else 0


def _pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def _since(period):
    days = PERIODS[period]
    return None if days is None else (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _days(since, until):
    start = datetime.strptime(since, "%Y-%m-%d %H:%M:%S").date()
    return [(start + timedelta(days=i)).isoformat() for i in range((until.date() - start).days + 1)]


def collect(period):
    since = _since(period)
    f = " AND created_at >= ?" if since else ""
    fv = " AND first_seen >= ?" if since else ""
    a = (since,) if since else ()

    # ---- ядро: то, что пишется всегда
    scores = _one(f"SELECT count(*) FROM score_results WHERE 1=1{f}", a)
    users = _one(f"SELECT count(*) FROM users WHERE 1=1{f}", a)
    leads = _one(f"SELECT count(*) FROM leads WHERE 1=1{f}", a)
    avg = _one(f"SELECT round(avg(total),1) FROM score_results WHERE method_version='2.0'{f}", a)
    visitors = _one(f"SELECT count(*) FROM visitors WHERE 1=1{fv}", a)
    views = _one(f"SELECT count(*) FROM events WHERE name='page_view'{f}", a)

    # ---- воронка по уникальным посетителям (только согласившиеся на аналитику)
    def uniq(name_sql):
        return _one(f"SELECT count(DISTINCT visitor_id) FROM events WHERE visitor_id IS NOT NULL AND {name_sql}{f}", a)
    funnel_raw = [
        ("Посетители (с согласием на cookie)", visitors),
        ("Начали анкету", uniq("name='quiz_answer'")),
        ("Дошли до 2-го вопроса и дальше", uniq("name='quiz_step'")),
        ("Получили результат", uniq("name='score_calculated'")),
        ("Зарегистрировались", uniq("name='account_registered'")),
        ("Оставили заявку на тариф", uniq("name='lead_submitted'")),
    ]
    funnel = []
    top = funnel_raw[0][1]
    for i, (label, n) in enumerate(funnel_raw):
        prev = funnel_raw[i - 1][1] if i else n
        funnel.append({"label": label, "n": n, "of_top": _pct(n, top), "of_prev": _pct(n, prev) if i else 100.0})

    # ---- ежедневные ряды
    end = datetime.now(timezone.utc).replace(tzinfo=None)
    first = since or (_one("SELECT min(day) FROM (SELECT min(created_at) AS day FROM score_results UNION ALL "
                           "SELECT min(first_seen) FROM visitors UNION ALL SELECT min(created_at) FROM events)") or "")
    first = first or end.strftime("%Y-%m-%d %H:%M:%S")
    days = _days(first[:10] + " 00:00:00", end)
    if len(days) > 120:
        days = days[-120:]
    def series(sql, args):
        got = {r["d"]: r["n"] for r in _rows(sql, args)}
        return [got.get(d, 0) for d in days]
    a2 = (days[0] + " 00:00:00",)
    daily = {
        "days": days,
        "visitors": series("SELECT substr(first_seen,1,10) d, count(*) n FROM visitors WHERE first_seen >= ? GROUP BY d", a2),
        "views": series("SELECT substr(created_at,1,10) d, count(*) n FROM events WHERE name='page_view' AND created_at >= ? GROUP BY d", a2),
        "scores": series("SELECT substr(created_at,1,10) d, count(*) n FROM score_results WHERE created_at >= ? GROUP BY d", a2),
        "users": series("SELECT substr(created_at,1,10) d, count(*) n FROM users WHERE created_at >= ? GROUP BY d", a2),
        "leads": series("SELECT substr(created_at,1,10) d, count(*) n FROM leads WHERE created_at >= ? GROUP BY d", a2),
    }

    # ---- анкета: уровни, баллы, слабые сферы, флаги
    tiers = [{"name": TIER_NAMES.get(r["tier"] or "", "старая методика"), "n": r["n"]} for r in _rows(
        f"SELECT tier, count(*) n FROM score_results WHERE 1=1{f} GROUP BY tier ORDER BY n DESC", a)]
    bands = {"low": "0–49", "mid": "50–79", "high": "80–100"}
    dist = {r["b"]: r["n"] for r in _rows(
        f"SELECT CASE WHEN total>=80 THEN 'high' WHEN total>=50 THEN 'mid' ELSE 'low' END b, count(*) n "
        f"FROM score_results WHERE method_version='2.0'{f} GROUP BY b", a)}
    levels = [{"label": bands[k], "key": k, "n": dist.get(k, 0)} for k in ("low", "mid", "high")]
    hist = {r["b"]: r["n"] for r in _rows(
        f"SELECT min(total/10,9) b, count(*) n FROM score_results WHERE method_version='2.0'{f} GROUP BY b", a)}
    histogram = [{"label": f"{i*10}–{i*10+9 if i < 9 else 100}", "n": hist.get(i, 0)} for i in range(10)]
    weakest = {}
    flags = {}
    for r in _rows(f"SELECT payload FROM events WHERE name='score_calculated'{f}", a):
        try:
            p = json.loads(r["payload"] or "{}")
        except ValueError:
            continue
        if p.get("weakest"):
            weakest[p["weakest"]] = weakest.get(p["weakest"], 0) + 1
        for code in p.get("flags") or []:
            flags[code] = flags.get(code, 0) + 1
    weakest_rows = sorted(({"name": DOMAIN_SHORT.get(k, k), "n": n} for k, n in weakest.items()), key=lambda x: -x["n"])
    flag_rows = sorted(({"name": k, "n": n} for k, n in flags.items()), key=lambda x: -x["n"])[:8]
    sphere_avg = []
    for key, name in DOMAIN_SHORT.items():
        v = _one(f"SELECT round(avg(json_extract(breakdown,'$.{key}')),1) FROM score_results WHERE method_version='2.0'{f}", a)
        if v:
            sphere_avg.append({"name": name, "v": v})

    # ---- аккаунты и возврат
    registered = _one("SELECT count(*) FROM users")
    repeat = _one("SELECT count(*) FROM (SELECT user_id FROM score_results WHERE user_id IS NOT NULL GROUP BY user_id HAVING count(*)>=2)")
    with_scores = _one("SELECT count(DISTINCT user_id) FROM score_results WHERE user_id IS NOT NULL")
    logins = _one(f"SELECT count(*) FROM events WHERE name='account_login'{f}", a)
    guest_scores = _one(f"SELECT count(*) FROM score_results WHERE user_id IS NULL{f}", a)
    account_scores = scores - guest_scores
    plans = _rows(f"SELECT plan, count(*) n FROM leads WHERE 1=1{f} GROUP BY plan ORDER BY n DESC", a)

    # ---- согласия
    consent = {r["choice"]: r["n"] for r in _rows(f"SELECT choice, count(*) n FROM cookie_consents WHERE 1=1{f} GROUP BY choice", a)}
    consent_total = sum(consent.values())

    # ---- трафик
    def top_visitors(col, limit=8, label="—"):
        return _rows(f"SELECT coalesce(nullif({col},''), ?) name, count(*) n FROM visitors WHERE 1=1{fv} GROUP BY 1 ORDER BY n DESC LIMIT {limit}", (label,) + a)
    sources = _rows(
        f"SELECT coalesce(nullif(v.source,''),'—') name, count(DISTINCT v.visitor_id) visitors, "
        f"count(DISTINCT s.id) scores, count(DISTINCT l.id) leads FROM visitors v "
        f"LEFT JOIN score_results s ON s.visitor_id=v.visitor_id LEFT JOIN leads l ON l.visitor_id=v.visitor_id "
        f"WHERE 1=1{fv.replace('first_seen','v.first_seen')} GROUP BY 1 ORDER BY visitors DESC LIMIT 10", a)
    for s in sources:
        s["conv"] = _pct(s["scores"], s["visitors"])
    campaigns = _rows(
        f"SELECT coalesce(utm_campaign,'—') campaign, coalesce(utm_source,'—') source, count(*) n FROM visitors "
        f"WHERE utm_source IS NOT NULL{fv} GROUP BY 1,2 ORDER BY n DESC LIMIT 8", a)
    pages = _rows(f"SELECT path name, count(*) n FROM events WHERE name='page_view' AND path IS NOT NULL{f} GROUP BY path ORDER BY n DESC LIMIT 8", a)
    clicks = _rows(
        f"SELECT name, count(*) n FROM events WHERE name NOT IN ('page_view','quiz_answer','quiz_step','score_calculated',"
        f"'cookie_consent','hashchange','anchor_click','link_click','account_registered','account_login','lead_submitted'){f} "
        f"GROUP BY name ORDER BY n DESC LIMIT 10", a)
    for c in clicks:
        c["label"] = EVENT_LABELS.get(c["name"], c["name"])
    quiz_drop = _rows(
        f"SELECT json_extract(payload,'$.step') step, count(DISTINCT visitor_id) n FROM events WHERE name='quiz_step'{f} GROUP BY 1 ORDER BY step", a)

    return {
        "period": period,
        "kpi": [
            {"label": "Посетители", "value": visitors, "hint": "с согласием на аналитику"},
            {"label": "Просмотры страниц", "value": views, "hint": "page_view"},
            {"label": "Анкет рассчитано", "value": scores, "hint": f"гостей {guest_scores}, из аккаунтов {account_scores}"},
            {"label": "Средний индекс", "value": avg or "—", "hint": "методика v2.0"},
            {"label": "Регистрации", "value": users, "hint": f"всего аккаунтов {registered}"},
            {"label": "Заявки на тариф", "value": leads, "hint": "по e-mail"},
            {"label": "Конверсия в результат", "value": f"{_pct(funnel_raw[3][1], visitors)}%", "hint": "посетитель → расчёт"},
            {"label": "Согласие на аналитику", "value": f"{_pct(consent.get('all', 0), consent_total)}%", "hint": f"ответов {consent_total}"},
        ],
        "funnel": funnel, "daily": daily, "tiers": tiers, "levels": levels, "histogram": histogram,
        "weakest": weakest_rows, "flags": flag_rows, "sphere_avg": sphere_avg,
        "retention": {"registered": registered, "with_scores": with_scores, "repeat": repeat,
                      "repeat_pct": _pct(repeat, with_scores), "logins": logins},
        "plans": plans, "consent": consent, "sources": sources, "campaigns": campaigns,
        "devices": top_visitors("device_type"), "os": top_visitors("os"), "browsers": top_visitors("browser"),
        "countries": top_visitors("country", label="?"), "languages": top_visitors("language"),
        "pages": pages, "clicks": clicks, "quiz_drop": quiz_drop,
    }


@bp.after_request
def no_index(resp):
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.get("")
def dashboard():
    period = request.args.get("period", "30")
    if period not in PERIODS:
        period = "30"
    data = collect(period)
    return render_template("admin/dashboard.html", d=data, periods=PERIOD_LABELS,
                           generated=(datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M"))
