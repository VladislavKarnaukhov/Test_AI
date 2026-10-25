import json
import re

import pytest

from app.consent import POLICY_VERSION
from tests.answers import SHORT_EXAMPLE as EXAMPLE, medium, short, with_consent

VALID = with_consent(EXAMPLE)                    # ядро 69
BETTER = with_consent(short(n1="2", n2="7"))      # ядро 91, слабее всего питание — сладкие напитки
PASSWORD = "correct-horse-1"


def csrf(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def register(client, email="anna@example.com", name="Анна", password=PASSWORD, **extra):
    data = {"csrf_token": csrf(client, "/register"), "name": name, "email": email,
            "password": password, "password_confirm": password, "consent": "on", "terms": "on"}
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
    ({"terms": ""}, "Нужно принять пользовательское соглашение"),
])
def test_register_validation(client, query, override, field):
    data = {"csrf_token": csrf(client, "/register"), "name": "Анна", "email": "anna@example.com",
            "password": PASSWORD, "password_confirm": PASSWORD, "consent": "on", "terms": "on", **override}
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
    client.post("/api/lead", json={"email": "anna@example.com", "plan": "Plus", "consent": True})
    register(client)
    client.post("/logout", data={"csrf_token": csrf(client, "/account")})
    login(client)
    assert query("SELECT user_id FROM score_results") == [{"user_id": None}]
    assert query("SELECT user_id FROM leads") == [{"user_id": None}]
    assert "Здесь появится ваш индекс" in client.get("/account").get_data(as_text=True)


def test_register_returns_to_quiz(client):
    res = register(client, next="/#try")
    assert res.status_code == 302 and res.headers["Location"].endswith("/#try")


def test_guest_score_has_login_cta_data(client):
    data = client.post("/api/score", json=VALID).get_json()
    assert data["saved_to_account"] is False and "claim_token" not in data


def test_logged_in_results_and_leads_are_linked(user_client, query):
    data = user_client.post("/api/score", json=VALID).get_json()
    assert data["saved_to_account"] is True
    user_client.post("/api/lead", json={"email": "anna@example.com", "plan": "Plus", "consent": True})
    assert query("SELECT user_id, recommendations FROM score_results")[0]["user_id"] == 1
    assert query("SELECT user_id FROM leads") == [{"user_id": 1}]


# ---------- Кабинет ----------

def test_dashboard_history(user_client):
    user_client.post("/api/score", json=VALID)
    user_client.post("/api/score", json=BETTER)
    html = user_client.get("/account").get_data(as_text=True)
    data = json.loads(re.search(r'id="history-data">(.*?)</script>', html, re.S).group(1))
    assert [d["total"] for d in data["points"]] == [69, 91]
    assert [k for k, _ in data["series"]] == ["total", "sleep", "activity", "nutrition", "mental", "nicotine", "alcohol"]
    entries = re.findall(r'<details class="entry level-(\w+)" id="entry-(\d+)"', html)
    assert [lvl for lvl, _ in entries] == ["high", "mid"]           # новые сверху
    last_id = data["points"][1]["id"]
    assert 'id="entry-{}" data-id="{}" open'.format(last_id, last_id) in html
    assert "+22" in html                                           # изменение к прошлой
    assert "6–7" in html and "Бросил(а)" in html                   # ответы словами (во вложенном «Что вы ответили»)
    assert "Фокус недели: На один день без сладких напитков больше" in html
    recs = html.split('id="recommendations"')[1]
    assert recs.index("Питание") < recs.index("Сон")


def test_dashboard_hides_registration_and_consent_facts(user_client):
    html = user_client.get("/account").get_data(as_text=True)
    assert "<dt>Кабинет создан" not in html
    assert "Согласие на обработку" not in html
    assert "Скачать" not in html


def test_dashboard_empty_state(user_client):
    html = user_client.get("/account").get_data(as_text=True)
    assert "Здесь появится ваш индекс" in html


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
    user_client.post("/api/lead", json={"email": "anna@example.com", "plan": "Plus", "consent": True})
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
    user_client.post("/api/score", json=VALID)   # 69
    user_client.post("/api/score", json=BETTER)  # 91
    html = user_client.get("/").get_data(as_text=True)
    assert "data-user-card" in html
    assert '<div class="score" data-uc-total>91<span>/100</span></div>' in html
    assert "На один день без сладких напитков больше" in html     # фокус недели по самой слабой сфере
    assert "data-uc-sphere" not in html                           # карточка на главной без разбивки по сферам
    assert ">82<span>/100</span>" not in html                     # демо-карточка скрыта


