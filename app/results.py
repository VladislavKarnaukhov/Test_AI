"""Сохранённая оценка → данные для страниц. Понимает методику v1.0 и старую формулу (v0)."""
import json

from . import scoring, scoring_v0

LEGACY_LABEL = "старая методика"


def present(row):
    """row — строка score_results. Возвращает словарь, одинаковый для обеих версий методики."""
    breakdown = json.loads(row["breakdown"])
    answers = json.loads(row["answers"])
    version = row["method_version"]
    if version:
        level = scoring.level_for(row["total"])
        recs = json.loads(row["recommendations"] or "[]")
        return {
            "version": version,
            "legacy": False,
            "total": row["total"],
            "level_code": level[1],
            "level_name": level[2],
            "summary": scoring.summary_for(row["total"]),
            "breakdown": breakdown,
            "flags": json.loads(row["flags"] or "[]"),
            "focus": json.loads(row["focus"]) if row["focus"] else None,
            "recommendations": recs,
            "answer_groups": scoring.describe_answers(answers),
        }
    # старая формула: рекомендации хранились не всегда — пересчитываем её же правилами
    recs = json.loads(row["recommendations"]) if row["recommendations"] else scoring_v0.build_recommendations(breakdown)
    return {
        "version": "0",
        "legacy": True,
        "total": row["total"],
        "level_code": None,
        "level_name": LEGACY_LABEL,
        "summary": scoring_v0.summary_for(row["total"]),
        "breakdown": breakdown,
        "flags": [],
        "focus": {"type": "step", "sphere": recs[0]["sphere"], "title": recs[0]["title"], "text": recs[0]["text"]}
        if recs else None,
        "recommendations": recs,
        "answer_groups": [("Ответы", scoring_v0.describe_answers(answers))],
    }


SELECT_COLUMNS = ("id, answers, total, breakdown, recommendations, method_version, flags, focus, created_at")
