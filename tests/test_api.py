import json

VALID = {"sleep": "7_8", "activity": "3_4", "nutrition": "2_3", "stress": "2"}


def test_index_renders_and_logs_page_view(client, query):
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


def test_visitor_id_is_stable_across_requests(client, query):
    client.get("/")
    client.get("/")
    ids = {r["visitor_id"] for r in query("SELECT visitor_id FROM events")}
    assert len(ids) == 1


def test_score_ok(client, query):
    res = client.post("/api/score", json=VALID)
    assert res.status_code == 200
    data = res.get_json()
    assert set(data) == {"total", "breakdown", "weakest", "summary", "tip"}

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


def test_lead_ok(client, query):
    res = client.post("/api/lead", json={"email": " user@example.com ", "plan": "Balance"})
    assert res.status_code == 200
    assert query("SELECT email, plan FROM leads") == [{"email": "user@example.com", "plan": "Balance"}]
    assert [e["name"] for e in query("SELECT name FROM events")] == ["lead_submitted"]


def test_lead_bad_email(client, query):
    res = client.post("/api/lead", json={"email": "not-an-email", "plan": "Start"})
    assert res.status_code == 400
    assert "email" in res.get_json()["fields"]
    assert query("SELECT * FROM leads") == []


def test_lead_bad_plan(client, query):
    res = client.post("/api/lead", json={"email": "a@b.co", "plan": "Premium"})
    assert res.status_code == 400
    assert "plan" in res.get_json()["fields"]
    assert query("SELECT * FROM leads") == []


def test_event_ok(client, query):
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


def test_event_beacon_text_plain(client, query):
    res = client.post("/api/event", data=json.dumps({"name": "hashchange"}), content_type="text/plain")
    assert res.status_code == 204
    assert query("SELECT name FROM events") == [{"name": "hashchange"}]


def test_event_requires_name(client, query):
    assert client.post("/api/event", json={"params": {}}).status_code == 400
    assert client.post("/api/event", json={"name": "bad name!"}).status_code == 400
    assert query("SELECT * FROM events") == []
