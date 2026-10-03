"""Сохранённая оценка → данные для страниц. Понимает методику v2.0 (действующую), v1.0 и старую формулу (v0)."""
import json

from . import scoring, scoring_v0, scoring_v1

SELECT_COLUMNS = ("id, answers, total, breakdown, recommendations, method_version, flags, focus, tier, details, "
                  "created_at")
VERSION_LABELS = {"0": "старая методика", "1.0": "методика v1.0"}
CORE_SHORT = {k: scoring.DOMAIN_SHORT[k] for k in scoring.CORE_DOMAINS}


def _spheres(breakdown, names):
    return [(k, names[k], breakdown[k]) for k in names if k in breakdown]


def present(row):
    """row — строка score_results. Словарь одинаковой формы для всех версий методики.

    current=False — результат другой версии: в истории остаётся, но с текущими не сравнивается.
    """
    breakdown = json.loads(row["breakdown"])
    answers = json.loads(row["answers"])
    version = row["method_version"] or "0"
    recs = json.loads(row["recommendations"]) if row["recommendations"] else None

    if version == scoring.METHOD_VERSION:
        details = json.loads(row["details"] or "{}")
        level = scoring.level_for(row["total"])
        return {
            "version": version, "current": True, "version_label": f"методика v{version}",
            "tier": row["tier"], "tier_name": scoring.TIER_NAMES.get(row["tier"], ""),
            "total": row["total"], "level_code": level[1], "level_name": level[2],
            "summary": scoring.summary_for(row["total"]),
            "breakdown": breakdown, "spheres": _spheres(breakdown, CORE_SHORT),
            "detailed": details.get("detailed"), "body": details.get("body"), "screens": details.get("screens", {}),
            "refined": details.get("refined", {}),
            "flags": json.loads(row["flags"] or "[]"),
            "focus": json.loads(row["focus"]) if row["focus"] else None,
            "recommendations": recs or [],
            "answer_groups": scoring.describe_answers(answers),
        }

    if version == "1.0":
        level = scoring_v1.level_for(row["total"])
        return {
            "version": version, "current": False, "version_label": VERSION_LABELS[version], "tier": None,
            "tier_name": "", "total": row["total"], "level_code": None, "level_name": level[2],
            "summary": scoring_v1.summary_for(row["total"]), "breakdown": breakdown,
            "spheres": _spheres(breakdown, scoring_v1.SPHERE_SHORT), "detailed": None, "body": None, "screens": {},
            "refined": {},
            "flags": json.loads(row["flags"] or "[]"),
            "focus": json.loads(row["focus"]) if row["focus"] else None,
            "recommendations": recs or [],
            "answer_groups": scoring_v1.describe_answers(answers),
        }

    # старая формула: рекомендации хранились не всегда — пересчитываем её же правилами
    recs = recs or scoring_v0.build_recommendations(breakdown)
    return {
        "version": "0", "current": False, "version_label": VERSION_LABELS["0"], "tier": None, "tier_name": "",
        "total": row["total"], "level_code": None, "level_name": VERSION_LABELS["0"],
        "summary": scoring_v0.summary_for(row["total"]), "breakdown": breakdown,
        "spheres": _spheres(breakdown, scoring_v0.SPHERE_NAMES), "detailed": None, "body": None, "screens": {}, "refined": {},
        "flags": [],
        "focus": {"type": "step", "sphere": recs[0]["sphere"], "title": recs[0]["title"], "text": recs[0]["text"]}
        if recs else None,
        "recommendations": recs,
        "answer_groups": [("Ответы", scoring_v0.describe_answers(answers))],
    }
