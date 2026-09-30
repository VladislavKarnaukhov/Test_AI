"""Скоринг по методике VitaScore v1.0. Чистые функции, без зависимости от Flask.

Здесь единственный источник правды: вопросы, варианты, баллы, формулы, красные флаги и
библиотека советов. Страница /methodology строит свои таблицы из этих же данных.

Ключи сфер sleep / activity / nutrition / recovery совпадают со старой формулой (scoring_v0),
чтобы история и графики работали со старыми результатами; recovery теперь —
«Психологическое состояние» (PHQ-4).
"""
import math

METHOD_VERSION = "1.0"

SPHERES = ("sleep", "activity", "nutrition", "recovery")
SPHERE_NAMES = {"sleep": "Сон", "activity": "Движение", "nutrition": "Питание",
                "recovery": "Психологическое состояние"}
SPHERE_SHORT = {"sleep": "Сон", "activity": "Движение", "nutrition": "Питание", "recovery": "Психол. состояние"}
WEIGHTS = {k: 0.25 for k in SPHERES}  # равные веса — см. «Итоговый балл» в методике

PHQ_OPTIONS = [("0", "Ни разу"), ("1", "Несколько дней"), ("2", "Больше половины дней"), ("3", "Почти каждый день")]

# Шаги анкеты: (ключ, заголовок, подзаголовок, [вопросы]).
# Вопрос: id, text, short (для истории), options [(value, label)], optional hint.
STEPS = [
    ("filter", "Для начала", "Два вопроса, чтобы советы подходили именно вам.", [
        {"id": "age", "text": "Сколько вам лет?", "short": "Возраст",
         "options": [("under18", "Младше 18"), ("18_64", "18–64"), ("65plus", "65 и старше")]},
        {"id": "restriction", "text": "Врач ограничил вам физическую нагрузку, или вы беременны?",
         "short": "Ограничение нагрузки", "options": [("no", "Нет"), ("yes", "Да")]},
    ]),
    ("sleep", "Сон", "За последние 2 недели.", [
        {"id": "s1", "text": "Сколько часов вы обычно спите за ночь?", "short": "Продолжительность",
         "options": [("lt5", "Меньше 5"), ("5_6", "5–6"), ("6_7", "6–7"), ("7_8", "7–8"), ("8_9", "8–9"),
                     ("gt9", "Больше 9")]},
        {"id": "s2", "text": "Насколько меняется время, когда вы засыпаете, в течение недели, включая выходные?",
         "short": "Регулярность",
         "options": [("lt30", "Меньше 30 минут"), ("30_60", "30–60 минут"), ("1_2h", "1–2 часа"),
                     ("gt2h", "Больше 2 часов")]},
        {"id": "s3", "text": "Сколько ночей в неделю вы засыпаете дольше 30 минут или просыпаетесь и долго не можете уснуть?",
         "short": "Трудности со сном", "options": [("0", "Ни одной"), ("1_2", "1–2"), ("3plus", "3 и больше")]},
        {"id": "s4", "text": "Как часто днём вам трудно не заснуть или вы чувствуете сонливость?",
         "short": "Сонливость днём", "options": [("never", "Никогда"), ("several", "Несколько дней"),
                                                 ("half", "Больше половины дней"), ("daily", "Почти каждый день")]},
        {"id": "s5", "text": "Насколько вы довольны своим сном?", "short": "Удовлетворённость сном",
         "options": [("0", "Совсем нет"), ("1", "Скорее нет"), ("2", "Не уверен(а)"), ("3", "Скорее да"),
                     ("4", "Полностью")]},
        {"id": "s6", "text": "Говорили ли вам, что вы громко храпите или перестаёте дышать во сне?",
         "short": "Храп, остановки дыхания", "options": [("no", "Нет"), ("yes", "Да"), ("unknown", "Не знаю")]},
    ]),
    ("activity", "Движение", "Обычная неделя.", [
        {"id": "m1", "text": "Сколько дней в неделю вы двигаетесь так, что учащается дыхание (быстрая ходьба, велосипед, бег, спорт)?",
         "short": "Дней с активностью", "options": [(str(d), str(d)) for d in range(8)]},
        {"id": "m2", "text": "Сколько минут в среднем длится такая активность в эти дни?", "short": "Минут за раз",
         "options": [("10", "10"), ("20", "20"), ("30", "30"), ("45", "45"), ("60", "60"), ("90", "90+")],
         "depends_on": "m1"},
        {"id": "m3", "text": "Как интенсивно чаще всего?", "short": "Интенсивность",
         "options": [("moderate", "Умеренно — можете говорить, но не петь"), ("vigorous", "Интенсивно — трудно говорить")],
         "depends_on": "m1"},
        {"id": "m4", "text": "Сколько дней в неделю вы делаете силовые упражнения (тренажёры, отжимания, приседания, резинки)?",
         "short": "Силовые", "options": [("0", "0"), ("1", "1"), ("2plus", "2 и больше")]},
        {"id": "m5", "text": "Сколько часов в день вы обычно сидите (работа, транспорт, экран)?", "short": "Сидячее время",
         "options": [("lt6", "Меньше 6"), ("6_8", "6–8"), ("8_10", "8–10"), ("gt10", "Больше 10")]},
    ]),
    ("nutrition", "Питание", "Обычная неделя.", [
        {"id": "n1", "text": "Сколько порций овощей и фруктов вы съедаете в день?", "short": "Овощи и фрукты",
         "hint": "Порция ≈ 80 г: яблоко, горсть салата.",
         "options": [("0_1", "0–1"), ("2", "2"), ("3_4", "3–4"), ("5plus", "5 и больше")]},
        {"id": "n2", "text": "Как часто вы пьёте сладкие напитки (газировка, сок, чай или кофе с сахаром)?",
         "short": "Сладкие напитки",
         "options": [("rare", "Редко или никогда"), ("1_3", "1–3 раза в неделю"), ("4_6", "4–6 раз в неделю"),
                     ("daily", "Ежедневно")]},
        {"id": "n3", "text": "Как часто едите сладости, выпечку, десерты?", "short": "Сладости",
         "options": [("le2", "2 раза в неделю или реже"), ("3_6", "3–6 раз в неделю"), ("daily", "Раз в день"),
                     ("multi", "Несколько раз в день")]},
        {"id": "n4", "text": "Как часто едите колбасу, сосиски, фастфуд, чипсы?", "short": "Колбаса, фастфуд",
         "options": [("le1", "Раз в неделю или реже"), ("2_3", "2–3 раза в неделю"), ("4plus", "4 раза и чаще")]},
        {"id": "n5", "text": "Сколько дней в неделю в вашем рационе есть цельные злаки, бобовые или орехи?",
         "short": "Цельные злаки, бобовые, орехи", "options": [("5_7", "5–7"), ("3_4", "3–4"), ("0_2", "0–2")]},
    ]),
    ("recovery", "Психологическое состояние",
     "Как часто за последние 2 недели вас беспокоило следующее? Опросник PHQ-4.", [
         {"id": "p1", "text": "Мало интереса или удовольствия от занятий", "short": "Мало интереса", "options": PHQ_OPTIONS},
         {"id": "p2", "text": "Подавленность, уныние, безнадёжность", "short": "Подавленность", "options": PHQ_OPTIONS},
         {"id": "p3", "text": "Нервозность, тревога, напряжение", "short": "Тревога", "options": PHQ_OPTIONS},
         {"id": "p4", "text": "Неспособность остановить или контролировать беспокойство",
          "short": "Неконтролируемое беспокойство", "options": PHQ_OPTIONS},
     ]),
]
QUESTIONS = {q["id"]: q for _, _, _, qs in STEPS for q in qs}

