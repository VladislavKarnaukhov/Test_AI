import json
import sqlite3
from pathlib import Path

from app import create_app
from app.consent import POLICY_VERSION

VALID = {"sleep": "7_8", "activity": "3_4", "nutrition": "2_3", "stress": "2"}


def test_index_renders_and_logs_page_view(consented, query):
    client = consented
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Рассчитать балл" in html
    assert "mc.yandex.ru/metrika" in html
    assert "widget.aistudio.yandexcloud.net" in html

    events = query("SELECT name, path, visitor_id FROM events")
    assert [e["name"] for e in events] == ["page_view"]
    assert events[0]["path"] == "/"
    assert events[0]["visitor_id"]


def test_visitor_id_is_stable_across_requests(consented, query):
    client = consented
    client.get("/")
    client.get("/")
    ids = {r["visitor_id"] for r in query("SELECT visitor_id FROM events")}
    assert len(ids) == 1


def test_score_ok(consented, query):
    client = consented
    res = client.post("/api/score", json=VALID)
    assert res.status_code == 200
    data = res.get_json()
    assert set(data) == {"total", "breakdown", "weakest", "summary", "tip", "recommendations",
                         "saved_to_account", "claim_token"}
    assert data["saved_to_account"] is False and data["claim_token"]

    rows = query("SELECT answers, total, breakdown, visitor_id FROM score_results")
    assert len(rows) == 1
    assert rows[0]["total"] == data["total"]
    assert json.loads(rows[0]["answers"]) == VALID
    assert json.loads(rows[0]["breakdown"]) == data["breakdown"]
    assert rows[0]["visitor_id"]
    assert [e["name"] for e in query("SELECT name FROM events")] == ["score_calculated"]


def test_score_validation_error(client, query):
    res = client.post("/api/score", json={"sleep": "bad"})
    assert res.status_code == 400
    fields = res.get_json()["fields"]
    assert set(fields) == {"sleep", "activity", "nutrition", "stress"}
    assert query("SELECT * FROM score_results") == []


def test_score_non_json(client):
    res = client.post("/api/score", data="nope", content_type="text/plain")
    assert res.status_code == 400


def test_lead_ok(consented, query):
    client = consented
    res = client.post("/api/lead", json={"email": " user@example.com ", "plan": "Balance", "consent": True})
    assert res.status_code == 200
    assert query("SELECT email, plan, policy_version FROM leads") == [
        {"email": "user@example.com", "plan": "Balance", "policy_version": POLICY_VERSION}]
    assert [e["name"] for e in query("SELECT name FROM events")] == ["lead_submitted"]


def test_lead_bad_email(client, query):
    res = client.post("/api/lead", json={"email": "not-an-email", "plan": "Start", "consent": True})
    assert res.status_code == 400
    assert "email" in res.get_json()["fields"]
    assert query("SELECT * FROM leads") == []


def test_lead_bad_plan(client, query):
    res = client.post("/api/lead", json={"email": "a@b.co", "plan": "Premium", "consent": True})
    assert res.status_code == 400
    assert "plan" in res.get_json()["fields"]
    assert query("SELECT * FROM leads") == []


def test_event_ok(consented, query):
    client = consented
    res = client.post("/api/event", json={
        "name": "anchor_click", "params": {"href": "#plans"},
        "path": "/#plans", "referrer": "https://ya.ru/",
    }, headers={"User-Agent": "pytest-agent"})
    assert res.status_code == 204
    rows = query("SELECT name, path, referrer, payload, user_agent, ip FROM events")
    assert rows == [{
        "name": "anchor_click", "path": "/#plans", "referrer": "https://ya.ru/",
        "payload": '{"href": "#plans"}', "user_agent": "pytest-agent", "ip": "127.0.0.1",
    }]


def test_event_beacon_text_plain(consented, query):
    client = consented
    res = client.post("/api/event", data=json.dumps({"name": "hashchange"}), content_type="text/plain")
    assert res.status_code == 204
    assert query("SELECT name FROM events") == [{"name": "hashchange"}]


def test_event_requires_name(consented, query):
    client = consented
    assert client.post("/api/event", json={"params": {}}).status_code == 400
    assert client.post("/api/event", json={"name": "bad name!"}).status_code == 400
    assert query("SELECT * FROM events") == []


