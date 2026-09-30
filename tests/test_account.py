import json
import re

import pytest

from app.consent import POLICY_VERSION
from tests.answers import EXAMPLE, answers, with_consent

VALID = with_consent(EXAMPLE)                        # итог 60
BETTER = with_consent(answers(n1="2", n2="daily"))  # итог 92, слабее всего питание — сладкие напитки
PASSWORD = "correct-horse-1"


def csrf(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def register(client, email="anna@example.com", name="Анна", password=PASSWORD, **extra):
    data = {"csrf_token": csrf(client, "/register"), "name": name, "email": email,
            "password": password, "password_confirm": password, "consent": "on"}
    data.update(extra)
    return client.post("/register", data=data)


def login(client, email="anna@example.com", password=PASSWORD):
    return client.post("/login", data={"csrf_token": csrf(client), "email": email, "password": password})


@pytest.fixture
def user_client(client):
    assert register(client).status_code == 302
    return client


# ---------- Регистрация и вход ----------

def test_register_creates_user_and_logs_in(client, query):
    res = register(client, email=" Anna@Example.com ")
    assert res.status_code == 302 and res.headers["Location"].endswith("/account")
    users = query("SELECT email, name, policy_version, password_hash FROM users")
    assert len(users) == 1
    u = users[0]
    assert (u["email"], u["name"], u["policy_version"]) == ("anna@example.com", "Анна", POLICY_VERSION)
    assert PASSWORD not in u["password_hash"]
    page = client.get("/account").get_data(as_text=True)
    assert "Здравствуйте, Анна" in page


@pytest.mark.parametrize("override,field", [
    ({"email": "not-email"}, "Введите корректный e-mail"),
    ({"password": "short", "password_confirm": "short"}, "Пароль — от 8"),
    ({"password_confirm": "different-123"}, "Пароли не совпадают"),
    ({"name": ""}, "Укажите имя"),
    ({"consent": ""}, "Нужно согласие"),
])
def test_register_validation(client, query, override, field):
    data = {"csrf_token": csrf(client, "/register"), "name": "Анна", "email": "anna@example.com",
            "password": PASSWORD, "password_confirm": PASSWORD, "consent": "on", **override}
    res = client.post("/register", data=data)
    assert res.status_code == 200
    assert field in res.get_data(as_text=True)
    assert query("SELECT * FROM users") == []


def test_register_duplicate_email(user_client, app, query):
    other = app.test_client()
    res = register(other, email="ANNA@example.com")
    assert "уже зарегистрирован" in res.get_data(as_text=True)
    assert len(query("SELECT * FROM users")) == 1


def test_login_logout(user_client, app):
    other = app.test_client()
    assert login(other, password="wrong-password").status_code == 200
    assert other.get("/account").status_code == 302
    res = login(other)
    assert res.status_code == 302 and res.headers["Location"].endswith("/account")
    assert other.get("/account").status_code == 200
    other.post("/logout", data={"csrf_token": csrf(other, "/account")})
    assert other.get("/account").status_code == 302


def test_login_redirects_to_safe_next_only(user_client, app):
    other = app.test_client()
    token = csrf(other)
    res = other.post("/login", data={"csrf_token": token, "email": "anna@example.com", "password": PASSWORD,
                                     "next": "//evil.example/steal"})
    assert res.headers["Location"].endswith("/account")


def test_login_rate_limit(user_client, app, query):
    other = app.test_client()
    for _ in range(5):
        login(other, password="wrong-password")
    res = login(other)  # верный пароль, но попытки исчерпаны
    assert "Слишком много попыток" in res.get_data(as_text=True)
    assert other.get("/account").status_code == 302


def test_account_requires_login(client):
    res = client.get("/account")
    assert res.status_code == 302 and "/login?next=/account" in res.headers["Location"]


def test_forms_require_csrf(user_client, query):
    assert user_client.post("/account/profile", data={"name": "Взлом"}).status_code == 400
    assert user_client.post("/login", data={"email": "a@b.co", "password": "x"}).status_code == 400
    assert query("SELECT name FROM users")[0]["name"] == "Анна"


# ---------- Связь данных с кабинетом ----------

def test_guest_results_are_never_attached(client, query):
    """За одним компьютером без входа могут считаться разные люди — гостевые расчёты не привязываем."""
    client.set_cookie("vs_consent", "all")
    client.set_cookie("vs_consent_v", POLICY_VERSION)
    client.get("/")
    client.post("/api/score", json=VALID)
    client.post("/api/lead", json={"email": "anna@example.com", "plan": "Start", "consent": True})
    register(client)
    client.post("/logout", data={"csrf_token": csrf(client, "/account")})
    login(client)
    assert query("SELECT user_id FROM score_results") == [{"user_id": None}]
    assert query("SELECT user_id FROM leads") == [{"user_id": None}]
    assert "Здесь появится ваш VitaScore" in client.get("/account").get_data(as_text=True)


def test_register_returns_to_quiz(client):
    res = register(client, next="/#try")
    assert res.status_code == 302 and res.headers["Location"].endswith("/#try")


def test_guest_score_has_login_cta_data(client):
    data = client.post("/api/score", json=VALID).get_json()
    assert data["saved_to_account"] is False and "claim_token" not in data


def test_logged_in_results_and_leads_are_linked(user_client, query):
    data = user_client.post("/api/score", json=VALID).get_json()
    assert data["saved_to_account"] is True
    user_client.post("/api/lead", json={"email": "anna@example.com", "plan": "Balance", "consent": True})
    assert query("SELECT user_id, recommendations FROM score_results")[0]["user_id"] == 1
    assert query("SELECT user_id FROM leads") == [{"user_id": 1}]


# ---------- Кабинет ----------

def test_dashboard_history(user_client):
    user_client.post("/api/score", json=VALID)
    user_client.post("/api/score", json=BETTER)
    html = user_client.get("/account").get_data(as_text=True)
    data = json.loads(re.search(r'id="history-data">(.*?)</script>', html, re.S).group(1))
    assert [d["total"] for d in data] == [60, 92]
    assert set(data[0]) >= {"id", "t", "label", "date", "total", "sleep", "activity", "nutrition", "recovery"}
    entries = re.findall(r'<details class="entry level-(\w+)" id="entry-(\d+)"', html)
    assert [lvl for lvl, _ in entries] == ["high", "mid"]           # новые сверху
    assert 'id="entry-{}" data-id="{}" open'.format(data[1]["id"], data[1]["id"]) in html
    assert "+32" in html                                           # изменение к прошлой
    assert "6–7" in html and "Умеренно — можете говорить, но не петь" in html  # ответы словами
    assert "account.js" in html
    assert "Фокус недели: Замените сладкий напиток" in html
    recs = html.split('id="recommendations"')[1]
    assert recs.index("Питание") < recs.index("Сон")
    assert "Замените сладкий напиток" in recs


def test_dashboard_hides_registration_and_consent_facts(user_client):
    html = user_client.get("/account").get_data(as_text=True)
    assert "<dt>Кабинет создан" not in html
    assert "Согласие на обработку" not in html
    assert "Скачать" not in html


def test_dashboard_empty_state(user_client):
    html = user_client.get("/account").get_data(as_text=True)
    assert "Здесь появится ваш VitaScore" in html


def test_dashboard_old_result_without_stored_recommendations(user_client, app):
    import sqlite3
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.execute("INSERT INTO score_results (user_id, answers, total, breakdown) VALUES (1, ?, 55, ?)",
                 (json.dumps(VALID), json.dumps({"sleep": 60, "activity": 80, "nutrition": 30, "recovery": 60})))
    conn.commit()
    conn.close()
    html = user_client.get("/account").get_data(as_text=True)
    assert "Овощи к обеду и ужину" in html  # питание — самая слабая, рекомендации пересчитаны


def test_update_profile_name(user_client, query):
    token = csrf(user_client, "/account")
    user_client.post("/account/profile", data={"csrf_token": token, "name": "Анна К."})
    assert query("SELECT name FROM users")[0]["name"] == "Анна К."


def test_change_password_logs_out_other_sessions(user_client, app):
    other = app.test_client()
    login(other)
    token = csrf(user_client, "/account")
    user_client.post("/account/password", data={"csrf_token": token, "current_password": PASSWORD,
                                                "password": "new-password-2", "password_confirm": "new-password-2"})
    assert user_client.get("/account").status_code == 200   # эта сессия жива
    assert other.get("/account").status_code == 302         # другая — разлогинена
    fresh = app.test_client()
    assert login(fresh, password="new-password-2").status_code == 302


def test_change_password_wrong_current(user_client, query):
    before = query("SELECT password_hash FROM users")[0]["password_hash"]
    token = csrf(user_client, "/account")
    user_client.post("/account/password", data={"csrf_token": token, "current_password": "nope",
                                                "password": "new-password-2", "password_confirm": "new-password-2"})
    assert query("SELECT password_hash FROM users")[0]["password_hash"] == before


def test_export_removed(user_client):
    assert user_client.get("/account/export").status_code == 404


def test_delete_account(user_client, query):
    user_client.post("/api/score", json=VALID)
    user_client.post("/api/lead", json={"email": "anna@example.com", "plan": "Start", "consent": True})
    token = csrf(user_client, "/account")
    user_client.post("/account/delete", data={"csrf_token": token, "password": "wrong"})
    assert len(query("SELECT * FROM users")) == 1
    res = user_client.post("/account/delete", data={"csrf_token": token, "password": PASSWORD})
    assert res.status_code == 302
    assert query("SELECT * FROM users") == []
    assert query("SELECT * FROM score_results") == []
    assert query("SELECT * FROM leads") == []
    assert user_client.get("/account").status_code == 302


def test_header_shows_login_or_account(client):
    assert ">Войти<" in client.get("/").get_data(as_text=True)
    register(client)
    assert ">Кабинет<" in client.get("/").get_data(as_text=True)


def test_migration_adds_user_columns(tmp_path):
    import sqlite3
    from app import create_app
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE score_results (id INTEGER PRIMARY KEY AUTOINCREMENT, visitor_id TEXT,"
                 " answers TEXT NOT NULL, total INTEGER NOT NULL, breakdown TEXT NOT NULL,"
                 " created_at TEXT NOT NULL DEFAULT (datetime('now')))")
    conn.commit()
    conn.close()
    create_app({"TESTING": True, "DATABASE_PATH": str(db_path)})
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(score_results)")}
    conn.close()
    assert {"user_id", "recommendations"} <= cols


# ---------- Последний балл на главной ----------

def test_home_shows_latest_score_for_logged_in_user(user_client):
    user_client.post("/api/score", json=VALID)   # 60
    user_client.post("/api/score", json=BETTER)  # 92
    html = user_client.get("/").get_data(as_text=True)
    assert "data-user-card" in html
    assert '<div class="score" data-uc-total>92<span>/100</span></div>' in html
    assert "Замените сладкий напиток" in html    # фокус недели по самой слабой сфере (питание)
    assert ">82<span>/100</span>" not in html    # демо-карточка скрыта


def test_home_shows_demo_card_for_guest_and_new_user(client):
    html = client.get("/").get_data(as_text=True)
    assert "data-user-card" not in html and ">82<span>/100</span>" in html
    register(client)
    html = client.get("/").get_data(as_text=True)
    assert "data-user-card" not in html  # оценок ещё нет


def test_home_does_not_show_other_users_score(user_client, app):
    user_client.post("/api/score", json=VALID)
    other = app.test_client()
    register(other, email="boris@example.com", name="Борис")
    assert "data-user-card" not in other.get("/").get_data(as_text=True)


def test_settings_moved_to_footer_page(user_client, client, app):
    dashboard = user_client.get("/account").get_data(as_text=True)
    assert 'id="password"' not in dashboard and 'id="delete"' not in dashboard
    settings = user_client.get("/account/settings").get_data(as_text=True)
    assert 'id="profile"' in settings and 'id="password"' in settings and 'id="delete"' in settings
    assert "anna@example.com" in settings
    assert "Заявки на тарифы" not in settings and "Оценок пройдено" not in settings
    footer = user_client.get("/").get_data(as_text=True).split("<footer>")[1]
    for text in ("Мои данные", "Сменить пароль", "Удалить аккаунт"):
        assert text in footer
    guest_footer = app.test_client().get("/").get_data(as_text=True).split("<footer>")[1]
    assert "Сменить пароль" not in guest_footer


def test_settings_requires_login(client):
    assert client.get("/account/settings").status_code == 302


def test_settings_forms_redirect_back(user_client):
    token = csrf(user_client, "/account/settings")
    res = user_client.post("/account/profile", data={"csrf_token": token, "name": "Анна К."})
    assert res.headers["Location"].endswith("/account/settings#profile")
    res = user_client.post("/account/delete", data={"csrf_token": token, "password": "wrong"})
    assert res.headers["Location"].endswith("/account/settings#delete")


def test_static_urls_are_versioned(client):
    html = client.get("/").get_data(as_text=True)
    assert "/static/css/style.css?v=" in html and "/static/js/main.js?v=" in html


# ---------- История: «Показать ещё» ----------

def test_history_shows_four_latest_and_more_button(user_client):
    for _ in range(6):
        user_client.post("/api/score", json=VALID)
    html = user_client.get("/account").get_data(as_text=True)
    items = re.findall(r'<li( class="extra")?>\s*<details class="entry', html)
    assert [bool(extra) for extra in items] == [False] * 4 + [True] * 2
    assert "Показать ещё 2 оценки" in html
    assert "data-collapse-all" in html and html.count("data-entry-close") == 6


def test_history_without_more_button_for_few_results(user_client):
    for _ in range(4):
        user_client.post("/api/score", json=VALID)
    html = user_client.get("/account").get_data(as_text=True)
    assert 'class="extra"' not in html and "data-history-more" not in html


# ---------- Методика v1.0 ----------

def _insert_legacy(app, user_id=1):
    import sqlite3
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.execute("INSERT INTO score_results (user_id, answers, total, breakdown, created_at) VALUES (?, ?, 66, ?,"
                 " datetime('now', '-7 days'))",
                 (user_id, json.dumps({"sleep": "5_6", "activity": "3_4", "nutrition": "2_3", "stress": "3"}),
                  json.dumps({"sleep": 60, "activity": 80, "nutrition": 65, "recovery": 60})))
    conn.commit()
    conn.close()


def test_legacy_results_marked_and_not_compared(user_client, app):
    _insert_legacy(app)
    user_client.post("/api/score", json=VALID)
    html = user_client.get("/account").get_data(as_text=True)
    data = json.loads(re.search(r'id="history-data">(.*?)</script>', html, re.S).group(1))
    assert [d["total"] for d in data] == [60]                    # на графике только v1.0
    assert "старая методика" in html
    assert "к прошлой оценке" not in html                        # 60 не сравнивается с 66 старой формулы
    assert "Сон: 5–6 часов" in html or "5–6 часов" in html       # ответы старой анкеты словами


def test_only_legacy_results_show_chart_placeholder(user_client, app):
    _insert_legacy(app)
    html = user_client.get("/account").get_data(as_text=True)
    assert "График появится после первой анкеты по методике v1.0" in html
    assert 'id="history-data"' not in html


def test_quiz_markup_has_all_questions_and_health_consent(client):
    html = client.get("/").get_data(as_text=True)
    assert len(set(re.findall(r'type="radio" name="(\w+)"', html))) == 22
    assert 'name="health_consent"' in html and "сведений о состоянии моего здоровья" in html
    assert 'class="quiz-step"' in html and "Шаг 1 из 5" in html
    assert "ПСИХОЛОГИЧЕСКОЕ СОСТОЯНИЕ" in html and "/methodology" in html


def test_methodology_page(client):
    html = client.get("/methodology").get_data(as_text=True)
    assert "Методика v1.0" in html and "бета-версия" in html
    assert "7–8 → <b>100</b>" in html and "8–9 → <b>100</b> (65+: 70)" in html   # таблицы из кода скоринга
    assert "Балл = 100 − PHQ-4 / 12 × 100" in html
    assert "Красные флаги" in html and "112" in html


def test_privacy_has_health_section(client):
    html = client.get("/privacy").get_data(as_text=True)
    assert 'id="health"' in html and "ст. 10 152-ФЗ" in html


def test_home_card_shows_specialist_flag(user_client):
    user_client.post("/api/score", json={**VALID, "s6": "yes"})
    html = user_client.get("/").get_data(as_text=True)
    assert "Есть рекомендация обратиться к специалисту" in html
    assert "Фокус недели — консультация специалиста" in html