def test_home_shows_demo_card_for_guest_and_new_user(client):
    html = client.get("/").get_data(as_text=True)
    assert "data-user-card" not in html and "<b>82</b>" in html and "score-peek" in html
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
    assert all(f"/static/css/{n}.css?v=" in html for n in ("base", "components", "pages")) and "/static/js/main.js?v=" in html


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
    assert [d["total"] for d in data["points"]] == [69]          # на графике только v2.0
    assert "старая методика" in html
    assert "к прошлой оценке" not in html                        # 69 не сравнивается с 66 старой формулы
    assert "5–6 часов" in html                                   # ответы старой анкеты словами


def test_only_legacy_results_show_chart_placeholder(user_client, app):
    _insert_legacy(app)
    html = user_client.get("/account").get_data(as_text=True)
    assert "График появится после первой анкеты по методике v2.0" in html
    assert 'id="history-data"' not in html


def test_quiz_markup_has_all_questions_and_health_consent(client):
    from app.scoring import QUESTIONS
    html = client.get("/").get_data(as_text=True)
    radios = set(re.findall(r'type="radio" name="(\w+)"', html))
    numbers = set(re.findall(r'type="number" name="(\w+)"', html))
    assert radios | numbers == set(QUESTIONS) | {"tier"}
    assert 'data-tier="medium"' in html and 'data-tier="extended"' in html and "data-cond=" in html
    assert 'name="health_consent"' in html and "/consent/health" in html and "/terms" in html
    assert "Что входит в индекс" in html and "<dt>Никотин</dt>" in html and "<dt>Алкоголь</dt>" in html
    assert "/methodology" in html


def test_methodology_page(client):
    html = client.get("/methodology").get_data(as_text=True)
    assert "Методика v2.0" in html and "бета-версия" in html
    assert "<td>7–9</td><td>100</td>" in html and "<td>150</td><td>100</td>" in html  # таблицы LE8 из кода
    assert "Три уровня" in html and "Каскад точности" in html
    assert "Красные флаги" in html and "112" in html
    assert "Sleep Condition Indicator — отключён" in html


def test_privacy_has_health_section(client):
    html = client.get("/privacy").get_data(as_text=True)
    assert 'id="health"' in html and "ст. 10 152-ФЗ" in html


def test_home_card_shows_specialist_flag(user_client):
    user_client.post("/api/score", json={**VALID, "sl2": "3plus"})
    html = user_client.get("/").get_data(as_text=True)
    assert "Есть рекомендация обратиться к специалисту" in html
    assert "Фокус недели — консультация специалиста" in html




# ---------- Методика v2.0: уровни, каскад, соглашения ----------

def test_cascade_between_submissions(user_client, query):
    """Средний уровень сегодня + короткий завтра → подробный индекс собирается из свежих уточнённых сфер."""
    user_client.post("/api/score", json=with_consent(medium()))
    data = user_client.post("/api/score", json=VALID).get_json()
    assert data["detailed"] is not None
    assert data["detailed"]["sources"]["wellbeing"] == "medium"
    assert data["detailed"]["sources"]["sleep"] == "short"


def test_guest_gets_no_cascade(client):
    client.post("/api/score", json=with_consent(medium()))
    assert client.post("/api/score", json=VALID).get_json()["detailed"] is None


def test_terms_and_health_consent_pages(client):
    terms = client.get("/terms").get_data(as_text=True)
    assert "Пользовательское соглашение" in terms and "не является медицинской услугой" in terms
    assert "Pfizer" in terms and "Всемирная организация здравоохранения" in terms
    consent = client.get("/consent/health").get_data(as_text=True)
    assert "статьями 9 и 10" in consent and "HbA1c" in consent and "Отзыв согласия" in consent
    footer = client.get("/").get_data(as_text=True).split("<footer>")[1]
    assert "Пользовательское соглашение" in footer


