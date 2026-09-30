"""Методика VitaScore v1.0 — проверки по тексту методики."""
import pytest

from app.scoring import METHOD_VERSION, QUESTIONS, STEPS, ScoringError, calculate_score, describe_answers
from tests.answers import BEST, EXAMPLE, answers


def test_worked_example_from_methodology():
    """«Пример расчёта» из методики: 61 / 44 / 58 / 75 → 60, хорошая база, фокус — движение."""
    r = calculate_score(EXAMPLE)
    assert r["breakdown"] == {"sleep": 61, "activity": 44, "nutrition": 58, "recovery": 75}
    assert r["total"] == 60
    assert r["level"] == "good" and r["level_name"] == "Хорошая база"
    assert r["version"] == METHOD_VERSION == "1.0"
    assert r["flags"] == []
    assert r["focus"]["sphere"] == "activity" and r["focus"]["item"] == "aerobic"
    assert "2 прогулки" in r["focus"]["text"] and "150 минут" in r["focus"]["text"]
    assert r["active_minutes"] == 90


def test_maximum_is_100():
    r = calculate_score(BEST)
    assert r["total"] == 100 and set(r["breakdown"].values()) == {100}
    assert r["level"] == "high" and r["focus"]["type"] == "maintain"


def test_aerobic_formula_and_cap():
    # 5 дней × 30 минут умеренно = 150 → 100; интенсивная считается вдвое
    assert calculate_score(answers(m1="5", m2="30", m3="moderate"))["active_minutes"] == 150
    r = calculate_score(answers(m1="2", m2="45", m3="vigorous", m4="2plus", m5="lt6"))
    assert r["active_minutes"] == 180 and r["breakdown"]["activity"] == 100


def test_no_activity_skips_minutes_questions():
    a = answers(m1="0")
    del a["m2"], a["m3"]
    r = calculate_score(a)
    assert r["active_minutes"] == 0
    assert r["breakdown"]["activity"] == round(.2 * 100 + .2 * 100)  # силовые и сидение из BEST


def test_sleep_norm_for_65_plus():
    young = calculate_score(answers(s1="8_9"))["breakdown"]["sleep"]
    old = calculate_score(answers(age="65plus", s1="8_9"))["breakdown"]["sleep"]
    assert young == 100 and old == 94  # (70 + 100·4) / 5


def test_psych_sphere_is_phq4():
    r = calculate_score(answers(p1="3", p2="3", p3="3", p4="3"))
    assert r["breakdown"]["recovery"] == 0 and r["screens"]["phq4"] == 12


def test_under_18_rejected():
    with pytest.raises(ScoringError) as exc:
        calculate_score(answers(age="under18"))
    assert exc.value.code == "age_restricted"


def test_missing_and_invalid():
    with pytest.raises(ScoringError) as exc:
        calculate_score({})
    assert set(exc.value.errors) == set(QUESTIONS)  # m2/m3 тоже нужны, пока m1 не «0»
    with pytest.raises(ScoringError) as exc:
        calculate_score(answers(s1="10h", p1="4"))
    assert set(exc.value.errors) == {"s1", "p1"}
    with pytest.raises(ScoringError):
        calculate_score(["not", "a", "dict"])


# ---------- Красные флаги ----------

def codes(r):
    return [f["code"] for f in r["flags"]]


def test_flag_mood_phq2_and_gad2():
    r = calculate_score(answers(p1="2", p2="1"))
    assert codes(r) == ["mood"] and "подавленного настроения" in r["flags"][0]["text"]
    r = calculate_score(answers(p3="2", p4="1"))
    assert codes(r) == ["mood"] and "тревоги" in r["flags"][0]["text"]
    assert codes(calculate_score(answers(p1="1", p2="1", p3="1", p4="1"))) == []  # PHQ-4 = 4, подшкалы < 3


def test_flag_distress_replaces_mood_and_has_contacts():
    r = calculate_score(answers(p1="3", p2="2", p3="2", p4="2"))
    assert codes(r) == ["distress"] and r["flags"][0]["contacts"] and r["flags"][0]["level"] == "urgent"


def test_flag_insomnia_and_apnea():
    assert "insomnia" in codes(calculate_score(answers(s3="3plus", s5="1")))
    assert "insomnia" not in codes(calculate_score(answers(s3="3plus", s5="2")))
    r = calculate_score(answers(s6="yes", s4="daily"))
    assert "apnea" in codes(r) and "дневной сонливостью" in r["flags"][codes(r).index("apnea")]["text"]
    assert "apnea" not in codes(calculate_score(answers(s6="unknown")))


def test_red_flag_makes_focus_specialist():
    r = calculate_score(answers(s6="yes"))
    assert r["focus"]["type"] == "specialist"


def test_restriction_changes_movement_advice_not_score():
    base = calculate_score(answers(m1="1", m2="20"))
    r = calculate_score(answers(m1="1", m2="20", restriction="yes"))
    assert r["breakdown"] == base["breakdown"]
    assert codes(r) == ["restriction"] and r["focus"]["type"] == "step"
    moves = [x for x in r["recommendations"] if x["sphere"] == "activity"]
    assert [x["title"] for x in moves] == ["Обсудите нагрузку с врачом"]


# ---------- Фокус недели и рекомендации ----------

def test_focus_picks_largest_weighted_gap():
    # слабее всего питание; сладкие напитки (0) отстают сильнее овощей (40)
    r = calculate_score(answers(n1="2", n2="daily"))
    assert r["focus"]["sphere"] == "nutrition" and r["focus"]["item"] == "n2"


def test_recommendations_order():
    r = calculate_score(EXAMPLE)
    spheres = []
    for rec in r["recommendations"]:
        if rec["sphere"] not in spheres:
            spheres.append(rec["sphere"])
    assert spheres == ["activity", "nutrition", "sleep", "recovery"]
    assert r["recommendations"][0]["item"] == "aerobic"


def test_describe_answers_groups():
    groups = dict(describe_answers(calculate_score(EXAMPLE)["answers"]))
    assert dict(groups["Сон"])["Продолжительность"] == "6–7"
    assert dict(groups["Движение"])["Интенсивность"].startswith("Умеренно")


def test_every_question_belongs_to_a_step():
    assert [key for key, *_ in STEPS] == ["filter", "sleep", "activity", "nutrition", "recovery"]
    assert len(QUESTIONS) == 22
