"""Вход по e-mail и паролю: регистрация, вход, выход и защита форм.

К кабинету относятся только анкеты, пройденные после входа: за одним компьютером
без входа могут считаться разные люди, поэтому гостевые расчёты не привязываются.
"""
import hashlib
import hmac
import re
import secrets
from functools import wraps

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .consent import POLICY_VERSION
from .db import get_db, log_event

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN, PASSWORD_MAX = 8, 128
NAME_MAX = 60
# не больше 5 неудачных попыток на e-mail и 20 с одного IP за 15 минут
FAILS_PER_EMAIL, FAILS_PER_IP, FAIL_WINDOW = 5, 20, "-15 minutes"


# ---------- Текущий пользователь ----------

def _session_marker(password_hash):
    """Меняется при смене пароля — старые сессии перестают действовать."""
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, password_hash.encode(), hashlib.sha256).hexdigest()[:32]


def load_current_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id is None:
        return
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None or not hmac.compare_digest(session.get("auth", ""), _session_marker(user["password_hash"])):
        session.pop("user_id", None)
        session.pop("auth", None)
        return
    g.user = user


def login_user(user):
    session.pop("csrf", None)
    session["user_id"] = user["id"]
    session["auth"] = _session_marker(user["password_hash"])
    session.permanent = True
    get_db().execute("UPDATE users SET last_login_at = datetime('now') WHERE id = ?", (user["id"],))


def logout_user():
    for key in ("user_id", "auth", "csrf"):
        session.pop(key, None)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


# ---------- CSRF для HTML-форм ----------

def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf():
    sent = request.form.get("csrf_token", "")
    if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
        abort(400, description="Форма устарела. Обновите страницу и попробуйте ещё раз.")


# ---------- Ограничение попыток входа ----------

def _client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip() or None


def _too_many_attempts(email):
    db = get_db()
    by_email = db.execute(
        "SELECT count(*) FROM login_attempts WHERE email = ? AND success = 0 AND created_at > datetime('now', ?)",
        (email, FAIL_WINDOW)).fetchone()[0]
    by_ip = db.execute(
        "SELECT count(*) FROM login_attempts WHERE ip = ? AND success = 0 AND created_at > datetime('now', ?)",
        (_client_ip(), FAIL_WINDOW)).fetchone()[0]
    return by_email >= FAILS_PER_EMAIL or by_ip >= FAILS_PER_IP


def _record_attempt(email, success):
    get_db().execute("INSERT INTO login_attempts (email, ip, success) VALUES (?, ?, ?)",
                     (email, _client_ip(), int(success)))


# ---------- Проверки ----------

def normalize_email(value):
    return (value or "").strip().lower()


def validate_password(password, confirm):
    if not (PASSWORD_MIN <= len(password) <= PASSWORD_MAX):
        return f"Пароль — от {PASSWORD_MIN} до {PASSWORD_MAX} символов."
    if password != confirm:
        return "Пароли не совпадают."
    return None


def hash_password(password):
    return generate_password_hash(password)


_DUMMY_HASH = None


def _dummy_hash():
    # проверка пароля для несуществующего e-mail занимает столько же времени, сколько для настоящего
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(16))
    return _DUMMY_HASH


def _safe_next(value):
    return value if value and value.startswith("/") and not value.startswith("//") else None


# ---------- Маршруты ----------

@bp.before_request
def protect_forms():
    if request.method == "POST":
        check_csrf()


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user is not None:
        return redirect(url_for("account.dashboard"))
    form = request.form if request.method == "POST" else request.args
    next_url = _safe_next(form.get("next"))
    errors = {}
    if request.method == "POST":
        name = form.get("name", "").strip()
        email = normalize_email(form.get("email"))
        password = form.get("password", "")
        if not name or len(name) > NAME_MAX:
            errors["name"] = f"Укажите имя — до {NAME_MAX} символов."
        if not EMAIL_RE.match(email) or len(email) > 254:
            errors["email"] = "Введите корректный e-mail."
        password_error = validate_password(password, form.get("password_confirm", ""))
        if password_error:
            errors["password"] = password_error
        if form.get("consent") != "on":
            errors["consent"] = "Нужно согласие на обработку персональных данных."
        db = get_db()
        if not errors and db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            errors["email"] = "Этот e-mail уже зарегистрирован — войдите."
        if not errors:
            cur = db.execute(
                "INSERT INTO users (email, name, password_hash, policy_version) VALUES (?, ?, ?, ?)",
                (email, name, hash_password(password), POLICY_VERSION))
            user = db.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
            login_user(user)
            db.commit()
            log_event("account_registered")
            if next_url:
                flash("Кабинет создан. Пройдите анкету — теперь результат сохранится в кабинете.")
                return redirect(next_url)
            flash("Кабинет создан. Добро пожаловать!")
            return redirect(url_for("account.dashboard"))
    return render_template("auth/register.html", form=form, errors=errors, next_url=next_url)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(url_for("account.dashboard"))
    form = request.form if request.method == "POST" else request.args
    next_url = _safe_next(form.get("next"))
    error = None
    if request.method == "POST":
        email = normalize_email(form.get("email"))
        db = get_db()
        if _too_many_attempts(email):
            error = "Слишком много попыток входа. Подождите 15 минут и попробуйте снова."
        else:
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            password_ok = check_password_hash(user["password_hash"] if user else _dummy_hash(),
                                              form.get("password", ""))
            ok = user is not None and password_ok
            _record_attempt(email, ok)
            if ok:
                login_user(user)
                db.commit()
                log_event("account_login")
                return redirect(next_url or url_for("account.dashboard"))
            error = "Неверный e-mail или пароль."
        db.commit()
    return render_template("auth/login.html", form=form, error=error, next_url=next_url)


@bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("main.index"))
