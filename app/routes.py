import json
import re

from flask import Blueprint, g, jsonify, render_template, request, session

from . import assign_visitor_id
from .consent import (CONSENT_ALL, CONSENT_CHOICES, CONSENT_COOKIE, CONSENT_MAX_AGE,
                      CONSENT_VERSION_COOKIE, POLICY_VERSION, analytics_allowed)
from .db import get_db, log_event, to_json
from .results import SELECT_COLUMNS, present
from .scoring import (AEROBIC_TARGET, CRISIS_CONTACTS, INTENSITY, LEVELS, POINTS, SPHERE_NAMES, SPHERE_SHORT,
                      STEPS, ScoringError, calculate_score)
from .visitor import classify_source, guess_country, parse_user_agent, referrer_domain

bp = Blueprint("main", __name__)

PLANS = {"Start", "Balance"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EVENT_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8}){0,3}$")
TIMEZONE_RE = re.compile(r"^[A-Za-z_]+(/[A-Za-z0-9_+-]+){0,2}$")
SCREEN_RE = re.compile(r"^\d{2,5}x\d{2,5}$")
UTM_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
MAX_FIELD = 2048


def _json_body():
    data = request.get_json(silent=True)
    if data is None and request.data:
        # sendBeacon может прислать тело как text/plain
        try:
            data = json.loads(request.data)
        except ValueError:
            data = None
    return data if isinstance(data, dict) else None


def _clip(value):
    return str(value)[:MAX_FIELD] if value is not None else None


def _latest_score(user_id):
    """Последняя оценка вошедшего клиента для карточки на главной."""
    row = get_db().execute(
        f"SELECT {SELECT_COLUMNS} FROM score_results WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (user_id,)).fetchone()
    if row is None:
        return None
    return {**present(row), "created_at": row["created_at"]}


@bp.get("/")
def index():
    log_event("page_view")
    latest = _latest_score(g.user["id"]) if g.user else None
    return render_template("index.html", latest=latest, sphere_names=SPHERE_NAMES, sphere_short=SPHERE_SHORT,
                           steps=STEPS)


@bp.get("/privacy")
def privacy():
    log_event("page_view")
    return render_template("privacy.html")


@bp.get("/methodology")
def methodology():
    log_event("page_view")
    return render_template("methodology.html", steps=STEPS, points=POINTS, levels=LEVELS,
                           intensity=INTENSITY, aerobic_target=AEROBIC_TARGET, crisis=CRISIS_CONTACTS)


@bp.post("/api/consent")
def api_consent():
    data = _json_body() or {}
    choice = data.get("choice")
    if choice not in CONSENT_CHOICES:
        return jsonify(error="validation_error", fields={"choice": "допустимые значения: all, necessary"}), 400

    if choice == CONSENT_ALL:
        if "visitor_id" not in session:
            assign_visitor_id()
    else:
        # отказ от аналитики: забываем анонимный идентификатор, Flask удалит cookie сессии
        session.clear()

    db = get_db()
    db.execute(
        "INSERT INTO cookie_consents (visitor_id, choice, policy_version) VALUES (?, ?, ?)",
        (session.get("visitor_id"), choice, POLICY_VERSION),
    )
    db.commit()

    res = jsonify(ok=True, choice=choice)
    for name, value in ((CONSENT_COOKIE, choice), (CONSENT_VERSION_COOKIE, POLICY_VERSION)):
        res.set_cookie(name, value, max_age=CONSENT_MAX_AGE, samesite="Lax", secure=request.is_secure)
    return res


@bp.post("/api/score")
def api_score():
    data = _json_body()
    if data is None:
        return jsonify(error="validation_error", fields={"answers": "ожидается объект с ответами"}), 400
    # ответы анкеты — сведения о здоровье: без отдельного согласия не считаем и не храним
    if data.get("health_consent") is not True:
        return jsonify(error="health_consent_required",
                       fields={"health_consent": "Нужно согласие на обработку данных о здоровье."}), 400
    try:
        result = calculate_score(data)
    except ScoringError as e:
        return jsonify(error=e.code, fields=e.errors), 400

    user_id = g.user["id"] if g.user else None
    db = get_db()
    db.execute(
        "INSERT INTO score_results (visitor_id, user_id, answers, total, breakdown, recommendations,"
        " method_version, flags, focus, health_consent_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session.get("visitor_id"), user_id, to_json(result.pop("answers")), result["total"],
         to_json(result["breakdown"]), to_json(result["recommendations"]), result["version"],
         to_json(result["flags"]), to_json(result["focus"]), POLICY_VERSION),
    )
    db.commit()
    log_event("score_calculated", {"total": result["total"], "weakest": result["weakest"],
                                   "flags": [f["code"] for f in result["flags"]]})
    result["saved_to_account"] = user_id is not None
    return jsonify(result)