# Баллы вариантов (0–100). s1 зависит от возраста: для 65+ норма 7–8 часов.
POINTS = {
    "s1": {"lt5": 0, "5_6": 40, "6_7": 70, "7_8": 100, "8_9": 100, "gt9": 70},
    "s1_65plus": {"lt5": 0, "5_6": 40, "6_7": 70, "7_8": 100, "8_9": 70, "gt9": 70},
    "s2": {"lt30": 100, "30_60": 70, "1_2h": 40, "gt2h": 10},
    "s3": {"0": 100, "1_2": 60, "3plus": 10},
    "s4": {"never": 100, "several": 60, "half": 25, "daily": 0},
    "s5": {"0": 0, "1": 25, "2": 50, "3": 75, "4": 100},
    "m4": {"0": 0, "1": 50, "2plus": 100},
    "m5": {"lt6": 100, "6_8": 70, "8_10": 40, "gt10": 10},
    "n1": {"0_1": 0, "2": 40, "3_4": 70, "5plus": 100},
    "n2": {"rare": 100, "1_3": 70, "4_6": 40, "daily": 0},
    "n3": {"le2": 100, "3_6": 60, "daily": 30, "multi": 0},
    "n4": {"le1": 100, "2_3": 60, "4plus": 20},
    "n5": {"5_7": 100, "3_4": 60, "0_2": 20},
}
INTENSITY = {"moderate": 1, "vigorous": 2}  # 1 минута интенсивной = 2 умеренным (ВОЗ)
AEROBIC_TARGET = 150                        # эквивалентных умеренных минут в неделю

