"""Методика VitaScore v2.0 — проверки по тексту методики."""
import pytest

from app.scoring import (CORE_DOMAINS, LE8_PA, LE8_SLEEP, METHOD_VERSION, QUESTIONS, ScoringError, calculate_score,
                         describe_answers, validate)
from tests.answers import SHORT_BEST, SHORT_EXAMPLE, extended, medium, short


def codes(r):
    return [f["code"] for f in r["flags"]]


# ---------- Пример расчёта и ядро ----------

def test_worked_example_from_methodology():
    """«Пример расчёта» методики v2.0: 70 / 80 / 63 / 75 / 50 / 75 → 69, умеренный; фокус — питание."""
    r = calculate_score(SHORT_EXAMPLE)
    assert r["breakdown"] == {"sleep": 70, "activity": 80, "nutrition": 63, "mental": 75, "nicotine": 50,
                              "alcohol": 75}
    assert r["total"] == 69 and r["level"] == "moderate"
    assert r["version"] == METHOD_VERSION == "2.0" and r["tier"] == "short"
    assert r["flags"] == []
    # у бросившего курить без вейпа балл растёт только со временем — фокус уходит на питание
    assert r["focus"]["sphere"] == "nutrition" and r["focus"]["item"] == "n3"
    assert r["detailed"] is None and r["body"] is None


def test_maximum_core_is_100():
    r = calculate_score(SHORT_BEST)
    assert r["total"] == 100 and set(r["breakdown"]) == set(CORE_DOMAINS)
    assert r["focus"]["type"] == "maintain"


@pytest.mark.parametrize("hours,points", list(LE8_SLEEP.items()))
def test_sleep_le8_table(hours, points):
    assert calculate_score(short(sl1=hours))["breakdown"]["sleep"] == points


@pytest.mark.parametrize("days,minutes,points", [("0", None, 0), ("1", "20", 20), ("1", "45", 40), ("2", "30", 60),
                                                  ("3", "30", 80), ("4", "30", 90), ("5", "30", 100)])
def test_activity_le8_table(days, minutes, points):
    a = short(pa1=days, pa2=minutes)
    if minutes is None:
        del a["pa2"]
    assert calculate_score(a)["breakdown"]["activity"] == points


@pytest.mark.parametrize("changes,points", [
    ({"nic1": "never"}, 100), ({"nic1": "former", "nic2": "ge5"}, 75), ({"nic1": "former", "nic2": "1_5"}, 50),
    ({"nic1": "former", "nic2": "lt1"}, 25), ({"nic1": "current"}, 0), ({"nic3": "yes"}, 25),
    ({"nic4": "yes"}, 80), ({"nic1": "current", "nic4": "yes"}, 0),
])
def test_nicotine_le8_table(changes, points):
    assert calculate_score(short(**changes))["breakdown"]["nicotine"] == points


def test_alcohol_audit_c_and_positive_threshold_by_sex():
    r = calculate_score(short(a1="2", a2="1", a3="0"))  # AUDIT-C = 3
    assert r["breakdown"]["alcohol"] == 75 and r["screens"]["audit_c"] == 3
    # 3 — положительно у женщин, но не у мужчин: полный AUDIT спрашивается только при положительном
    with pytest.raises(ScoringError) as exc:
        calculate_score(extended(sex="female", a1="2", a2="1", a3="0"))
    assert "a4" in exc.value.errors
    assert calculate_score(extended(sex="male", a1="2", a2="1", a3="0"))["screens"]["audit"] is None


def test_nutrition_pomp():
    r = calculate_score(short(n1="3", n2="2", n3="3"))
    assert r["breakdown"]["nutrition"] == 63  # (60 + 71,4 + 57,1) / 3


def test_mental_phq4():
    assert calculate_score(short(p1="3", p2="3", p3="3", p4="3"))["breakdown"]["mental"] == 0


# ---------- Уровни и каскад ----------

def test_medium_refines_and_gives_detailed_index():
    r = calculate_score(medium())
    assert r["tier"] == "medium"
    assert set(r["refined"]) == {"activity", "nutrition", "mental", "wellbeing"}
    assert r["detailed"]["total"] is not None and len(r["detailed"]["domains"]) == 7
    assert r["detailed"]["sources"]["sleep"] == "short"  # SCI отключён до лицензии — сон по ядру
    assert r["total"] == calculate_score({**medium(), "tier": "short"})["total"]  # ядро не зависит от уровня


def test_medium_strength_and_intensity():
    r = calculate_score(medium(pa1="2", pa2="30", pa3="vigorous", pa4="0"))
    # 60 мин × 2 = 120 эквивалентных → 90; силовые 0 → (90 + 0) / 2
    assert r["refined"]["activity"] == 45
    assert r["breakdown"]["activity"] == 60  # ядро — без удвоения


def test_phq8_gad7_formula():
    r = calculate_score(medium(p1="3", p2="3", ph3="3", ph4="3", ph5="3", ph6="3", ph7="3", ph8="3"))
    assert r["screens"]["phq8"] == 24
    assert r["screens"]["gad7"] == 1                  # ga3 = 1 в MEDIUM_EXTRA
    assert r["refined"]["mental"] == 48               # ((100 − 24/24·100) + (100 − 1/21·100)) / 2 = 47,6