# ---------- Согласие на обработку данных и cookie ----------

def test_lead_requires_consent(client, query):
    for payload in ({"email": "a@b.co", "plan": "Start"},
                    {"email": "a@b.co", "plan": "Start", "consent": False},
                    {"email": "a@b.co", "plan": "Start", "consent": "yes"}):
        res = client.post("/api/lead", json=payload)
        assert res.status_code == 400
        assert "consent" in res.get_json()["fields"]
    assert query("SELECT * FROM leads") == []


def test_lead_without_cookie_consent_saves_lead_but_no_events(client, query):
    res = client.post("/api/lead", json={"email": "a@b.co", "plan": "Start", "consent": True})
    assert res.status_code == 200
    assert query("SELECT email, visitor_id FROM leads") == [{"email": "a@b.co", "visitor_id": None}]
    assert query("SELECT * FROM events") == []


def test_no_tracking_without_consent(client, query):
    res = client.get("/")
    assert res.status_code == 200
    assert "Set-Cookie" not in res.headers  # ни visitor_id, ни других cookie
    assert "cookie-banner" in res.get_data(as_text=True)

    assert client.post("/api/event", json={"name": "anchor_click"}).status_code == 204
    client.post("/api/score", json=VALID)
    assert query("SELECT * FROM events") == []
    assert query("SELECT visitor_id FROM score_results") == [{"visitor_id": None}]


def test_necessary_only_does_not_track(client, query):
    client.set_cookie("vs_consent", "necessary")
    client.set_cookie("vs_consent_v", POLICY_VERSION)
    client.get("/")
    client.post("/api/event", json={"name": "anchor_click"})
    assert query("SELECT * FROM events") == []


def test_consent_all(client, query):
    res = client.post("/api/consent", json={"choice": "all"})
    assert res.status_code == 200
    cookies = res.headers.getlist("Set-Cookie")
    assert any(c.startswith("vs_consent=all") for c in cookies)
    assert any(c.startswith("vs_consent_v=" + POLICY_VERSION) for c in cookies)
    assert any(c.startswith("session=") for c in cookies)

    rows = query("SELECT visitor_id, choice, policy_version FROM cookie_consents")
    assert len(rows) == 1 and rows[0]["choice"] == "all" and rows[0]["visitor_id"]
    assert rows[0]["policy_version"] == POLICY_VERSION

    client.get("/")  # cookie согласия уже у клиента — теперь логируем
    events = query("SELECT name, visitor_id FROM events")
    assert events == [{"name": "page_view", "visitor_id": rows[0]["visitor_id"]}]


def test_consent_revoke_clears_visitor(consented, query):
    consented.get("/")
    res = consented.post("/api/consent", json={"choice": "necessary"})
    assert res.status_code == 200
    assert query("SELECT visitor_id, choice FROM cookie_consents") == [{"visitor_id": None, "choice": "necessary"}]
    consented.get("/")
    assert [e["name"] for e in query("SELECT name FROM events")] == ["page_view"]  # только до отзыва


def test_consent_invalid_choice(client, query):
    assert client.post("/api/consent", json={"choice": "maybe"}).status_code == 400
    assert query("SELECT * FROM cookie_consents") == []


def test_privacy_page(client):
    res = client.get("/privacy")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Политика обработки персональных данных" in html
    assert POLICY_VERSION in html
    assert "vs_consent" in html


def test_metrika_only_loads_with_consent(client):
    html = client.get("/").get_data(as_text=True)
    assert "window.vsLoadMetrika=function" in html
    assert "mc.yandex.ru/watch" not in html  # noscript-пиксель без согласия убран


def test_migration_adds_policy_version(tmp_path):
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE leads (id INTEGER PRIMARY KEY AUTOINCREMENT, visitor_id TEXT,"
                 " email TEXT NOT NULL, plan TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')))")
    conn.execute("INSERT INTO leads (email, plan) VALUES ('old@example.com', 'Start')")
    conn.commit()
    conn.close()

    create_app({"TESTING": True, "DATABASE_PATH": str(db_path)})

    conn = sqlite3.connect(db_path)
    columns = [r[1] for r in conn.execute("PRAGMA table_info(leads)")]
    rows = conn.execute("SELECT email, policy_version FROM leads").fetchall()
    conn.close()
    assert "policy_version" in columns
    assert rows == [("old@example.com", None)]