# Веса пунктов внутри сферы — для выбора «фокуса недели»
ITEM_WEIGHTS = {
    "sleep": {"s1": .2, "s2": .2, "s3": .2, "s4": .2, "s5": .2},
    "activity": {"aerobic": .6, "strength": .2, "sedentary": .2},
    "nutrition": {"n1": .2, "n2": .2, "n3": .2, "n4": .2, "n5": .2},
    "recovery": {"p1": .25, "p2": .25, "p3": .25, "p4": .25},
}
ITEM_NAMES = {"aerobic": "Аэробная активность", "strength": "Силовые", "sedentary": "Сидячее время"}

LEVELS = [  # (от, код, название, что видит человек)
    (80, "high", "Устойчивый баланс", "Привычки близки к рекомендациям — фокус на том, чтобы их поддержать."),
    (60, "good", "Хорошая база", "Есть 1–2 сферы с заметным запасом роста."),
    (40, "risk", "Есть зоны риска", "Несколько сфер далеко от рекомендаций."),
    (0, "low", "Низкий ресурс", "Начните с одного шага; если есть красные флаги — сначала к специалисту."),
]
SPHERE_LEVEL_NAMES = {"low": "в приоритете", "mid": "есть резерв", "high": "поддерживайте"}

# Экстренная помощь. Телефоны доверия добавляются после утверждения врачом-консультантом (см. методику).
CRISIS_CONTACTS = [("112", "единый номер экстренных служб")]


class ScoringError(ValueError):
    """Ошибка валидации ответов. errors — {поле: описание}; code — тип ошибки."""

    def __init__(self, errors, code="validation_error"):
        self.errors = errors
        self.code = code
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


def _round(x):
    """Округление «как в школе»: 59,5 → 60 (встроенный round округлил бы к чётному)."""
    return int(math.floor(x + 0.5))


def level_for(total):
    return next(level for level in LEVELS if total >= level[0])


def summary_for(total):
    _, _, name, text = level_for(total)
    return f"{name}. {text}"


def sphere_level(points):
    return "low" if points < 50 else "mid" if points < 80 else "high"


# ---------- Валидация ----------

def _needs(qid, answers):
    """m2 и m3 не нужны, если активности нет вовсе."""
    q = QUESTIONS[qid]
    return not (q.get("depends_on") and answers.get(q["depends_on"]) == "0")


def validate(answers):
    if not isinstance(answers, dict):
        raise ScoringError({"answers": "ожидается объект с ответами"})
    errors = {}
    clean = {}
    for qid, q in QUESTIONS.items():
        if not _needs(qid, answers):
            continue
        value = answers.get(qid)
        value = None if value is None else str(value)
        if not value:
            errors[qid] = "обязательный вопрос"
        elif value not in {v for v, _ in q["options"]}:
            errors[qid] = "недопустимый ответ"
        else:
            clean[qid] = value
    if errors:
        raise ScoringError(errors)
    if clean["age"] == "under18":
        raise ScoringError({"age": "Анкета VitaScore рассчитана на взрослых — от 18 лет."}, code="age_restricted")
    return clean