def test_extended_ipaq_and_body():
    r = calculate_score(extended())
    assert r["screens"]["met_minutes"] == round(8 * 60 + 4 * 60 + 3.3 * 150)
    assert r["body"]["known"] == 4 and r["body"]["parts"] == {"bmi": 100, "bp": 100, "lipids": 60, "glucose": 100}
    assert r["body"]["score"] == 90


def test_cascade_uses_fresh_history():
    history = {"wellbeing": {"score": 40, "tier": "medium", "age_days": 10},
               "mental": {"score": 30, "tier": "medium", "age_days": 20}}
    r = calculate_score(SHORT_BEST, history=history)
    assert r["detailed"]["domains"]["wellbeing"] == 40
    assert r["detailed"]["domains"]["mental"] == 100  # PHQ-8/GAD-7 старше 14 дней — берём ядро
    assert r["detailed"]["sources"]["mental"] == "short"


def test_no_detailed_without_wellbeing():
    assert calculate_score(SHORT_BEST)["detailed"] is None


def test_body_labs_older_than_year_ignored():
    r = calculate_score(extended(lab_age="gt12m"))
    assert set(r["body"]["parts"]) == {"bmi", "bp"}


def test_body_le8_tables():
    r = calculate_score(extended(weight=95, sbp=145, dbp=85, bp_tx="yes", chol=7.0, hdl=1.0, lip_tx="yes",
                                 dm="yes", hba1c=7.5))
    # ИМТ 32,9 → 30; давление 140–159 → 25 − 20 = 5; не-ЛПВП 6,0 → 0 (лечение не уводит ниже 0); диабет HbA1c 7,5 → 30
    assert r["body"]["parts"] == {"bmi": 30, "bp": 5, "lipids": 0, "glucose": 30}


def test_pregnancy_skips_weight():
    tier, a = validate(extended(restriction="pregnant"))
    assert "weight" not in a and "waist" not in a


# ---------- Красные флаги ----------

def test_flags_mental():
    assert codes(calculate_score(short(p1="2", p2="1"))) == ["mood"]
    assert codes(calculate_score(short(p1="3", p2="2", p3="2", p4="2"))) == ["distress"]
    assert codes(calculate_score(medium(ph3="3", ph4="3", ph5="3", ph6="1"))) == ["mood"]  # PHQ-8 = 10


def test_flag_insomnia():
    assert "insomnia" in codes(calculate_score(short(sl2="3plus")))


def test_flags_body():
    r = calculate_score(extended(sbp=185, dbp=100))
    assert "bp_crisis" in codes(r) and r["focus"]["type"] == "specialist"
    assert "bp_high" in codes(calculate_score(extended(sbp=136, dbp=80, bp_src="home")))
    assert "bp_high" not in codes(calculate_score(extended(sbp=136, dbp=80, bp_src="clinic")))
    assert "glucose" in codes(calculate_score(extended(glu=7.2)))
    assert "lipids" in codes(calculate_score(extended(ldl=5.2)))
    assert "underweight" in codes(calculate_score(extended(weight=50)))


def test_flag_audit_dependence():
    a = extended(sex="male", a1="4", a2="4", a3="4", a4="4", a5="2", a6="0", a7="0", a8="0", a9="0", a10="0")
    r = calculate_score(a)
    assert r["screens"]["audit"] == 18 and "alcohol" not in codes(r)
    r = calculate_score({**a, "a9": "4"})
    assert r["screens"]["audit_zone"] == 4 and "alcohol" in codes(r)


def test_flag_checkup_and_restriction_are_info():
    r = calculate_score(extended(checkup="1_3y", restriction="restriction"))
    assert {f["code"]: f["level"] for f in r["flags"]} == {"checkup": "info", "restriction": "info"}
    assert r["focus"]["type"] != "specialist"


# ---------- Валидация ----------

def test_under_18_rejected():
    with pytest.raises(ScoringError) as exc:
        calculate_score(short(age="under18"))
    assert exc.value.code == "age_restricted"


def test_validation_errors():
    with pytest.raises(ScoringError) as exc:
        calculate_score({"tier": "short"})
    assert {"age", "sl1", "pa1", "p1", "nic1", "a1"} <= set(exc.value.errors)
    with pytest.raises(ScoringError) as exc:
        calculate_score(extended(height=20, sbp="abc"))
    assert set(exc.value.errors) == {"height", "sbp"}
    with pytest.raises(ScoringError):
        calculate_score(short(tier="huge"))


def test_hidden_questions_are_dropped():
    tier, a = validate(short(pa4="2plus", w1="4", height=180))  # вопросы других уровней
    assert "pa4" not in a and "w1" not in a and "height" not in a


def test_describe_answers_numbers_and_choices():
    groups = dict(describe_answers(validate(extended())[1]))
    assert dict(groups["Тело и метаболизм"])["Рост"] == "170 см"
    assert dict(groups["Сон"])["Часы сна"] == "7–9"


def test_question_bank_is_nested():
    tiers = {q["tier"] for q in QUESTIONS.values()}
    assert tiers == {"short", "medium", "extended"}
    short_ids = {k for k, q in QUESTIONS.items() if q["tier"] == "short"}
    assert {"sl1", "pa1", "pa2", "n1", "n2", "n3", "p1", "p2", "p3", "p4", "nic1", "a1"} <= short_ids
    assert LE8_PA[0] == (150, 100)
