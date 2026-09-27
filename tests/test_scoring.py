import pytest

from app.scoring import ScoringError, calculate_score

BEST = {"sleep": "7_8", "activity": "5plus", "nutrition": "4plus", "stress": 1}


def test_maximum_is_100():
    result = calculate_score(BEST)
    assert result["total"] == 100
    assert result["breakdown"] == {"sleep": 100, "activity": 100, "nutrition": 100, "recovery": 100}
    assert result["summary"] and result["tip"]


def test_minimum_is_low():
    result = calculate_score({"sleep": "lt5", "activity": "0", "nutrition": "0_1", "stress": 5})
    assert 0 <= result["total"] < 40


def test_weighted_total():
    # 60*0.30 + 80*0.25 + 65*0.20 + 60*0.25 = 18 + 20 + 13 + 15 = 66
    result = calculate_score({"sleep": "5_6", "activity": "3_4", "nutrition": "2_3", "stress": 3})
    assert result["total"] == 66


@pytest.mark.parametrize("answers,weakest", [
    ({**BEST, "sleep": "lt5"}, "sleep"),
    ({**BEST, "activity": "0"}, "activity"),
    ({**BEST, "nutrition": "0_1"}, "nutrition"),
    ({**BEST, "stress": 5}, "recovery"),
])
def test_weakest_sphere(answers, weakest):
    result = calculate_score(answers)
    assert result["weakest"] == weakest
    assert result["tip"]


def test_stress_accepts_string():
    assert calculate_score({**BEST, "stress": "1"})["total"] == 100


def test_missing_fields():
    with pytest.raises(ScoringError) as exc:
        calculate_score({})
    assert set(exc.value.errors) == {"sleep", "activity", "nutrition", "stress"}


@pytest.mark.parametrize("field,value", [
    ("sleep", "10h"), ("activity", 7), ("nutrition", "lots"),
    ("stress", 0), ("stress", 6), ("stress", "abc"), ("stress", 2.5), ("stress", True),
])
def test_invalid_values(field, value):
    with pytest.raises(ScoringError) as exc:
        calculate_score({**BEST, field: value})
    assert list(exc.value.errors) == [field]


def test_non_dict():
    with pytest.raises(ScoringError):
        calculate_score(["sleep"])


def test_recommendations_start_with_weakest():
    result = calculate_score({**BEST, "stress": 5})
    recs = result["recommendations"]
    assert recs[0]["sphere"] == "recovery" and recs[0]["level"] == "low"
    assert {r["sphere"] for r in recs} == {"sleep", "activity", "nutrition", "recovery"}
    assert all(r["title"] and r["text"] for r in recs)


def test_recommendation_levels():
    result = calculate_score({"sleep": "5_6", "activity": "5plus", "nutrition": "0_1", "stress": 1})
    levels = {r["sphere"]: r["level"] for r in result["recommendations"]}
    assert levels == {"sleep": "mid", "activity": "high", "nutrition": "low", "recovery": "high"}