def test_registration_stores_terms_version(client, query):
    from app.consent import TERMS_VERSION
    register(client)
    assert query("SELECT terms_version FROM users")[0]["terms_version"] == TERMS_VERSION


def test_extended_result_in_dashboard(user_client):
    from tests.answers import extended
    user_client.post("/api/score", json=with_consent(extended()))
    html = user_client.get("/account").get_data(as_text=True)
    assert "Подробный индекс (7 сфер)" in html and "Тело и метаболизм: 90/100 — по 4 из 4 показателей" in html
    assert "170 см" in html and "расширенный" in html


# ---------- Удаление отдельной оценки ----------

def _history_ids(client):
    html = client.get("/account").get_data(as_text=True)
    return [int(i) for i in re.findall(r'<details class="entry level-\w+" id="entry-(\d+)"', html)]


def test_delete_result_removes_only_selected_own_result(user_client, query):
    user_client.post("/api/score", json=VALID)
    user_client.post("/api/score", json=BETTER)
    first, second = sorted(_history_ids(user_client))
    token = csrf(user_client, "/account")
    r = user_client.post(f"/account/results/{first}/delete", data={"csrf_token": token})
    assert r.status_code == 302 and r.headers["Location"].endswith("/account#history")
    html = user_client.get("/account").get_data(as_text=True)          # сообщение показывается один раз
    assert "Оценка удалена" in html and f'id="entry-{first}"' not in html and f'id="entry-{second}"' in html
    assert [row["id"] for row in query("SELECT id FROM score_results")] == [second]


def test_delete_result_requires_csrf_and_login(user_client, client, app, query):
    user_client.post("/api/score", json=VALID)
    (rid,) = _history_ids(user_client)
    assert user_client.post(f"/account/results/{rid}/delete").status_code == 400      # без csrf_token
    assert len(query("SELECT id FROM score_results")) == 1
    anon = app.test_client()
    r = anon.post(f"/account/results/{rid}/delete", data={"csrf_token": "x"})
    assert r.status_code in (302, 400) and len(query("SELECT id FROM score_results")) == 1


def test_cannot_delete_someone_elses_result(user_client, app, query):
    user_client.post("/api/score", json=VALID)
    (rid,) = _history_ids(user_client)
    other = app.test_client()
    register(other, email="boris@example.com", name="Борис")
    r = other.post(f"/account/results/{rid}/delete", data={"csrf_token": csrf(other, "/account")})
    assert r.status_code == 302
    assert len(query("SELECT id FROM score_results")) == 1                                # чужая оценка на месте
    assert "нет в вашем кабинете" in other.get("/account").get_data(as_text=True)


def test_history_offers_answers_full_result_and_delete(user_client):
    user_client.post("/api/score", json=VALID)
    html = user_client.get("/account").get_data(as_text=True)
    assert "Что вы ответили" in html and "Полный результат и советы" in html and "Удалить оценку" in html
    assert "/delete" in html and 'data-metric="account_delete_result"' in html


def test_choosing_necessary_cookies_keeps_login(user_client):
    user_client.post("/api/consent", json={"choice": "all"})
    assert user_client.get("/account").status_code == 200
    user_client.post("/api/consent", json={"choice": "necessary"})
    assert user_client.get("/account").status_code == 200      # вход сохранён
    with user_client.session_transaction() as s:
        assert "visitor_id" not in s                            # аналитический идентификатор забыт


def test_chart_has_text_equivalent(user_client):
    user_client.post("/api/score", json=VALID)
    user_client.post("/api/score", json=BETTER)
    html = user_client.get("/account").get_data(as_text=True)
    assert 'aria-describedby="chart-summary"' in html and 'id="chart-summary"' in html
    assert "<caption>Индекс и баллы сфер по датам</caption>" in html
    assert html.count('<th scope="row">') >= 2                                  # строка таблицы на каждую оценку


# ---------- Аналитический дашборд /admin ----------