# ---------- Расчёт ----------

def _item_scores(a):
    s1_table = POINTS["s1_65plus"] if a["age"] == "65plus" else POINTS["s1"]
    minutes = 0 if a["m1"] == "0" else int(a["m1"]) * int(a["m2"]) * INTENSITY[a["m3"]]
    return {
        "sleep": {"s1": s1_table[a["s1"]], **{q: POINTS[q][a[q]] for q in ("s2", "s3", "s4", "s5")}},
        "activity": {"aerobic": min(100.0, minutes / AEROBIC_TARGET * 100),
                     "strength": POINTS["m4"][a["m4"]], "sedentary": POINTS["m5"][a["m5"]]},
        "nutrition": {q: POINTS[q][a[q]] for q in ("n1", "n2", "n3", "n4", "n5")},
        "recovery": {q: 100 - int(a[q]) / 3 * 100 for q in ("p1", "p2", "p3", "p4")},
    }, minutes


def _flags(a):
    p = {q: int(a[q]) for q in ("p1", "p2", "p3", "p4")}
    phq2, gad2 = p["p1"] + p["p2"], p["p3"] + p["p4"]
    phq4 = phq2 + gad2
    flags = []
    if phq4 >= 9:
        flags.append({"code": "distress", "level": "urgent",
                      "title": "Не откладывайте разговор со специалистом",
                      "text": "Ваши ответы говорят о выраженном эмоциональном напряжении. Это не диагноз — короткий "
                              "опросник лишь помогает заметить, что нужна поддержка. Обратитесь к терапевту, "
                              "психиатру или психотерапевту в ближайшие дни.",
                      "contacts": True})
    elif phq2 >= 3 or gad2 >= 3:
        signs = " и ".join(s for s, on in (("подавленного настроения", phq2 >= 3), ("тревоги", gad2 >= 3)) if on)
        flags.append({"code": "mood", "level": "warn",
                      "title": "Стоит обсудить своё состояние со специалистом",
                      "text": f"В ответах есть признаки {signs}. Это не диагноз, а повод обратиться к терапевту, "
                              "психиатру или психотерапевту."})
    if a["s3"] == "3plus" and a["s5"] in ("0", "1"):
        flags.append({"code": "insomnia", "level": "warn",
                      "title": "Проблемы со сном стоит обсудить с врачом",
                      "text": "Если трудности с засыпанием или ночные пробуждения длятся 3 месяца и дольше, "
                              "обратитесь к сомнологу. Метод первой линии — когнитивно-поведенческая терапия "
                              "инсомнии, а не снотворное."})
    if a["s6"] == "yes":
        extra = " — особенно вместе с дневной сонливостью" if a["s4"] in ("half", "daily") else ""
        flags.append({"code": "apnea", "level": "warn",
                      "title": "Храп и остановки дыхания стоит показать врачу",
                      "text": f"Это может быть признаком апноэ сна{extra}. Обратитесь к терапевту или сомнологу."})
    if a["restriction"] == "yes":
        flags.append({"code": "restriction", "level": "info",
                      "title": "Советы по движению — только после разговора с врачом",
                      "text": "Врач ограничил вам нагрузку или вы беременны: общие рекомендации могут не подойти. "
                              "Балл считается как обычно."})
    return flags, {"phq2": phq2, "gad2": gad2, "phq4": phq4}


def _plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else many


