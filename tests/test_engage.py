"""Недельный ритм: DAU/WAU/MAU, шаг недели, пульс, недельное письмо."""
import sqlite3
from datetime import datetime, timedelta

from app import engage
from tests.test_account import VALID, csrf, login, register

PULSE = {"sleep": "4", "activity": "3", "nutrition": "2", "mood": "5"}


def _tok(c):
    return csrf(c, "/account")


def _db(app):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.row_factory = sqlite3.Row
    return conn


def _with_score(app):
    c = app.test_client()
    register(c)
    c.post("/api/score", json=VALID)
    return c


def test_week_start_is_monday_in_moscow():
    # вс 25.10.2026 22:00 UTC = пн 26.10 01:00 МСК
    assert engage.week_start(datetime(2026, 10, 25, 22, 0)) == "2026-10-26"
    assert engage.week_start(datetime(2026, 10, 25, 20, 0)) == "2026-10-19"


def test_login_and_dashboard_record_activity(app, query):
    c = app.test_client()
    register(c)
    c.get("/account")
    assert query("SELECT kind FROM activity") == [{"kind": "cabinet"}]       # одна запись на день и вид
    c.get("/account")
    assert len(query("SELECT * FROM activity")) == 1


def test_dau_wau_mau_windows(app):
    with app.app_context():
        db = engage.get_db()
        today = datetime.strptime(engage.today_utc(), "%Y-%m-%d")
        for uid, back in ((1, 0), (2, 3), (3, 20), (4, 45)):
            db.execute("INSERT INTO activity (user_id, day, kind) VALUES (?, ?, 'cabinet')",
                       (uid, (today - timedelta(days=back)).strftime("%Y-%m-%d")))
        db.commit()
        block = engage.activity_block([engage.today_utc()])
        assert (block["dau"], block["wau"], block["mau"]) == (1, 2, 3)
        assert block["wau_mau"] == 66.7 and len(block["wau_series"]) == 12


def test_week_step_toggle_records_activity_and_streak(app, query):
    c = _with_score(app)
    assert "Шаг недели" in c.get("/account").get_data(as_text=True)
    c.post("/account/week-step", data={"csrf_token": _tok(c)})
    assert len(query("SELECT * FROM week_steps")) == 1
    assert {r["kind"] for r in query("SELECT kind FROM activity")} == {"cabinet", "step"}
    c.post("/account/week-step", data={"csrf_token": _tok(c)})               # повторное нажатие снимает отметку
    assert query("SELECT * FROM week_steps") == []
    assert c.post("/account/week-step").status_code == 400                    # без CSRF


def test_week_step_requires_a_score(app):
    c = app.test_client()
    register(c)
    r = c.post("/account/week-step", data={"csrf_token": _tok(c)})
    assert r.status_code == 302


def test_streak_counts_consecutive_weeks(app):
    c = _with_score(app)
    with app.app_context():
        db = engage.get_db()
        now = datetime(2026, 10, 28, 12, 0)
        for w in ("2026-10-26", "2026-10-19", "2026-10-12", "2026-09-28"):
            db.execute("INSERT INTO week_steps (user_id, week_start) VALUES (1, ?)", (w,))
        db.commit()
        assert engage.streak(1, now) == 3
        assert engage.streak(1, datetime(2026, 11, 3, 12, 0)) == 3           # текущая неделя пуста — серия не обрывается
        assert engage.streak(1, datetime(2026, 11, 10, 12, 0)) == 0
    del c


def test_pulse_requires_consent_and_all_fields(app, query):
    c = _with_score(app)
    r = c.post("/account/pulse", data={"csrf_token": _tok(c), **PULSE})
    assert r.status_code == 302 and query("SELECT * FROM pulses") == []      # без согласия не сохраняем
    r = c.post("/account/pulse", data={"csrf_token": _tok(c), "pulse_consent": "on", **PULSE, "mood": "9"})
    assert query("SELECT * FROM pulses") == []
    c.post("/account/pulse", data={"csrf_token": _tok(c), "pulse_consent": "on", **PULSE})
    assert len(query("SELECT * FROM pulses")) == 1
    assert query("SELECT pulse_consent_at FROM users")[0]["pulse_consent_at"]
    assert "pulse" in {r["kind"] for r in query("SELECT kind FROM activity")}


def test_pulse_is_upserted_per_week_and_scored(app, query):
    c = _with_score(app)
    c.post("/account/pulse", data={"csrf_token": _tok(c), "pulse_consent": "on", **PULSE})
    c.post("/account/pulse", data={"csrf_token": _tok(c), **{**PULSE, "mood": "1"}})   # согласие уже дано
    rows = query("SELECT * FROM pulses")
    assert len(rows) == 1 and rows[0]["mood"] == 1
    assert engage.pulse_score({"sleep": 5, "activity": 5, "nutrition": 5, "mood": 5}) == 100
    assert engage.pulse_score({"sleep": 1, "activity": 1, "nutrition": 1, "mood": 1}) == 0


