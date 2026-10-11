import re
from datetime import date, timedelta

import pytest

from tests.test_account import PASSWORD, csrf, register

TODAY = date.today()


def day(offset=0, **fields):
    return {"date": (TODAY - timedelta(days=offset)).isoformat(), **fields}


def token(client):
    html = client.get("/account/settings").get_data(as_text=True)
    return re.search(r'data-csrf="([^"]+)"', html).group(1)


@pytest.fixture
def api(user_client):
    t = token(user_client)

    def call(path, body, headers=True):
        return user_client.post(path, json=body, headers={"X-CSRF-Token": t} if headers else {})
    return call


@pytest.fixture
def user_client(client):
    assert register(client).status_code == 302
    return client


@pytest.fixture
def connected(api):
    assert api("/api/health-sync/connect", {"consent": True}).status_code == 200
    return api


def test_requires_login(client):
    assert client.post("/api/health-sync", json={"days": []}).status_code == 401
    assert client.post("/api/health-sync/connect", json={"consent": True}).status_code == 401


def test_requires_csrf(api):
    assert api("/api/health-sync/connect", {"consent": True}, headers=False).status_code == 400


def test_connect_needs_explicit_consent(api, query):
    assert api("/api/health-sync/connect", {}).status_code == 400
    assert api("/api/health-sync/connect", {"consent": "yes"}).status_code == 400
    assert query("SELECT * FROM health_connections") == []


def test_sync_before_connect_forbidden(api, query):
    assert api("/api/health-sync", {"days": [day(steps=10)]}).status_code == 403
    assert query("SELECT * FROM health_sync_days") == []


def test_connect_records_consent_version(connected, query):
    from app.consent import POLICY_VERSION
    assert query("SELECT consent_version, source FROM health_connections") == [
        {"consent_version": POLICY_VERSION, "source": "health_connect"}]


def test_sync_saves_and_upserts(connected, query):
    r = connected("/api/health-sync", {"days": [day(0, steps=5000, sleep_minutes=420, heart_rate_avg=61.46), day(1, steps=9000)]})
    assert r.get_json() == {"ok": True, "saved": 2}
    connected("/api/health-sync", {"days": [day(0, steps=6000)]})
    rows = query("SELECT date, steps, sleep_minutes, heart_rate_avg FROM health_sync_days ORDER BY date DESC")
    assert len(rows) == 2
    assert rows[0]["steps"] == 6000 and rows[0]["sleep_minutes"] is None  # день заменён целиком
    assert query("SELECT last_sync_at FROM health_connections")[0]["last_sync_at"]


@pytest.mark.parametrize("bad", [
    day(0),                                   # нет показателей
    day(0, steps=-1), day(0, steps=10**7), day(0, steps=True), day(0, steps="5000"),
    day(0, heart_rate_avg=5), day(0, sleep_minutes=5000),
    {"date": "вчера", "steps": 1}, {"steps": 1},
    day(-5, steps=1),                         # будущее
    day(60, steps=1),                         # слишком давно
    "строка", None,
])
def test_invalid_days_skipped(connected, query, bad):
    r = connected("/api/health-sync", {"days": [bad]})
    assert r.status_code == 200 and r.get_json()["saved"] == 0
    assert query("SELECT * FROM health_sync_days") == []


def test_bad_payload(connected):
    assert connected("/api/health-sync", {"days": "x"}).status_code == 400
    assert connected("/api/health-sync", {"days": [day(0, steps=1)] * 40}).status_code == 400


def test_data_isolated_per_user(client, app, query):
    register(client)
    t = token(client)
    client.post("/api/health-sync/connect", json={"consent": True}, headers={"X-CSRF-Token": t})
    client.post("/api/health-sync", json={"days": [day(0, steps=111)]}, headers={"X-CSRF-Token": t})
    other = app.test_client()
    register(other, email="boris@example.com", name="Борис")
    page = other.get("/account/settings").get_data(as_text=True)
    assert "111" not in page and 'data-connected="false"' in page


def test_settings_shows_days(connected, user_client):
    connected("/api/health-sync", {"days": [day(0, steps=12345)]})
    page = user_client.get("/account/settings").get_data(as_text=True)
    assert "12345" in page and 'data-connected="true"' in page


def test_disconnect_deletes_data(connected, user_client, query):
    connected("/api/health-sync", {"days": [day(0, steps=1)]})
    res = user_client.post("/account/health/disconnect", data={"csrf_token": token(user_client)})
    assert res.status_code == 302
    assert query("SELECT * FROM health_sync_days") == [] and query("SELECT * FROM health_connections") == []


def test_disconnect_needs_csrf(connected, user_client, query):
    assert user_client.post("/account/health/disconnect", data={}).status_code == 400
    assert len(query("SELECT * FROM health_connections")) == 1


def test_account_deletion_removes_health_data(connected, user_client, query):
    connected("/api/health-sync", {"days": [day(0, steps=1)]})
    res = user_client.post("/account/delete", data={"csrf_token": token(user_client), "password": PASSWORD})
    assert res.status_code == 302
    assert query("SELECT * FROM health_sync_days") == [] and query("SELECT * FROM health_connections") == []


def test_consent_and_privacy_mention_wearables(client):
    assert "Данные из приложений здоровья" in client.get("/consent/health").get_data(as_text=True)
    assert "Health Connect" in client.get("/privacy").get_data(as_text=True)