def step_for(item, a, minutes):
    """Следующая ступень шкалы для пункта: (заголовок, текст)."""
    if item in ("aerobic", "strength", "sedentary") and a["restriction"] == "yes":
        return ("Обсудите нагрузку с врачом",
                "Врач ограничил вам нагрузку или вы беременны — спросите, какая активность вам безопасна.")
    if item == "s1":
        long_sleep = a["s1"] in ("gt9",) or (a["age"] == "65plus" and a["s1"] == "8_9")
        if long_sleep:
            return ("Вставайте в одно и то же время",
                    "Сон дольше нормы — повод держать постоянное время подъёма; если усталость не проходит, "
                    "обсудите это с врачом.")
        norm = "7–8" if a["age"] == "65plus" else "7–9"
        return ("Ложитесь на 30 минут раньше в будни",
                f"Сдвиньте отход ко сну на 30 минут — это приблизит вас к норме {norm} часов.")
    if item == "aerobic":
        walks = max(1, math.ceil((AEROBIC_TARGET - minutes) / 30))
        word = _plural(walks, "прогулку", "прогулки", "прогулок")
        return (f"+{walks} {word} по 30 минут",
                f"Добавьте {walks} {word} быстрым шагом по 30 минут в неделю — это доведёт вас до 150 минут "
                "умеренной активности.")
    if item == "strength":
        if a["m4"] == "0":
            return ("Одна силовая тренировка в неделю",
                    "20 минут с собственным весом: приседания, отжимания от стены, планка, упражнения с резинкой.")
        return ("Второй день силовых", "ВОЗ рекомендует силовые упражнения 2 и больше дней в неделю.")
    return STEPS_LIBRARY[item]


STEPS_LIBRARY = {
    "s2": ("Одно время отхода ко сну", "Ложитесь в пределах 30 минут от одного времени каждый день, включая выходные."),
    "s3": ("Правило 20 минут", "Не уснули за 20 минут — встаньте, займитесь спокойным делом при тусклом свете "
                               "и вернитесь в кровать, когда захочется спать."),
    "s4": ("Утренний свет", "Выходите на дневной свет в первый час после подъёма, дневной сон — не дольше 20 минут."),
    "s5": ("Ритуал перед сном", "За час до сна — без экранов и рабочих сообщений: тёплый душ, книга, приглушённый свет."),
    "sedentary": ("Вставайте каждый час", "Поставьте напоминание: 3 минуты ходьбы или разминки на каждый час сидения."),
    "n1": ("Ещё одна порция овощей", "Добавьте порцию овощей или фруктов (≈ 80 г) к одному приёму пищи — цель ВОЗ: "
                                     "5 порций в день."),
    "n2": ("Замените сладкий напиток", "Хотя бы в половине случаев выбирайте воду, чай или кофе без сахара."),
    "n3": ("Сладкое — на раз реже", "Сократите сладости и выпечку на один раз в неделю по сравнению с нынешней привычкой."),
    "n4": ("Меньше колбасы и фастфуда", "Замените один приём колбасы, сосисок или фастфуда на рыбу, курицу, яйца "
                                        "или бобовые."),
    "n5": ("Цельные злаки и бобовые", "Добавьте 1–2 дня с гречкой, овсянкой, цельнозерновым хлебом, фасолью или "
                                      "горстью орехов."),
    "p1": ("Одно приятное дело в день", "Запланируйте 15 минут на то, что раньше радовало: прогулка, музыка, встреча."),
    "p2": ("Поговорите с близким", "Расскажите человеку, которому доверяете, как вы себя чувствуете."),
    "p3": ("Дыхание 4–6", "Несколько раз в день по 2 минуты: вдох на 4 счёта, выдох на 6."),
    "p4": ("Время для беспокойства", "Выделите 15 минут в день, чтобы записать тревожные мысли, а в остальное время "
                                     "откладывайте их «на потом»."),
}
MAINTAIN = {
    "sleep": ("Сохраняйте режим", "Ваш сон близок к рекомендациям — держите постоянное время отхода ко сну."),
    "activity": ("Поддерживайте активность", "Вы выполняете рекомендации ВОЗ — не забывайте о днях восстановления."),
    "nutrition": ("Держите баланс", "Ваш рацион близок к рекомендациям ВОЗ — продолжайте."),
    "recovery": ("Берегите ресурс", "Заметьте, что помогает вам чувствовать себя хорошо, и оставьте это в расписании."),
}