def test_pulse_chart_shows_line_between_index_points(app):
    c = _with_score(app)
    with app.app_context():
        db = engage.get_db()
        for w, v in (("2026-10-05", 2), ("2026-10-12", 3), ("2026-10-19", 4)):
            db.execute("INSERT INTO pulses (user_id, week_start, sleep, activity, nutrition, mood) VALUES (1, ?, ?, ?, ?, ?)",
                       (w, v, v, v, v))
        db.commit()
    html = c.get("/account").get_data(as_text=True)
    assert 'class="pl"' in html and html.count('class="pd"') == 3 and 'class="pi"' in html


def test_pulse_data_is_private_and_deleted(app, query):
    c = _with_score(app)
    c.post("/account/pulse", data={"csrf_token": _tok(c), "pulse_consent": "on", **PULSE})
    other = app.test_client()
    register(other, email="boris@example.com", name="Борис")
    other.post("/api/score", json=VALID)
    html = other.get("/account").get_data(as_text=True)
    assert "pulse-done" not in html and 'class="pl"' not in html             # чужие отметки не видны
    c.post("/account/pulse/delete", data={"csrf_token": _tok(c)})
    assert query("SELECT * FROM pulses") == []
    assert query("SELECT pulse_consent_at FROM users WHERE id = 1")[0]["pulse_consent_at"] is None


def test_delete_account_removes_engagement_data(app, query):
    c = _with_score(app)
    c.post("/account/week-step", data={"csrf_token": _tok(c)})
    c.post("/account/pulse", data={"csrf_token": _tok(c), "pulse_consent": "on", **PULSE})
    c.post("/account/delete", data={"csrf_token": csrf(c, "/account/settings"), "password": "correct-horse-1"})
    for table in ("activity", "week_steps", "pulses", "weekly_mail"):
        assert query(f"SELECT count(*) AS n FROM {table}")[0]["n"] == 0


def test_register_weekly_checkbox_is_optional(app, query):
    register(app.test_client())
    register(app.test_client(), email="b@example.com", weekly="on")
    assert [r["weekly_opt_in"] for r in query("SELECT weekly_opt_in FROM users ORDER BY id")] == [0, 1]


def test_weekly_mail_sent_once_per_week_to_opted_in(app, query):
    c = _with_score(app)
    sent = []

    def fake(to, name, subject, html, text, unsubscribe_url=None):
        sent.append((to, text, unsubscribe_url))
        return True, "id"

    with app.test_request_context(base_url="https://example.test"):
        assert engage.send_weekly("https://example.test", send=fake) == (0, 0, 0)       # письмо не включено
        c.post("/account/weekly-mail", data={"csrf_token": _tok(c), "weekly": "on"})
        assert engage.send_weekly("https://example.test", send=fake, dry_run=True) == (0, 0, 1)
        assert engage.send_weekly("https://example.test", send=fake) == (1, 0, 0)
        assert engage.send_weekly("https://example.test", send=fake) == (0, 0, 0)       # раз в неделю
        later = datetime.utcnow() + timedelta(days=8)
        assert engage.send_weekly("https://example.test", send=fake, now=later) == (1, 0, 0)
    assert "/unsubscribe/" in sent[0][2] and "/account#week" in sent[0][1]


def test_failed_weekly_send_is_retried(app, query):
    c = _with_score(app)
    c.post("/account/weekly-mail", data={"csrf_token": _tok(c), "weekly": "on"})
    with app.test_request_context(base_url="https://example.test"):
        assert engage.send_weekly("https://example.test", send=lambda *a, **k: (False, "boom")) == (0, 1, 0)
        assert query("SELECT count(*) AS n FROM weekly_mail")[0]["n"] == 0
        assert engage.send_weekly("https://example.test", send=lambda *a, **k: (True, "id")) == (1, 0, 0)


def test_unsubscribe_turns_off_weekly_mail(app, query):
    from app import plus
    c = _with_score(app)
    c.post("/account/weekly-mail", data={"csrf_token": _tok(c), "weekly": "on"})
    with app.test_request_context(base_url="https://example.test"):
        token = plus.unsubscribe_token(1)
    assert app.test_client().get(f"/unsubscribe/{token}").status_code == 200
    assert query("SELECT weekly_opt_in FROM users")[0]["weekly_opt_in"] == 0