def _seed_analytics(app):
    import sqlite3
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.execute("INSERT INTO visitors (visitor_id, source, device_type, os, browser, country, language) VALUES ('v1','yandex','mobile','iOS','Safari','RU','ru')")
    conn.execute("INSERT INTO visitors (visitor_id, source, utm_source, utm_campaign, device_type, os, browser, country, language) VALUES ('v2','direct','tg','spring','desktop','macOS','Chrome','RU','ru')")
    for name, vid, payload in [("page_view", "v1", None), ("quiz_answer", "v1", '{"question":"tier"}'), ("quiz_step", "v1", '{"step":2}'),
                               ("score_calculated", "v1", '{"total":69,"tier":"short","weakest":"nutrition","flags":["sleep_3plus"]}'),
                               ("page_view", "v2", None), ("hero_start_quiz", "v2", None)]:
        conn.execute("INSERT INTO events (visitor_id, name, path, payload) VALUES (?, ?, '/', ?)", (vid, name, payload))
    conn.execute("INSERT INTO cookie_consents (visitor_id, choice, policy_version) VALUES ('v1','all','x')")
    conn.commit()
    conn.close()


def test_admin_hidden_from_everyone_but_listed_admins(client, app, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    assert client.get("/admin").status_code == 404                        # гость
    register(client)                                                       # anna@example.com — не админ
    assert client.get("/admin").status_code == 404
    monkeypatch.setenv("ADMIN_EMAILS", "")
    assert client.get("/admin").status_code == 404                        # список пуст — закрыто для всех


def test_admin_dashboard_shows_aggregates_without_personal_data(app, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com, other@example.com")
    c = app.test_client()
    register(c, email="boss@example.com", name="Босс")
    c.post("/api/score", json=VALID)
    _seed_analytics(app)
    r = c.get("/admin")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Воронка" in html and "Откуда приходят" in html
    assert r.headers["X-Robots-Tag"].startswith("noindex") and "no-store" in r.headers["Cache-Control"]
    assert "yandex" in html and "iOS" in html and "Питание" in html       # источники, устройства, слабая сфера
    assert "boss@example.com" not in html.split("<main", 1)[1]            # e-mail в отчёте нет
    for period in ("7", "90", "all", "bogus"):
        assert c.get(f"/admin?period={period}").status_code == 200


def test_owner_is_admin_by_default_and_sees_analytics_tab(app):
    c = app.test_client()
    register(c, email="KarnaukhovVlad@gmail.com", name="Влад")
    assert c.get("/admin").status_code == 200
    assert 'class="nav-admin"' in c.get("/").get_data(as_text=True)          # вкладка «Аналитика» в шапке


def test_regular_user_has_no_analytics_tab(user_client):
    assert "/admin" not in user_client.get("/").get_data(as_text=True)
    assert user_client.get("/admin").status_code == 404


def test_home_trend_shows_current_users_scores_only(user_client, app):
    guest = app.test_client()
    assert "Пример динамики" in guest.get("/").get_data(as_text=True)         # гостю — пример
    user_client.post("/api/score", json=VALID)                                # 69
    user_client.post("/api/score", json=BETTER)                               # 91
    html = user_client.get("/").get_data(as_text=True)
    assert "Ваша динамика" in html and "69 → 91" in html and "Пример динамики" not in html
    other = app.test_client()
    register(other, email="boris@example.com", name="Борис")
    assert "Ваша динамика" not in other.get("/").get_data(as_text=True)       # у нового нет чужих данных


def test_funnel_is_nested_and_never_exceeds_100_percent(app, monkeypatch):
    import sqlite3
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    # v1 прошёл всё; v2 дошёл до результата без события quiz_step (потерян); v3 зарегистрировался, не начав анкету
    rows = [("v1", n) for n in ("page_view", "quiz_answer", "quiz_step", "score_calculated", "account_registered", "lead_submitted")]
    rows += [("v2", n) for n in ("page_view", "quiz_answer", "score_calculated")]
    rows += [("v3", n) for n in ("page_view", "account_registered")]
    for vid, name in rows:
        conn.execute("INSERT INTO events (visitor_id, name, path) VALUES (?, ?, '/')", (vid, name))
    conn.commit()
    conn.close()
    c = app.test_client()
    register(c, email="boss@example.com", name="Босс")
    with app.test_request_context():
        from app.admin import collect
        d = collect("all")
    ns = [s["n"] for s in d["funnel"]]
    assert ns == [3, 2, 1, 1, 1, 1]                                 # v2 отсеян на шаге «следующий вопрос», v3 не начинал
    assert all(s["of_top"] <= 100 and s["of_prev"] <= 100 for s in d["funnel"])
    assert all(a >= b for a, b in zip(ns[:4], ns[1:4]))             # основная цепочка не растёт


# ---------- Предзаполнение никотина и алкоголя ----------

def _checked(html, name):
    return re.findall(rf'<input type="radio" name="{name}" value="([^"]*)" checked>', html)


def test_prefill_nicotine_and_alcohol_from_previous_result(user_client, app):
    user_client.post("/api/score", json=VALID)           # nic1=former, nic2=1_5, nic3=no, nic4=no, a1=2, a2=1, a3=0
    html = user_client.get("/").get_data(as_text=True)
    assert _checked(html, "nic1") == ["former"] and _checked(html, "nic2") == ["1_5"]
    assert _checked(html, "a1") == ["2"] and _checked(html, "a2") == ["1"] and _checked(html, "a3") == ["0"]
    assert "Из вашей анкеты от" in html and html.count("data-prefilled") >= 7
    assert _checked(html, "sl1") == [] and _checked(html, "age") == []        # остальные вопросы не трогаем
    guest = app.test_client().get("/").get_data(as_text=True)
    assert "data-prefilled" not in guest and _checked(guest, "nic1") == []    # гость — без подстановки
    other = app.test_client()
    register(other, email="boris@example.com", name="Борис")
    assert _checked(other.get("/").get_data(as_text=True), "nic1") == []      # чужие ответы не попадают


def test_prefill_uses_latest_result_and_does_not_change_scoring(user_client):
    user_client.post("/api/score", json=VALID)
    user_client.post("/api/score", json={**VALID, "nic1": "never", "a1": "0", "a2": None, "a3": None})
    html = user_client.get("/").get_data(as_text=True)
    assert _checked(html, "nic1") == ["never"] and _checked(html, "a1") == ["0"]
    first = user_client.post("/api/score", json=VALID).get_json()["total"]
    again = user_client.post("/api/score", json=VALID).get_json()["total"]
    assert first == again == 69                                                # расчёт прежний


# ---------- Del Health Plus ----------

import sqlite3 as _sqlite3
from datetime import datetime as _dt, timedelta as _td


def _user_id(query, email="anna@example.com"):
    return query("SELECT id FROM users WHERE email = ?", email)[0]["id"]


def _make_plus(app, query, email="anna@example.com", days=30):
    conn = _sqlite3.connect(app.config["DATABASE_PATH"])
    until = (_dt.utcnow() + _td(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE users SET plus_until = ? WHERE email = ?", (until, email))
    conn.commit()
    conn.close()


def test_free_user_sees_locked_plus_and_cannot_use_it(user_client):
    user_client.post("/api/score", json=VALID)
    html = user_client.get("/account").get_data(as_text=True)
    assert "plus-offer" in html and "Ваш план на месяц" in html and "plan-steps" not in html
    r = user_client.post("/account/plan/1/0", data={"csrf_token": csrf(user_client, "/account")})
    assert r.status_code == 302 and "#plus" in r.headers["Location"]          # платная функция закрыта
    r = user_client.post("/account/reminders", data={"csrf_token": csrf(user_client, "/account"), "reminders": "on"})
    assert r.status_code == 302


def test_plus_user_gets_plan_with_toggle_and_compare(user_client, app, query):
    user_client.post("/api/score", json=VALID)
    user_client.post("/api/score", json=BETTER)
    _make_plus(app, query)
    html = user_client.get("/account").get_data(as_text=True)
    assert "Ваш месяц" in html and html.count('<li class="plan-step') == 3 and "Сравнение по сферам" in html
    assert "plus-offer" not in html and "<th scope=\"row\">Итог</th>" in html
    rid = int(re.search(r'/account/plan/(\d+)/0', html).group(1))
    token = csrf(user_client, "/account")
    user_client.post(f"/account/plan/{rid}/0", data={"csrf_token": token})
    assert "is-done" in user_client.get("/account").get_data(as_text=True)
    user_client.post(f"/account/plan/{rid}/0", data={"csrf_token": token})    # повторное нажатие снимает отметку
    assert "is-done" not in user_client.get("/account").get_data(as_text=True)
    assert user_client.post(f"/account/plan/{rid}/9", data={"csrf_token": token}).status_code == 404
    assert user_client.post(f"/account/plan/{rid}/0").status_code == 400      # без CSRF


def test_plan_steps_are_per_user_and_removed_with_result(user_client, app, query):
    user_client.post("/api/score", json=VALID)
    _make_plus(app, query)
    rid = int(re.search(r'/account/plan/(\d+)/0', user_client.get("/account").get_data(as_text=True)).group(1))
    user_client.post(f"/account/plan/{rid}/1", data={"csrf_token": csrf(user_client, "/account")})
    other = app.test_client()
    register(other, email="boris@example.com", name="Борис")
    _make_plus(app, query, "boris@example.com")
    assert other.post(f"/account/plan/{rid}/0", data={"csrf_token": csrf(other, "/account")}).status_code == 404
    user_client.post(f"/account/results/{rid}/delete", data={"csrf_token": csrf(user_client, "/account")})
    assert query("SELECT count(*) AS n FROM plan_steps")[0]["n"] == 0


def test_plus_expired_is_free_again(user_client, app, query):
    user_client.post("/api/score", json=VALID)
    _make_plus(app, query, days=-1)
    assert "plus-offer" in user_client.get("/account").get_data(as_text=True)


def test_admin_grants_and_revokes_plus(app, query, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    user = app.test_client()
    register(user, email="anna@example.com")
    boss = app.test_client()
    register(boss, email="boss@example.com", name="Босс")
    tok = csrf(boss, "/admin")
    assert user.post("/admin/plus", data={"csrf_token": "x", "email": "anna@example.com"}).status_code == 404   # не админ
    boss.post("/admin/plus", data={"csrf_token": tok, "email": "anna@example.com", "days": "30", "action": "grant"})
    assert query("SELECT plus_until FROM users WHERE email = 'anna@example.com'")[0]["plus_until"]
    boss.post("/admin/plus", data={"csrf_token": tok, "email": "anna@example.com", "days": "30", "action": "grant"})
    first = query("SELECT plus_until FROM users WHERE email = 'anna@example.com'")[0]["plus_until"]
    assert first > (_dt.utcnow() + _td(days=58)).strftime("%Y-%m-%d %H:%M:%S")      # повторная выдача продлевает срок
    boss.post("/admin/plus", data={"csrf_token": tok, "email": "anna@example.com", "action": "revoke"})
    assert query("SELECT plus_until FROM users WHERE email = 'anna@example.com'")[0]["plus_until"] is None
    assert boss.post("/admin/plus", data={"email": "anna@example.com"}).status_code == 400               # без CSRF


def test_reminders_sent_only_to_opted_in_plus_users_and_capped(app, query):
    from app import plus as plusmod
    c = app.test_client()
    register(c)
    c.post("/api/score", json=VALID)
    _make_plus(app, query)
    conn = _sqlite3.connect(app.config["DATABASE_PATH"])
    old = (_dt.utcnow() - _td(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE score_results SET created_at = ?", (old,))
    conn.commit()
    sent = []
    def fake(to, name, subject, html, text, unsubscribe_url=None):
        sent.append((to, subject, text, unsubscribe_url)); return True, "id"
    with app.test_request_context(base_url="https://example.test"):
        assert plusmod.send_due_reminders("https://example.test", send=fake) == (0, 0, 0)      # напоминания не включены
        conn.execute("UPDATE users SET reminders_opt_in = 1"); conn.commit()
        assert plusmod.send_due_reminders("https://example.test", send=fake, dry_run=True) == (0, 0, 1)
        assert plusmod.send_due_reminders("https://example.test", send=fake) == (1, 0, 0)
        assert plusmod.send_due_reminders("https://example.test", send=fake) == (0, 0, 0)      # повтор не раньше чем через 14 дней
        conn.execute("UPDATE reminders SET sent_at = ?", (old,)); conn.commit()
        assert plusmod.send_due_reminders("https://example.test", send=fake) == (1, 0, 0)      # второй и последний
        conn.execute("UPDATE reminders SET sent_at = ?", (old,)); conn.commit()
        assert plusmod.send_due_reminders("https://example.test", send=fake) == (0, 0, 0)      # лимит 2 на оценку
    assert sent[0][0] == "anna@example.com" and "/unsubscribe/" in sent[0][3] and "индекс 69" in sent[0][2]
    conn.close()


def test_failed_send_is_not_recorded_and_unsubscribe_works(app, query):
    from app import plus as plusmod
    c = app.test_client()
    register(c)
    c.post("/api/score", json=VALID)
    _make_plus(app, query)
    conn = _sqlite3.connect(app.config["DATABASE_PATH"])
    conn.execute("UPDATE score_results SET created_at = datetime('now', '-30 days')")
    conn.execute("UPDATE users SET reminders_opt_in = 1")
    conn.commit()
    with app.test_request_context(base_url="https://example.test"):
        assert plusmod.send_due_reminders("https://example.test", send=lambda *a, **k: (False, "boom")) == (0, 1, 0)
        assert query("SELECT count(*) AS n FROM reminders")[0]["n"] == 0                       # неудача не засчитана
        token = plusmod.unsubscribe_token(_user_id(query))
    assert app.test_client().get("/unsubscribe/bad-token").status_code == 404
    assert app.test_client().get(f"/unsubscribe/{token}").status_code == 200                    # без входа
    assert query("SELECT reminders_opt_in FROM users")[0]["reminders_opt_in"] == 0
    conn.close()


def test_mailer_without_keys_does_not_send(monkeypatch):
    from app import mailer
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    assert mailer.send_email("a@b.co", "A", "s", "<p>x</p>", "x") == (False, "BREVO_API_KEY / BREVO_SENDER_EMAIL не заданы")


def test_mailer_builds_brevo_request_and_hides_key(monkeypatch):
    import json
    from app import mailer
    monkeypatch.setenv("BREVO_API_KEY", "secret-key"); monkeypatch.setenv("BREVO_SENDER_EMAIL", "no-reply@example.test")
    captured = {}
    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"messageId": "<abc>"}'
    def fake_urlopen(req, timeout=0):
        captured["url"], captured["headers"], captured["body"] = req.full_url, dict(req.header_items()), json.loads(req.data)
        return Resp()
    monkeypatch.setattr(mailer.urllib.request, "urlopen", fake_urlopen)
    ok, info = mailer.send_email("a@b.co", "Анна", "Тема", "<p>x</p>", "x", unsubscribe_url="https://e.test/u")
    assert (ok, info) == (True, "<abc>") and captured["url"] == mailer.API_URL
    assert captured["headers"]["Api-key"] == "secret-key" and captured["body"]["to"] == [{"email": "a@b.co", "name": "Анна"}]
    assert captured["body"]["headers"] == {"List-Unsubscribe": "<https://e.test/u>"}


def test_home_shows_free_and_plus_plans(client, user_client=None):
    html = client.get("/").get_data(as_text=True)
    assert "Бесплатно и Plus" in html and "99" in html and 'data-plan="Plus"' in html
    assert "Start" not in html and "Balance" not in html
    res = client.post("/api/lead", json={"email": "a@b.co", "plan": "Start", "consent": True})
    assert res.status_code == 400                                              # старые тарифы больше не принимаются


def test_index_block_shows_users_result_or_example(user_client, app):
    html = app.test_client().get("/").get_data(as_text=True)
    assert "Пример результата" in html and 'aria-label="Пример: индекс 82' in html          # гостю — пример
    assert "Пример результата" in user_client.get("/").get_data(as_text=True)              # вошёл, но оценок нет — пример
    user_client.post("/api/score", json=VALID)                                              # 69
    html = user_client.get("/").get_data(as_text=True)
    block = html[html.index('class="score-story"'):html.index('id="how"') if 'id="how"' in html else None]
    assert 'aria-label="Ваш индекс: 69 из 100' in block and "Ваш последний результат" in block
    assert "Пример результата" not in block and '<div class="ring-score big" style="--v:69"><b>69</b></div>' in block
    other = app.test_client()
    register(other, email="boris@example.com", name="Борис")
    assert "Ваш последний результат" not in other.get("/").get_data(as_text=True)          # чужой результат не показывается