def _gaps(items):
    """[(отставание, сфера, пункт)] — (100 − балл пункта) × вес пункта в сфере."""
    return [((100 - score) * ITEM_WEIGHTS[sphere][item], sphere, item)
            for sphere, scores in items.items() for item, score in scores.items()]


def build_recommendations(items, breakdown, a, minutes):
    """Все шаги по сферам — от самой слабой сферы, внутри — от самого большого отставания."""
    order = sorted(SPHERES, key=lambda k: (breakdown[k], SPHERES.index(k)))
    gaps = _gaps(items)
    recs = []
    for sphere in order:
        level = sphere_level(breakdown[sphere])
        base = {"sphere": sphere, "sphere_name": SPHERE_NAMES[sphere], "level": level,
                "level_name": SPHERE_LEVEL_NAMES[level]}
        sphere_gaps = sorted((g for g in gaps if g[1] == sphere and g[0] > 0), key=lambda g: -g[0])
        if not sphere_gaps:
            title, text = MAINTAIN[sphere]
            recs.append({**base, "item": None, "title": title, "text": text})
            continue
        seen = set()
        for _, _, item in sphere_gaps:
            title, text = step_for(item, a, minutes)
            if title in seen:  # «обсудите с врачом» — один раз на сферу
                continue
            seen.add(title)
            recs.append({**base, "item": item, "title": title, "text": text})
    return recs


def _focus(flags, items, breakdown, a, minutes):
    """Фокус недели: красный флаг → специалист; иначе самый отстающий пункт самой слабой сферы."""
    serious = [f for f in flags if f["level"] in ("urgent", "warn")]
    if serious:
        return {"type": "specialist", "sphere": None, "item": None,
                "title": "Фокус недели — консультация специалиста", "text": serious[0]["title"] + "."}
    weakest = min(SPHERES, key=lambda k: (breakdown[k], SPHERES.index(k)))
    candidates = [g for g in _gaps(items) if g[1] == weakest]
    gap, _, item = max(candidates, key=lambda g: g[0])
    if gap <= 0:
        title, text = MAINTAIN[weakest]
        return {"type": "maintain", "sphere": weakest, "item": None, "title": title, "text": text}
    title, text = step_for(item, a, minutes)
    return {"type": "step", "sphere": weakest, "item": item, "title": title, "text": text}


def calculate_score(answers):
    """Считает VitaScore v1.0. Бросает ScoringError при неполных/неверных ответах и для младше 18."""
    a = validate(answers)
    items, minutes = _item_scores(a)
    breakdown = {
        "sleep": _round(sum(items["sleep"].values()) / 5),
        "activity": _round(.6 * items["activity"]["aerobic"] + .2 * items["activity"]["strength"]
                           + .2 * items["activity"]["sedentary"]),
        "nutrition": _round(sum(items["nutrition"].values()) / 5),
        "recovery": _round(sum(items["recovery"].values()) / 4),
    }
    total = _round(sum(breakdown.values()) / 4)
    _, level, level_name, _ = level_for(total)
    flags, screens = _flags(a)
    focus = _focus(flags, items, breakdown, a, minutes)
    weakest = min(SPHERES, key=lambda k: (breakdown[k], SPHERES.index(k)))
    return {
        "version": METHOD_VERSION,
        "answers": a,
        "total": total,
        "level": level,
        "level_name": level_name,
        "summary": summary_for(total),
        "breakdown": breakdown,
        "weakest": weakest,
        "flags": flags,
        "screens": screens,
        "focus": focus,
        "tip": focus["text"],
        "active_minutes": minutes,
        "recommendations": build_recommendations(items, breakdown, a, minutes),
    }


def describe_answers(answers):
    """[(название группы, [(вопрос кратко, ответ словами)])] в порядке анкеты."""
    groups = []
    for key, title, _, questions in STEPS:
        rows = [(q["short"], dict(q["options"]).get(str(answers[q["id"]]), str(answers[q["id"]])))
                for q in questions if q["id"] in answers]
        if rows:
            groups.append((title, rows))
    return groups
