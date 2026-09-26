import json
import re

from flask import Blueprint, jsonify, render_template, request, session

from . import assign_visitor_id
from .consent import (CONSENT_ALL, CONSENT_CHOICES, CONSENT_COOKIE, CONSENT_MAX_AGE,
                      POLICY_VERSION, analytics_allowed)
from .db import get_db, log_event, to_json
from .scoring import ScoringError, calculate_score

bp = Blueprint("main", __name__)

PLANS = {"Start", "Balance"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EVENT_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
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


@bp.get("/")
def index():
    log_event("page_view")
    return render_template("index.html")


@bp.get("/privacy")
def privacy():
    log_event("page_view")
    return render_template("privacy.html", policy_version=POLICY_VERSION)


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
    res.set_cookie(CONSENT_COOKIE, choice, max_age=CONSENT_MAX_AGE, samesite="Lax",
                   secure=request.is_secure)
    return res


@bp.post("/api/score")
def api_score():
    answers = _json_body()
    try:
        result = calculate_score(answers)
    except ScoringError as e:
        return jsonify(error="validation_error", fields=e.errors), 400

    clean = {k: answers[k] for k in ("sleep", "activity", "nutrition", "stress")}
    db = get_db()
    db.execute(
        "INSERT INTO score_results (visitor_id, answers, total, breakdown) VALUES (?, ?, ?, ?)",
        (session.get("visitor_id"), to_json(clean), result["total"], to_json(result["breakdown"])),
    )
    db.commit()
    log_event("score_calculated", {"total": result["total"], "weakest": result["weakest"]})
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
        "INSERT INTO leads (visitor_id, email, plan, policy_version) VALUES (?, ?, ?, ?)",
        (session.get("visitor_id"), email, plan, POLICY_VERSION),
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