def test_admin_shows_activity_block(app, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    boss = app.test_client()
    register(boss, email="boss@example.com", name="Босс")
    html = boss.get("/admin").get_data(as_text=True)
    assert "DAU" in html and "WAU" in html and "MAU" in html and 'id="activity"' in html


def test_privacy_mentions_pulse_and_weekly_mail(client):
    html = client.get("/privacy").get_data(as_text=True)
    assert "пульс" in html and "недельное письмо" in html
    assert 'id="pulse"' in client.get("/consent/health").get_data(as_text=True)


def test_pulse_items_are_complete_and_shown(app):
    assert [i["key"] for i in engage.PULSE_ITEMS] == ["sleep", "activity", "nutrition", "mood"]
    assert all(len(i["options"]) == 5 and i["question"] for i in engage.PULSE_ITEMS)
    c = _with_score(app)
    html = c.get("/account").get_data(as_text=True)
    for i in engage.PULSE_ITEMS:
        assert i["question"] in html
    c.post("/account/pulse", data={"csrf_token": _tok(c), "pulse_consent": "on", **PULSE})
    assert "Хорошее" in c.get("/account").get_data(as_text=True)         # сон 4 → подпись варианта


def test_methodology_page_describes_pulse(client):
    html = client.get("/methodology").get_data(as_text=True)
    assert 'id="pulse-method"' in html and "Consensus Sleep Diary" in html and "ВОЗ-5" in html


# ---------- Plus: отчёт месяца и превью ----------

def _make_plus_user(app, email="anna@example.com"):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.execute("UPDATE users SET plus_until = datetime('now', '+20 days') WHERE email = ?", (email,))
    conn.commit()
    conn.close()


def test_report_requires_plus(app):
    c = _with_score(app)
    r = c.get("/account/report")
    assert r.status_code == 302 and "#plus" in r.headers["Location"]
    assert app.test_client().get("/account/report").status_code == 302          # без входа — на вход


def test_report_shows_own_scores_plan_and_pulse(app, query):
    c = _with_score(app)
    c.post("/api/score", json=VALID)
    _make_plus_user(app)
    c.post("/account/pulse", data={"csrf_token": _tok(c), "pulse_consent": "on", **PULSE})
    html = c.get("/account/report").get_data(as_text=True)
    assert "Отчёт месяца" in html and "data-print" in html and 'class="report-spheres"' in html
    assert "Шагов плана выполнено" in html and "Сохранить в PDF" in html
    other = app.test_client()
    register(other, email="boris@example.com", name="Борис")
    _make_plus_user(app, "boris@example.com")
    page = other.get("/account/report").get_data(as_text=True)
    assert "Пройдите анкету" in page and "Анна" not in page                      # чужие данные не попадают


def test_locked_preview_shows_first_step_but_hides_the_rest(app):
    c = _with_score(app)
    html = c.get("/account").get_data(as_text=True)
    assert "plus-preview" in html and html.count('class="skeleton"') == 2 and "Откроется в Plus" in html
    assert "plan-check" not in html


def test_plan_steps_show_sphere_score(app):
    c = _with_score(app)
    _make_plus_user(app)
    html = c.get("/account").get_data(as_text=True)
    assert 'class="plan-score"' in html


def test_plan_puts_filler_steps_last():
    from app.plus import build_plan
    recs = [{"sphere": "nicotine", "level": "mid", "item": None, "title": "Поддерживайте", "text": "t"},
            {"sphere": "sleep", "level": "mid", "item": "sl1", "title": "Раньше спать", "text": "t"},
            {"sphere": "activity", "level": "high", "item": "aerobic", "title": "Прогулки", "text": "t"}]
    assert [s["title"] for s in build_plan(recs)] == ["Раньше спать", "Прогулки", "Поддерживайте"]


def test_compare_is_visual_with_summary_and_accessible_table(app):
    c = _with_score(app)
    c.post("/api/score", json=VALID)
    _make_plus_user(app)
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.execute("UPDATE score_results SET created_at = datetime('now', '-40 days') WHERE id = 1")
    conn.commit()
    conn.close()
    html = c.get("/account").get_data(as_text=True)
    assert 'class="cmp-summary"' in html and 'class="cmp"' in html and "Больше всего резерва" in html
    assert '<th scope="row">Итог</th>' in html and 'class="visually-hidden"><table class="compare"' in html


def test_source_conversion_counts_people_not_anketas(app):
    from app import admin
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.execute("INSERT INTO visitors (visitor_id, source) VALUES ('v1', 'direct'), ('v2', 'direct')")
    for _ in range(3):      # один человек прошёл анкету три раза
        conn.execute("INSERT INTO score_results (visitor_id, answers, total, breakdown) VALUES ('v1', '{}', 50, '{}')")
    conn.execute("INSERT INTO leads (visitor_id, email, plan) VALUES ('v1', 'a@example.com', 'Plus'), ('v1', 'a@example.com', 'Plus')")
    conn.commit()
    conn.close()
    with app.app_context():
        row = [s for s in admin.collect("all")["sources"] if s["name"] == "direct"][0]
    assert (row["visitors"], row["people"], row["scores"], row["leads"]) == (2, 1, 3, 1)
    assert row["conv"] == 50.0                   # раньше было 150%


# ---------- Автоматический пробный период и отчёт месяца по e-mail ----------

def test_first_pulse_opens_trial_once(app, query):
    c = _with_score(app)
    assert "Попробуйте бесплатно" in c.get("/account").get_data(as_text=True)
    c.post("/account/pulse", data={"csrf_token": _tok(c), "pulse_consent": "on", **PULSE})
    u = query("SELECT plus_until, plus_is_trial, trial_used_at FROM users")[0]
    assert u["plus_until"] and u["plus_is_trial"] == 1 and u["trial_used_at"]
    html = c.get("/account").get_data(as_text=True)
    assert "пробный период до" in html and "plus-trial" in html
    # повторный пульс (правка отметки) пробный период не продлевает
    c.post("/account/pulse", data={"csrf_token": _tok(c), **{**PULSE, "mood": "1"}})
    assert query("SELECT plus_until FROM users")[0]["plus_until"] == u["plus_until"]


def test_trial_is_not_given_to_paying_user_or_twice(app, query):
    from app import plus
    c = _with_score(app)
    _make_plus_user(app)                                                       # у человека уже оплаченный Plus
    c.post("/account/pulse", data={"csrf_token": _tok(c), "pulse_consent": "on", **PULSE})
    assert query("SELECT plus_is_trial, trial_used_at FROM users")[0] == {"plus_is_trial": 0, "trial_used_at": None}
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.execute("UPDATE users SET plus_until = datetime('now', '-1 day'), trial_used_at = datetime('now', '-20 days')")
    conn.commit()
    conn.close()
    with app.app_context():
        assert plus.grant_trial(1) is None                                     # второй раз не выдаём
    assert "Пробный период закончился" in c.get("/account").get_data(as_text=True)


def test_paid_grant_replaces_trial_flag(app, query):
    from app import plus
    c = _with_score(app)
    c.post("/account/pulse", data={"csrf_token": _tok(c), "pulse_consent": "on", **PULSE})
    with app.app_context():
        plus.grant(1, 30)
    assert query("SELECT plus_is_trial FROM users")[0]["plus_is_trial"] == 0


def test_report_mail_requires_opt_in_and_is_sent_once_a_month(app, query):
    from app import monthly
    c = _with_score(app)
    _make_plus_user(app)
    sent = []

    def fake(to, name, subject, html, text, unsubscribe_url=None):
        sent.append((to, text, unsubscribe_url))
        return True, "id"

    with app.test_request_context(base_url="https://example.test"):
        assert monthly.send_monthly("https://example.test", send=fake) == (0, 0, 0)       # согласия нет — писем нет
        c.post("/account/report-mail", data={"csrf_token": _tok(c), "report": "on"})
        assert monthly.send_monthly("https://example.test", send=fake, dry_run=True) == (0, 0, 1)
        assert monthly.send_monthly("https://example.test", send=fake) == (1, 0, 0)
        assert monthly.send_monthly("https://example.test", send=fake) == (0, 0, 0)       # в этом месяце уже отправлено
        nxt = datetime.utcnow() + timedelta(days=35)
        conn = sqlite3.connect(app.config["DATABASE_PATH"])
        conn.execute("UPDATE users SET plus_until = datetime('now', '+90 days')")
        conn.commit()
        conn.close()
        assert monthly.send_monthly("https://example.test", send=fake, now=nxt) == (1, 0, 0)  # следующий месяц
    assert "Итог:" in sent[0][1] and "/account/report" in sent[0][1] and "/unsubscribe/" in sent[0][2]


def test_failed_monthly_send_is_retried_and_unsubscribe_works(app, query):
    from app import monthly, plus
    c = _with_score(app)
    _make_plus_user(app)
    c.post("/account/report-mail", data={"csrf_token": _tok(c), "report": "on"})
    with app.test_request_context(base_url="https://example.test"):
        assert monthly.send_monthly("https://example.test", send=lambda *a, **k: (False, "boom")) == (0, 1, 0)
        assert query("SELECT count(*) AS n FROM monthly_mail")[0]["n"] == 0
        token = plus.unsubscribe_token(1)
    assert app.test_client().get(f"/unsubscribe/{token}").status_code == 200
    assert query("SELECT report_opt_in FROM users")[0]["report_opt_in"] == 0


def test_report_mail_toggle_is_plus_only(app, query):
    c = _with_score(app)
    r = c.post("/account/report-mail", data={"csrf_token": _tok(c), "report": "on"})
    assert r.status_code == 302 and query("SELECT report_opt_in FROM users")[0]["report_opt_in"] == 0
