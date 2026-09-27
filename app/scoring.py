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

# Подписи ответов для истории в кабинете
ANSWER_LABELS = {
    "sleep": ("Сон", {"lt5": "меньше 5 часов", "5_6": "5–6 часов", "7_8": "7–8 часов", "gt8": "больше 8 часов"}),
    "activity": ("Активность", {"0": "ни одного дня", "1_2": "1–2 дня в неделю", "3_4": "3–4 дня в неделю",
                                "5plus": "5 и больше дней в неделю"}),
    "nutrition": ("Овощи и фрукты", {"0_1": "0–1 порция в день", "2_3": "2–3 порции в день",
                                     "4plus": "4 и больше порций в день"}),
    "stress": ("Напряжение", {"1": "1 из 5 — спокойно", "2": "2 из 5", "3": "3 из 5 — умеренно", "4": "4 из 5",
                              "5": "5 из 5 — очень напряжённо"}),
}


def describe_answers(answers):
    """[(вопрос, ответ словами)] в порядке анкеты."""
    return [(label, options.get(str(answers.get(key)), str(answers.get(key))))
            for key, (label, options) in ANSWER_LABELS.items() if key in answers]


# Каталог рекомендаций: сфера → уровень → [(заголовок, текст)].
# Уровень по баллу сферы: low < 50 ≤ mid < 80 ≤ high.
RECOMMENDATIONS = {
    "sleep": {
        "low": [
            ("Зафиксируйте время подъёма", "Вставайте в одно и то же время, даже в выходные, — так режим выстраивается быстрее всего."),
            ("Час без экранов", "За час до сна отложите телефон и ноутбук и приглушите свет."),
            ("Кофеин — до обеда", "Последняя чашка кофе или крепкого чая — не позже 14:00."),
        ],
        "mid": [
            ("На 15 минут раньше", "Сдвиньте отход ко сну на 15 минут раньше и удержите новый режим неделю."),
            ("Прохладная и тёмная спальня", "Проветрите комнату перед сном и уберите источники света."),
        ],
        "high": [
            ("Сохраняйте режим", "Сон — ваша опора. Старайтесь не сбивать режим в выходные."),
        ],
    },
    "activity": {
        "low": [
            ("Прогулка 20 минут", "Начните с быстрой ходьбы по 20 минут три раза в неделю."),
            ("Движение в течение дня", "Лестница вместо лифта, пешком до остановки — короткие активности тоже считаются."),
        ],
        "mid": [
            ("Добавьте силовые", "К кардио добавьте 1–2 силовые тренировки в неделю."),
            ("Тренировки в календаре", "Запланируйте тренировки заранее, как встречи, — так их реже пропускают."),
        ],
        "high": [
            ("Не забывайте о восстановлении", "При высокой активности важны дни отдыха и растяжка."),
        ],
    },
    "nutrition": {
        "low": [
            ("Овощи к обеду и ужину", "Добавьте по одной порции овощей к обеду и ужину."),
            ("Фрукт вместо сладкого", "Замените один сладкий перекус в день на фрукт или ягоды."),
        ],
        "mid": [
            ("Полтарелки — овощи", "Хотя бы в одном приёме пищи сделайте овощи половиной тарелки."),
            ("Разные цвета", "В течение недели выбирайте овощи и фрукты разных цветов."),
        ],
        "high": [
            ("Держите баланс", "Вы едите достаточно овощей и фруктов — продолжайте в том же духе."),
        ],
    },
    "recovery": {
        "low": [
            ("10 минут тишины", "Выделите 10 минут в день на паузу без телефона: дыхание, прогулка, тишина."),
            ("Разговор с близким", "Поделитесь тем, что беспокоит, с человеком, которому доверяете."),
            ("Попросите о помощи", "Если напряжение не отпускает неделями, стоит обратиться к специалисту."),
        ],
        "mid": [
            ("Дыхание 4–6", "Несколько раз в день делайте медленный вдох на 4 счёта и выдох на 6."),
            ("Границы рабочего дня", "Определите время, после которого не проверяете рабочие сообщения."),
        ],
        "high": [
            ("Берегите ресурс", "Заметьте, что помогает вам восстанавливаться, и оставьте это в расписании."),
        ],
    },
}

LEVEL_NAMES = {"low": "в приоритете", "mid": "есть резерв", "high": "поддерживайте"}

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


def summary_for(total):
    return next(text for threshold, text in SUMMARIES if total >= threshold)


def sphere_level(points):
    return "low" if points < 50 else "mid" if points < 80 else "high"


def build_recommendations(breakdown):
    """Все рекомендации по сферам, начиная с самой слабой."""
    order = sorted(WEIGHTS, key=lambda k: (breakdown[k], -WEIGHTS[k]))
    result = []
    for sphere in order:
        level = sphere_level(breakdown[sphere])
        for title, text in RECOMMENDATIONS[sphere][level]:
            result.append({
                "sphere": sphere,
                "sphere_name": SPHERE_NAMES[sphere],
                "level": level,
                "level_name": LEVEL_NAMES[level],
                "title": title,
                "text": text,
            })
    return result


def calculate_score(answers):
    """Считает VitaScore по ответам анкеты.

    Возвращает {"total", "breakdown", "weakest", "summary", "tip", "recommendations"}.
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
    summary = summary_for(total)

    return {
        "total": total,
        "breakdown": {k: breakdown[k] for k in WEIGHTS},
        "weakest": weakest,
        "summary": summary,
        "tip": TIPS[weakest],
        "recommendations": build_recommendations(breakdown),
    }