@bp.post("/api/lead")
def api_lead():
    data = _json_body() or {}
    email = str(data.get("email") or "").strip()
    plan = data.get("plan")

    errors = {}
    if not email or len(email) > 254 or not EMAIL_RE.match(email):
        errors["email"] = "введите корректный e-mail"
    if plan not in PLANS:
        errors["plan"] = "допустимые значения: Start, Balance"
    if data.get("consent") is not True:
        errors["consent"] = "нужно согласие на обработку персональных данных"
    if errors:
        return jsonify(error="validation_error", fields=errors), 400

    db = get_db()
    db.execute(
        "INSERT INTO leads (visitor_id, user_id, email, plan, policy_version) VALUES (?, ?, ?, ?, ?)",
        (session.get("visitor_id"), g.user["id"] if g.user else None, email, plan, POLICY_VERSION),
    )
    db.commit()
    log_event("lead_submitted", {"plan": plan})
    return jsonify(ok=True)


@bp.post("/api/event")
def api_event():
    if not analytics_allowed():
        # без согласия на аналитику ничего не пишем, но и не ломаем фронтенд
        return "", 204
    data = _json_body()
    name = data.get("name") if data else None
    if not isinstance(name, str) or not EVENT_NAME_RE.match(name):
        return jsonify(error="validation_error", fields={"name": "обязательное поле"}), 400

    params = data.get("params")
    if params is not None and len(to_json(params)) > MAX_FIELD:
        params = {"truncated": True}
    log_event(name, params, path=_clip(data.get("path")) or "", referrer=_clip(data.get("referrer")) or "")
    return "", 204


def _valid(value, pattern, max_len=64):
    if not isinstance(value, str) or len(value) > max_len:
        return None
    return value if pattern.match(value) else None


@bp.post("/api/visitor")
def api_visitor():
    """Контекст посетителя. Первый визит фиксирует источник (first touch), дальше обновляется только last_seen."""
    visitor_id = session.get("visitor_id")
    if not analytics_allowed() or not visitor_id:
        return "", 204
    data = _json_body() or {}

    utm = {key: (str(data[key]).strip()[:200] or None) if data.get(key) else None for key in UTM_FIELDS}
    referrer = _clip(data.get("referrer")) or None
    if not referrer_domain(referrer, request.host):
        referrer = None  # переход внутри сайта — не источник
    source = classify_source(utm["utm_source"], referrer, request.host)

    language = _valid(data.get("language"), LANGUAGE_RE, 35)
    if not language and request.accept_languages:
        language = _valid(request.accept_languages.best, LANGUAGE_RE, 35)
    timezone = _valid(data.get("timezone"), TIMEZONE_RE)
    ua = parse_user_agent(request.user_agent.string)

    row = {
        "visitor_id": visitor_id,
        "landing_path": _clip(data.get("landing_path")),
        "referrer": referrer,
        "source": source,
        **utm,
        "language": language,
        "timezone": timezone,
        "country": guess_country(timezone, language),
        "screen": _valid(data.get("screen"), SCREEN_RE, 11),
        **ua,
    }
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    # поля первого визита не перезаписываем; пустые — дополняем, если появились
    updates = ", ".join(f"{k} = coalesce(visitors.{k}, excluded.{k})" for k in row if k != "visitor_id")
    db = get_db()
    db.execute(
        f"INSERT INTO visitors ({columns}) VALUES ({placeholders}) "
        f"ON CONFLICT(visitor_id) DO UPDATE SET last_seen = datetime('now'), {updates}",
        tuple(row.values()),
    )
    db.commit()
    return "", 204
