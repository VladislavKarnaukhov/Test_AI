"""Логика скоринга VitaScore. Чистые функции, без зависимости от Flask."""

SLEEP_POINTS = {"lt5": 30, "5_6": 60, "7_8": 100, "gt8": 80}
ACTIVITY_POINTS = {"0": 20, "1_2": 50, "3_4": 80, "5plus": 100}
NUTRITION_POINTS = {"0_1": 30, "2_3": 65, "4plus": 100}
# stress: 1 — спокойно, 5 — очень напряжённо; чем выше стресс, тем ниже восстановление
RECOVERY_POINTS = {1: 100, 2: 80, 3: 60, 4: 35, 5: 15}

WEIGHTS = {"sleep": 0.30, "activity": 0.25, "nutrition": 0.20, "recovery": 0.25}

SPHERE_NAMES = {
    "sleep": "Сон",
    "activity": "Движение",
    "nutrition": "Питание",
    "recovery": "Восстановление",
}

TIPS = {
    "sleep": "Ложитесь в одно и то же время и добавьте 20 минут без экрана перед сном.",
    "activity": "Начните с 20-минутной прогулки быстрым шагом три раза в неделю.",
    "nutrition": "Добавьте по одной порции овощей или фруктов к обеду и ужину.",
    "recovery": "Выделите 10 минут в день на паузу: дыхание, прогулку или тишину.",
}

SUMMARIES = [
    (80, "У вас устойчивый баланс — поддерживайте привычки, которые уже работают."),
    (60, "Хорошая база с заметным резервом для роста."),
    (40, "Ресурса пока не хватает — начните с одной сферы, и остальные подтянутся."),
    (0, "Организму нужна поддержка: сфокусируйтесь на восстановлении и базовых привычках."),
]


class ScoringError(ValueError):
    """Ошибка валидации ответов. errors — словарь {поле: описание}."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


def _parse_stress(value):
    if isinstance(value, bool):
        return None
    try:
        stress = int(value)
    except (TypeError, ValueError):
        return None
    if str(value).strip() != str(stress) and not isinstance(value, int):
        return None
    return stress if stress in RECOVERY_POINTS else None


def calculate_score(answers):
    """Считает VitaScore по ответам анкеты.

    Возвращает {"total", "breakdown", "weakest", "summary", "tip"}.
    Бросает ScoringError, если поля отсутствуют или имеют неверные значения.
    """
    if not isinstance(answers, dict):
        raise ScoringError({"answers": "ожидается объект с ответами"})

    errors = {}
    breakdown = {}

    for field, table in (("sleep", SLEEP_POINTS), ("activity", ACTIVITY_POINTS),
                         ("nutrition", NUTRITION_POINTS)):
        value = answers.get(field)
        if value is None or value == "":
            errors[field] = "обязательное поле"
        elif str(value) not in table:
            errors[field] = "допустимые значения: " + ", ".join(table)
        else:
            breakdown[field] = table[str(value)]

    stress = answers.get("stress")
    if stress is None or stress == "":
        errors["stress"] = "обязательное поле"
    else:
        parsed = _parse_stress(stress)
        if parsed is None:
            errors["stress"] = "целое число от 1 до 5"
        else:
            breakdown["recovery"] = RECOVERY_POINTS[parsed]

    if errors:
        raise ScoringError(errors)

    total = round(sum(breakdown[k] * w for k, w in WEIGHTS.items()))
    # при равенстве берём сферу с большим весом — её улучшение сильнее влияет на итог
    weakest = min(WEIGHTS, key=lambda k: (breakdown[k], -WEIGHTS[k]))
    summary = next(text for threshold, text in SUMMARIES if total >= threshold)

    return {
        "total": total,
        "breakdown": {k: breakdown[k] for k in WEIGHTS},
        "weakest": weakest,
        "summary": summary,
        "tip": TIPS[weakest],
    }
