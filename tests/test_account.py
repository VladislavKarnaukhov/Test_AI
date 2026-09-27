import json
import re

import pytest

from app.consent import POLICY_VERSION

VALID = {"sleep": "5_6", "activity": "3_4", "nutrition": "2_3", "stress": "3"}
PASSWORD = "correct-horse-1"


def csrf(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def register(client, email="anna@example.com", name="Анна", password=PASSWORD, claim="", **extra):
    data = {"csrf_token": csrf(client, "/register"), "name": name, "email": email,
            "password": password, "password_confirm": password, "consent": "on", "claim": claim}
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

def test_guest_result_claimed_on_register(client, query):
    data = client.post("/api/score", json=VALID).get_json()
    assert data["claim_token"]
    register(client, claim=data["claim_token"])
    rows = query("SELECT user_id FROM score_results")
    assert rows[0]["user_id"] is not None


def test_claim_token_cannot_be_forged(client, query):
    client.post("/api/score", json=VALID)
    register(client, claim="1")  # не подписан
    assert query("SELECT user_id FROM score_results")[0]["user_id"] is None


def test_claimed_result_of_other_user_is_not_stolen(user_client, app, query):
    token = user_client.post("/api/score", json=VALID).get_json()["claim_token"]
    assert token is None  # у вошедшего результат сразу в кабинете
    guest = app.test_client()
    guest_token = guest.post("/api/score", json=VALID).get_json()["claim_token"]
    register(guest, email="boris@example.com", name="Борис", claim=guest_token)
    register(app.test_client(), email="eve@example.com", name="Ева", claim=guest_token)  # повторное использование
    owners = [r["user_id"] for r in query("SELECT user_id FROM score_results ORDER BY id")]
    assert owners == [1, 2]


def test_consented_visitor_data_attached_on_login(user_client, app, query):
    guest = app.test_client()
    guest.set_cookie("vs_consent", "all")
    guest.set_cookie("vs_consent_v", POLICY_VERSION)
    guest.get("/")
    guest.post("/api/score", json=VALID)
    guest.post("/api/lead", json={"email": "anna@example.com", "plan": "Start", "consent": True})
    login(guest)
    assert [r["user_id"] for r in query("SELECT user_id FROM score_results")] == [1]
    assert [r["user_id"] for r in query("SELECT user_id FROM leads")] == [1]


def test_logged_in_results_and_leads_are_linked(user_client, query):
    data = user_client.post("/api/score", json=VALID).get_json()
    assert data["saved_to_account"] is True
    user_client.post("/api/lead", json={"email": "anna@example.com", "plan": "Balance", "consent": True})
    assert query("SELECT user_id, recommendations FROM score_results")[0]["user_id"] == 1
    assert query("SELECT user_id FROM leads") == [{"user_id": 1}]


# ---------- Кабинет ----------

def test_dashboard_shows_dynamics_and_recommendations(user_client):
    user_client.post("/api/score", json=VALID)
    user_client.post("/api/score", json={**VALID, "sleep": "7_8", "stress": "1"})
    html = user_client.get("/account").get_data(as_text=True)
    assert "История оценок" in html
    assert "<polyline" in html                    # две оценки — линия графика
    assert "к прошлой оценке" in html
    assert "Рекомендации прошлых оценок" in html
    # во второй оценке слабее всего питание (65, «есть резерв») — его советы идут первыми
    recs = html.split('id="recommendations"')[1]
    assert recs.index("Питание") < recs.index("Сон")
    assert "Полтарелки — овощи" in recs


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


def test_export(user_client):
    user_client.post("/api/score", json=VALID)
    res = user_client.get("/account/export")
    assert "attachment" in res.headers["Content-Disposition"]
    data = res.get_json(force=True)
    assert data["user"]["email"] == "anna@example.com"
    assert len(data["score_results"]) == 1 and data["score_results"][0]["recommendations"]
    assert "password_hash" not in json.dumps(data)


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