def test_consent_for_old_policy_version_is_ignored(client, query):
    client.set_cookie("vs_consent", "all")
    client.set_cookie("vs_consent_v", "2000-01-01")
    res = client.get("/")
    assert "Set-Cookie" not in res.headers
    client.post("/api/event", json={"name": "anchor_click"})
    assert query("SELECT * FROM events") == []


# ---------- Контекст посетителя ----------

CHROME_ANDROID = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36")
CONTEXT = {
    "landing_path": "/", "referrer": "https://www.google.com/search?q=vitascore",
    "language": "ru-RU", "timezone": "Europe/Moscow", "screen": "412x915",
    "utm_source": "Telegram", "utm_medium": "social", "utm_campaign": "launch",
}


def test_visitor_context_saved(consented, query):
    consented.get("/")
    res = consented.post("/api/visitor", json=CONTEXT, headers={"User-Agent": CHROME_ANDROID})
    assert res.status_code == 204
    rows = query("SELECT * FROM visitors")
    assert len(rows) == 1
    v = rows[0]
    assert v["visitor_id"] == query("SELECT visitor_id FROM events")[0]["visitor_id"]
    assert (v["source"], v["utm_source"], v["utm_medium"], v["utm_campaign"]) == ("telegram", "Telegram", "social", "launch")
    assert v["referrer"] == CONTEXT["referrer"]
    assert (v["language"], v["timezone"], v["country"], v["screen"]) == ("ru-RU", "Europe/Moscow", "RU", "412x915")
    assert (v["device_type"], v["os"], v["browser"]) == ("mobile", "Android", "Chrome")


def test_visitor_first_touch_is_kept(consented, query):
    consented.post("/api/visitor", json=CONTEXT)
    consented.post("/api/visitor", json={"landing_path": "/privacy", "utm_source": "vk",
                                         "referrer": "http://localhost/"})
    v = query("SELECT source, utm_source, landing_path, first_seen, last_seen FROM visitors")[0]
    assert (v["source"], v["utm_source"], v["landing_path"]) == ("telegram", "Telegram", "/")


def test_visitor_referrer_and_direct(consented, app, query):
    consented.post("/api/visitor", json={"referrer": "https://www.yandex.ru/search/?text=x"})
    assert query("SELECT source FROM visitors")[0]["source"] == "yandex.ru"

    other = app.test_client()  # второй посетитель
    other.set_cookie("vs_consent", "all")
    other.set_cookie("vs_consent_v", POLICY_VERSION)
    other.post("/api/visitor", json={"referrer": "http://localhost/#plans"})  # внутренний переход
    rows = query("SELECT source, referrer FROM visitors ORDER BY rowid")
    assert rows[1] == {"source": "(direct)", "referrer": None}


def test_visitor_invalid_values_dropped(consented, query):
    consented.post("/api/visitor", json={"language": "<script>", "timezone": "../../etc",
                                         "screen": "huge", "utm_source": "x" * 500},
                   headers={"Accept-Language": "en-US,en;q=0.9"})
    v = query("SELECT language, timezone, screen, utm_source, country FROM visitors")[0]
    assert v["language"] == "en-US"  # из заголовка Accept-Language
    assert v["timezone"] is None and v["screen"] is None
    assert len(v["utm_source"]) == 200
    assert v["country"] == "US"


def test_visitor_ignored_without_consent(client, query):
    assert client.post("/api/visitor", json=CONTEXT).status_code == 204
    assert query("SELECT * FROM visitors") == []


def test_reports_sql_runs(consented, app):
    consented.post("/api/visitor", json=CONTEXT)
    consented.post("/api/lead", json={"email": "a@b.co", "plan": "Balance", "consent": True})
    consented.post("/api/score", json=VALID)
    sql = (Path(__file__).parent.parent / "reports.sql").read_text(encoding="utf-8")
    body = "\n".join(l for l in sql.splitlines() if not l.startswith((".", "--")))
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    try:
        results = [conn.execute(stmt).fetchall() for stmt in body.split(";") if stmt.strip()]
    finally:
        conn.close()
    assert len(results) == 6
    assert ("telegram", 1, 1, 100.0) in results[0]
    assert results[1] == [("launch", "Telegram", "social", 1, 0, 1)]
