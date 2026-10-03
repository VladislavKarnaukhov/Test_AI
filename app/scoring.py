"""Скоринг по методике VitaScore v2.0 (docs/methodology-v2.0.md). Чистые функции, без Flask.

Три вложенных уровня анкеты: короткий (ядро), средний, расширенный. Вопросы короткого уровня входят
во все уровни без изменений, поэтому VitaScore-ядро считается всегда и сравнимо во времени.

Здесь единственный источник правды: вопросы, условия показа, таблицы баллов, красные флаги, шаги
фокуса недели. Страница /methodology строит таблицы из этих же данных. Любая правка вопросов, баллов,
весов или порогов — только вместе с METHOD_VERSION и docs/.
"""
import math

METHOD_VERSION = "2.0"

TIERS = ("short", "medium", "extended")
TIER_NAMES = {"short": "Короткий", "medium": "Средний", "extended": "Расширенный"}
TIER_RANK = {t: i for i, t in enumerate(TIERS)}
TIER_INFO = {"short": "около 20 вопросов, 3–4 минуты", "medium": "около 40 вопросов, 10 минут",
             "extended": "около 70 вопросов и данные обследования, 20 минут"}

# Опросники, требующие лицензии для платного сервиса (раздел «Лицензии» методики).
# Пока разрешения нет — выключены, сфера считается по более короткому уровню.
LICENSED_INSTRUMENTS = {
    "SCI": {"name": "Sleep Condition Indicator", "enabled": False, "need": "разрешение авторов (CC BY-NC)"},
    "STOP-Bang": {"name": "STOP-Bang", "enabled": False, "need": "лицензия University Health Network"},
    "MEPA": {"name": "MEPA", "enabled": False, "need": "условия авторов и русская адаптация"},
}

CORE_DOMAINS = ("sleep", "activity", "nutrition", "mental", "nicotine", "alcohol")
DETAILED_DOMAINS = CORE_DOMAINS + ("wellbeing",)
DOMAIN_NAMES = {"sleep": "Сон", "activity": "Движение", "nutrition": "Питание",
                "mental": "Психологическое состояние", "nicotine": "Никотин", "alcohol": "Алкоголь",
                "wellbeing": "Самочувствие и связи", "body": "Тело и метаболизм"}
DOMAIN_SHORT = {**DOMAIN_NAMES, "mental": "Психол. состояние", "wellbeing": "Самочувствие"}

# Категории LE8 (Lloyd-Jones 2022) — для всех индексов VitaScore
LEVELS = [(80, "high", "Высокий уровень", "Привычки близки к рекомендациям — фокус на том, чтобы их поддержать."),
          (50, "moderate", "Умеренный уровень", "Есть сферы с заметным запасом роста."),
          (0, "low", "Низкий уровень", "Начните с одного шага; если есть красные флаги — сначала к специалисту.")]
SPHERE_LEVEL_NAMES = {"low": "в приоритете", "mid": "есть резерв", "high": "поддерживайте"}

# Срок годности измерения для каскада точности, дней (= период, о котором спрашивает опросник)
VALIDITY_DAYS = {"sleep": 30, "activity": 30, "nutrition": 30, "mental": 14, "nicotine": 30,
                 "alcohol": 365, "wellbeing": 30, "body": 365}

CRISIS_CONTACTS = [("112", "единый номер экстренных служб")]  # телефоны доверия — после утверждения врачом

PHQ_OPTIONS = [("0", "Ни разу"), ("1", "Несколько дней"), ("2", "Больше половины дней"), ("3", "Почти каждый день")]
DAYS = [(str(d), str(d)) for d in range(8)]
MINUTES = [("10", "10"), ("20", "20"), ("30", "30"), ("45", "45"), ("60", "60"), ("90", "90+")]
IPAQ_MINUTES = [("0", "0"), ("10", "10"), ("20", "20"), ("30", "30"), ("45", "45"), ("60", "60"), ("90", "90"),
                ("120", "120+")]
OFTEN3 = [("1", "Почти никогда"), ("2", "Иногда"), ("3", "Часто")]
AUDIT_FREQ5 = [("0", "Никогда"), ("1", "Реже раза в месяц"), ("2", "Раз в месяц"), ("3", "Раз в неделю"),
               ("4", "Ежедневно или почти ежедневно")]
AUDIT_YESNO = [("0", "Нет"), ("2", "Да, но не в последний год"), ("4", "Да, в последний год")]


def q(qid, tier, text, short, options=None, *, kind="choice", cond=None, optional=False, hint=None, unit=None,
      lo=None, hi=None, step=None):
    return {"id": qid, "tier": tier, "text": text, "short": short, "options": options or [], "kind": kind,
            "cond": cond, "optional": optional, "hint": hint, "unit": unit, "min": lo, "max": hi, "step": step}


# Шаги анкеты: (ключ, заголовок, подзаголовок, [вопросы]). Шаг виден, если в нём есть хотя бы один вопрос уровня.
STEPS = [
    ("filter", "Для начала", "Несколько вопросов, чтобы баллы и советы подходили именно вам.", [
        q("age", "short", "Сколько вам лет?", "Возраст",
          [("under18", "Младше 18"), ("18_39", "18–39"), ("40_49", "40–49"), ("50_64", "50–64"), ("65plus", "65+")]),
        q("sex", "short", "Ваш пол", "Пол", [("female", "Женский"), ("male", "Мужской")],
          hint="Нужен для порогов опросника об алкоголе и окружности талии."),
        q("restriction", "short", "Врач ограничил вам физическую нагрузку, или вы беременны?", "Ограничения",
          [("no", "Нет"), ("restriction", "Врач ограничил нагрузку"), ("pregnant", "Беременность")]),
    ]),
    ("sleep", "Сон", "За последний месяц.", [
        q("sl1", "short", "Сколько часов вы обычно спите за ночь?", "Часы сна",
          [("lt4", "Меньше 4"), ("4_5", "4–5"), ("5_6", "5–6"), ("6_7", "6–7"), ("7_9", "7–9"), ("9_10", "9–10"),
           ("ge10", "10 и больше")]),
        q("sl2", "short", "Сколько ночей в неделю вы долго засыпаете или просыпаетесь и не можете снова уснуть?",
          "Ночи с нарушением сна", [("0", "Ни одной"), ("1_2", "1–2"), ("3plus", "3 и больше")]),
    ]),
    ("activity", "Движение", "Обычная неделя.", [
        q("pa1", "short", "Сколько дней в неделю вы занимаетесь умеренной или интенсивной активностью "
          "(например, быстрая ходьба)?", "Дней с активностью", DAYS),
        q("pa2", "short", "В эти дни сколько минут в среднем?", "Минут за раз", MINUTES,
          cond={"q": "pa1", "not_in": ["0"]}),
        q("pa3", "medium", "Как интенсивно чаще всего?", "Интенсивность",
          [("moderate", "Умеренно — можете говорить, но не петь"), ("vigorous", "Интенсивно — трудно говорить")],
          cond={"q": "pa1", "not_in": ["0"]}),
        q("pa4", "medium", "Сколько дней в неделю вы делаете силовые упражнения на основные группы мышц?",
          "Силовые", [("0", "0"), ("1", "1"), ("2plus", "2 и больше")]),
        q("pa5", "medium", "Сколько часов в день вы обычно проводите сидя в будний день?", "Сидячее время",
          [("lt4", "Меньше 4"), ("4_6", "4–6"), ("6_8", "6–8"), ("8_10", "8–10"), ("gt10", "Больше 10")]),
        q("ip_vd", "extended", "IPAQ. За последние 7 дней: сколько дней была интенсивная нагрузка "
          "(бег, быстрая езда на велосипеде, тяжёлая работа)?", "Интенсивная: дни", DAYS),
        q("ip_vm", "extended", "Сколько минут обычно длилась интенсивная нагрузка в такой день?", "Интенсивная: минуты",
          IPAQ_MINUTES, cond={"q": "ip_vd", "not_in": ["0"]}),
        q("ip_md", "extended", "Сколько дней была умеренная нагрузка (перенос лёгких грузов, спокойная езда "
          "на велосипеде; не считая ходьбы)?", "Умеренная: дни", DAYS),
        q("ip_mm", "extended", "Сколько минут обычно длилась умеренная нагрузка в такой день?", "Умеренная: минуты",
          IPAQ_MINUTES, cond={"q": "ip_md", "not_in": ["0"]}),
        q("ip_wd", "extended", "Сколько дней вы ходили пешком не меньше 10 минут подряд?", "Ходьба: дни", DAYS),
        q("ip_wm", "extended", "Сколько минут обычно в такой день?", "Ходьба: минуты", IPAQ_MINUTES,
          cond={"q": "ip_wd", "not_in": ["0"]}),
        q("steps", "extended", "Среднее число шагов в день по фитнес-браслету или телефону (если знаете)",
          "Шаги в день", kind="number", optional=True, lo=0, hi=60000, step=100, unit="шагов"),
    ]),
    ("nutrition", "Питание", "Обычная неделя за последний месяц.", [
        q("n1", "short", "Сколько порций овощей и фруктов вы съедаете в день?", "Овощи и фрукты, порций",
          [("0", "0"), ("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("5", "5 и больше")],
          hint="Порция ≈ 80 г: яблоко, горсть салата."),
        q("n2", "short", "Сколько дней в неделю вы пьёте сладкие напитки (газировка, сок, чай или кофе с сахаром)?",
          "Сладкие напитки, дней", DAYS),
        q("n3", "short", "Сколько дней в неделю вы едите колбасу, сосиски, фастфуд или солёные снеки?",
          "Колбаса, фастфуд, дней", DAYS),
        q("n4", "medium", "Сколько дней в неделю вы едите сладости, выпечку, десерты?", "Сладости, дней", DAYS),
        q("n5", "medium", "Сколько дней в неделю в рационе есть цельные злаки, бобовые или орехи?",
          "Злаки, бобовые, орехи, дней", DAYS),
    ]),
    ("mental", "Психологическое состояние",
     "Как часто за последние 2 недели вас беспокоило следующее? Опросники PHQ и GAD.", [
         q("p1", "short", "Мало интереса или удовольствия от занятий", "Мало интереса", PHQ_OPTIONS),
         q("p2", "short", "Подавленность, уныние, безнадёжность", "Подавленность", PHQ_OPTIONS),
         q("p3", "short", "Нервозность, тревога, напряжение", "Тревога", PHQ_OPTIONS),
         q("p4", "short", "Неспособность остановить или контролировать беспокойство", "Неконтролируемое беспокойство",
           PHQ_OPTIONS),
         q("ph3", "medium", "Трудности с засыпанием, прерывистый сон или слишком долгий сон", "Сон (PHQ)", PHQ_OPTIONS),
         q("ph4", "medium", "Усталость или упадок сил", "Усталость", PHQ_OPTIONS),
         q("ph5", "medium", "Плохой аппетит или переедание", "Аппетит", PHQ_OPTIONS),
         q("ph6", "medium", "Плохое мнение о себе: ощущение, что вы неудачник или подвели себя или семью",
           "Плохое мнение о себе", PHQ_OPTIONS),
         q("ph7", "medium", "Трудно сосредоточиться, например на чтении или просмотре фильма", "Концентрация",
           PHQ_OPTIONS),
         q("ph8", "medium", "Движения или речь настолько замедлены, что это заметно другим, — или наоборот, "
           "непоседливость и беспокойство", "Замедленность / непоседливость", PHQ_OPTIONS),
         q("ga3", "medium", "Слишком сильное беспокойство по разным поводам", "Беспокойство по разным поводам",
           PHQ_OPTIONS),
         q("ga4", "medium", "Трудно расслабиться", "Трудно расслабиться", PHQ_OPTIONS),
         q("ga5", "medium", "Беспокойство настолько сильное, что трудно усидеть на месте", "Не усидеть на месте",
           PHQ_OPTIONS),
         q("ga6", "medium", "Лёгкая раздражительность", "Раздражительность", PHQ_OPTIONS),
         q("ga7", "medium", "Страх, будто может случиться что-то ужасное", "Страх", PHQ_OPTIONS),
     ]),
    ("habits", "Никотин и алкоголь", "Алкоголь — за последний год. Стандартная порция — 10 г спирта: "
     "250 мл пива, 100 мл вина или 30 мл крепкого напитка.", [
        q("nic1", "short", "Курите ли вы сигареты или другие табачные изделия (включая нагреваемый табак)?", "Курение",
          [("never", "Никогда не курил(а)"), ("former", "Бросил(а)"), ("current", "Курю")]),
        q("nic2", "short", "Как давно вы бросили?", "Срок без курения",
          [("lt1", "Меньше года"), ("1_5", "1–5 лет"), ("ge5", "5 лет и больше")], cond={"q": "nic1", "in": ["former"]}),
        q("nic3", "short", "Пользуетесь ли вы электронными сигаретами или вейпами?", "Вейп", [("no", "Нет"), ("yes", "Да")]),
        q("nic4", "short", "Курит ли кто-то в помещении, где вы живёте?", "Курение дома", [("no", "Нет"), ("yes", "Да")]),
        q("a1", "short", "Как часто вы употребляете алкоголь?", "Частота",
          [("0", "Никогда"), ("1", "Раз в месяц или реже"), ("2", "2–4 раза в месяц"), ("3", "2–3 раза в неделю"),
           ("4", "4 раза в неделю и чаще")]),
        q("a2", "short", "Сколько стандартных порций вы обычно выпиваете в такой день?", "Порций за раз",
          [("0", "1–2"), ("1", "3–4"), ("2", "5–6"), ("3", "7–9"), ("4", "10 и больше")], cond={"q": "a1", "not_in": ["0"]}),
        q("a3", "short", "Как часто вы выпиваете 6 и больше порций за раз?", "6+ порций", AUDIT_FREQ5,
          cond={"q": "a1", "not_in": ["0"]}),
        q("a4", "extended", "Как часто за последний год вы не могли остановиться, начав пить?", "Не мог(ла) остановиться",
          AUDIT_FREQ5, cond={"audit_positive": True}),
        q("a5", "extended", "Как часто из-за выпивки вы не сделали того, что от вас ожидали?", "Не сделал(а) ожидаемого",
          AUDIT_FREQ5, cond={"audit_positive": True}),
        q("a6", "extended", "Как часто вам нужно было выпить утром, чтобы прийти в себя после выпивки накануне?",
          "Выпивка утром", AUDIT_FREQ5, cond={"audit_positive": True}),
        q("a7", "extended", "Как часто вы чувствовали вину или раскаяние после выпивки?", "Вина", AUDIT_FREQ5,
          cond={"audit_positive": True}),
        q("a8", "extended", "Как часто вы не могли вспомнить, что было накануне, из-за выпивки?", "Провалы в памяти",
          AUDIT_FREQ5, cond={"audit_positive": True}),
        q("a9", "extended", "Были ли вы или кто-то другой травмированы из-за вашей выпивки?", "Травмы", AUDIT_YESNO,
          cond={"audit_positive": True}),
        q("a10", "extended", "Беспокоились ли родные, друзья или врач о том, сколько вы пьёте, или советовали пить меньше?",
          "Беспокойство близких", AUDIT_YESNO, cond={"audit_positive": True}),
    ]),
    ("wellbeing", "Самочувствие и связи", "Сейчас и в последнее время.", [
        q("w1", "medium", "В целом как бы вы оценили своё здоровье?", "Самооценка здоровья",
          [("4", "Отличное"), ("3", "Очень хорошее"), ("2", "Хорошее"), ("1", "Удовлетворительное"), ("0", "Плохое")]),
        q("w2", "medium", "Как часто вы чувствуете, что вам не хватает общения?", "Не хватает общения", OFTEN3),
        q("w3", "medium", "Как часто вы чувствуете себя обделённым, оставленным в стороне?", "Оставлен(а) в стороне", OFTEN3),
        q("w4", "medium", "Как часто вы чувствуете себя изолированным от других?", "Изоляция", OFTEN3),
    ]),
    ("body", "Тело и метаболизм", "Из последних анализов, выписки или домашнего тонометра. Любое поле можно пропустить.", [
        q("height", "extended", "Рост", "Рост", kind="number", optional=True, lo=120, hi=230, step=1, unit="см"),
        q("weight", "extended", "Вес", "Вес", kind="number", optional=True, lo=30, hi=300, step=0.1, unit="кг",
          cond={"q": "restriction", "not_in": ["pregnant"]}),
        q("waist", "extended", "Окружность талии", "Талия", kind="number", optional=True, lo=40, hi=200, step=1,
          unit="см", cond={"q": "restriction", "not_in": ["pregnant"]}),
        q("sbp", "extended", "Давление: верхнее (систолическое)", "Верхнее давление", kind="number", optional=True,
          lo=70, hi=260, step=1, unit="мм рт. ст."),
        q("dbp", "extended", "Давление: нижнее (диастолическое)", "Нижнее давление", kind="number", optional=True,
          lo=40, hi=160, step=1, unit="мм рт. ст."),
        q("bp_src", "extended", "Где измерено давление?", "Где измерено",
          [("home", "Дома, среднее за несколько дней"), ("clinic", "У врача")], optional=True),
        q("bp_tx", "extended", "Принимаете препараты от давления?", "Лечение давления", [("no", "Нет"), ("yes", "Да")],
          optional=True),
        q("chol", "extended", "Общий холестерин", "Общий холестерин", kind="number", optional=True, lo=1, hi=20,
          step=0.01, unit="ммоль/л"),
        q("hdl", "extended", "Холестерин ЛПВП («хороший»)", "ЛПВП", kind="number", optional=True, lo=0.2, hi=5,
          step=0.01, unit="ммоль/л"),
        q("ldl", "extended", "Холестерин ЛПНП («плохой»)", "ЛПНП", kind="number", optional=True, lo=0.2, hi=15,
          step=0.01, unit="ммоль/л"),
        q("lip_tx", "extended", "Принимаете препараты для снижения холестерина?", "Лечение холестерина",
          [("no", "Нет"), ("yes", "Да")], optional=True),
        q("dm", "extended", "Врач диагностировал у вас сахарный диабет?", "Диабет", [("no", "Нет"), ("yes", "Да")],
          optional=True),
        q("glu", "extended", "Глюкоза натощак", "Глюкоза", kind="number", optional=True, lo=2, hi=30, step=0.1,
          unit="ммоль/л"),
        q("hba1c", "extended", "Гликированный гемоглобин HbA1c", "HbA1c", kind="number", optional=True, lo=3, hi=20,
          step=0.1, unit="%"),
        q("lab_age", "extended", "Когда сданы анализы?", "Давность анализов",
          [("lt3m", "Меньше 3 месяцев назад"), ("3_12m", "3–12 месяцев назад"), ("gt12m", "Больше года назад")],
          optional=True),
        q("checkup", "extended", "Когда вы последний раз проходили диспансеризацию или профосмотр?", "Диспансеризация",
          [("lt1y", "Меньше года назад"), ("1_3y", "1–3 года назад"), ("gt3y", "Больше 3 лет назад"),
           ("never", "Не проходил(а)")], optional=True),
    ]),
]
QUESTIONS = {item["id"]: item for _, _, _, items in STEPS for item in items}

# ---------- Таблицы баллов ----------

# LE8 (Lloyd-Jones 2022, табл. 1)
LE8_SLEEP = {"lt4": 0, "4_5": 20, "5_6": 40, "6_7": 70, "7_9": 100, "9_10": 90, "ge10": 40}
LE8_PA = [(150, 100), (120, 90), (90, 80), (60, 60), (30, 40), (1, 20), (0, 0)]  # (минут от, балл)
LE8_BMI = [(40, 0), (35, 15), (30, 30), (25, 70), (0, 100)]                        # (ИМТ от, балл)
LE8_NONHDL_MMOL = [(5.69, 0), (4.91, 20), (4.14, 40), (3.36, 60), (0, 100)]
LE8_NICOTINE = {"never": 100, "ge5": 75, "1_5": 50, "lt1": 25, "current": 0}
PA_MINUTES_ANCHOR = 150
STRENGTH = {"0": 0, "1": 50, "2plus": 100}
INTENSITY = {"moderate": 1, "vigorous": 2}
IPAQ_MET = {"vig": 8.0, "mod": 4.0, "walk": 3.3}
MET_PER_MODERATE_MINUTE = 4.0  # 600 МЕТ-мин/нед ≈ 150 минут (ВОЗ, GPAQ)
SRH = {"4": 100, "3": 75, "2": 50, "1": 25, "0": 0}


class ScoringError(ValueError):
    """Ошибка валидации ответов. errors — {поле: описание}; code — тип ошибки."""

    def __init__(self, errors, code="validation_error"):
        self.errors = errors
        self.code = code
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


def _round(x):
    return int(math.floor(x + 0.5))


def level_for(total):
    return next(level for level in LEVELS if total >= level[0])


def summary_for(total):
    _, _, name, text = level_for(total)
    return f"{name}. {text}"


def sphere_level(points):
    return "low" if points < 50 else "mid" if points < 80 else "high"


def _table(value, rows):
    return next(points for threshold, points in rows if value >= threshold)


def _plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else many


# ---------- Условия показа и валидация ----------

def audit_c(a):
    return sum(int(a.get(k) or 0) for k in ("a1", "a2", "a3")) if a.get("a1") not in (None, "0") else 0


def audit_c_positive(a):
    return audit_c(a) >= (4 if a.get("sex") == "male" else 3)


def condition_met(cond, a):
    if not cond:
        return True
    if cond.get("audit_positive"):
        return audit_c_positive(a)
    value = a.get(cond["q"])
    if value is None:
        return False
    if "in" in cond:
        return value in cond["in"]
    return value not in cond["not_in"]


def visible(question, a, tier):
    return TIER_RANK[question["tier"]] <= TIER_RANK[tier] and condition_met(question["cond"], a)


def validate(answers):
    """→ (tier, чистые ответы). Невидимые на выбранном уровне вопросы отбрасываются."""
    if not isinstance(answers, dict):
        raise ScoringError({"answers": "ожидается объект с ответами"})
    tier = answers.get("tier") or "short"
    if tier not in TIERS:
        raise ScoringError({"tier": "допустимые значения: " + ", ".join(TIERS)})
    errors, clean = {}, {}
    for qid, question in QUESTIONS.items():  # порядок анкеты: условия ссылаются на более ранние вопросы
        if not visible(question, clean, tier):
            continue
        raw = answers.get(qid)
        if raw is None or raw == "":
            if not question["optional"]:
                errors[qid] = "обязательный вопрос"
            continue
        if question["kind"] == "number":
            try:
                number = float(str(raw).replace(",", "."))
            except ValueError:
                errors[qid] = "нужно число"
                continue
            if not (question["min"] <= number <= question["max"]):
                errors[qid] = f"от {question['min']} до {question['max']} {question['unit']}"
                continue
            clean[qid] = number
        else:
            value = str(raw)
            if value not in {v for v, _ in question["options"]}:
                errors[qid] = "недопустимый ответ"
            else:
                clean[qid] = value
    if errors:
        raise ScoringError(errors)
    if clean["age"] == "under18":
        raise ScoringError({"age": "Анкета Adelina Health рассчитана на взрослых — от 18 лет."}, code="age_restricted")
    return tier, clean


# ---------- Сферы ----------

def _pa_minutes_core(a):
    return 0 if a["pa1"] == "0" else int(a["pa1"]) * int(a["pa2"])


def _sleep(a):
    return {"core": LE8_SLEEP[a["sl1"]], "items": {"sl1": (LE8_SLEEP[a["sl1"]], 1.0)}}


def _activity(a, tier):
    minutes = _pa_minutes_core(a)
    core = _table(minutes, LE8_PA)
    out = {"core": core, "minutes": minutes, "items": {"aerobic": (core, 1.0)}}
    if TIER_RANK[tier] >= 1:
        mult = INTENSITY[a["pa3"]] if a["pa1"] != "0" else 1
        eq_minutes = minutes * mult
        source = "evs"
        if TIER_RANK[tier] >= 2:
            met = (IPAQ_MET["vig"] * int(a["ip_vd"]) * int(a.get("ip_vm", 0))
                   + IPAQ_MET["mod"] * int(a["ip_md"]) * int(a.get("ip_mm", 0))
                   + IPAQ_MET["walk"] * int(a["ip_wd"]) * int(a.get("ip_wm", 0)))
            eq_minutes, source = met / MET_PER_MODERATE_MINUTE, "ipaq"
            out["met_minutes"] = round(met)
        aerobic = _table(eq_minutes, LE8_PA)
        strength = STRENGTH[a["pa4"]]
        out.update(refined=(aerobic + strength) / 2, eq_minutes=round(eq_minutes), aerobic_source=source,
                   items={"aerobic": (aerobic, .5), "strength": (strength, .5)})
    return out


def _nutrition(a, tier):
    def per_day_good(k):
        return min(100.0, int(a[k]) / 5 * 100)

    def days_bad(k):
        return (7 - int(a[k])) / 7 * 100

    items = {"n1": per_day_good("n1"), "n2": days_bad("n2"), "n3": days_bad("n3")}
    core = sum(items.values()) / 3
    out = {"core": core, "items": {k: (v, 1 / 3) for k, v in items.items()}}
    if TIER_RANK[tier] >= 1:
        items.update(n4=days_bad("n4"), n5=int(a["n5"]) / 7 * 100)
        out.update(refined=sum(items.values()) / 5, items={k: (v, .2) for k, v in items.items()})
    return out


def _mental(a, tier):
    p = {k: int(a[k]) for k in ("p1", "p2", "p3", "p4")}
    phq4 = sum(p.values())
    out = {"core": 100 - phq4 / 12 * 100, "phq4": phq4, "phq2": p["p1"] + p["p2"], "gad2": p["p3"] + p["p4"],
           "items": {k: (100 - v / 3 * 100, .25) for k, v in p.items()}}
    if TIER_RANK[tier] >= 1:
        phq_items = ["p1", "p2", "ph3", "ph4", "ph5", "ph6", "ph7", "ph8"]
        gad_items = ["p3", "p4", "ga3", "ga4", "ga5", "ga6", "ga7"]
        phq8 = sum(int(a[k]) for k in phq_items)
        gad7 = sum(int(a[k]) for k in gad_items)
        items = {k: (100 - int(a[k]) / 3 * 100, .5 / 8) for k in phq_items}
        items.update({k: (100 - int(a[k]) / 3 * 100, .5 / 7) for k in gad_items})
        out.update(refined=((100 - phq8 / 24 * 100) + (100 - gad7 / 21 * 100)) / 2, phq8=phq8, gad7=gad7, items=items)
    return out


def _nicotine(a):
    status = a["nic1"]
    score = LE8_NICOTINE["current"] if status == "current" else LE8_NICOTINE["never"] if status == "never" \
        else LE8_NICOTINE[a["nic2"]]
    if a["nic3"] == "yes" and status != "current":
        score = min(score, 25)  # вейп = «бросил меньше года назад или использует ЭСДН» в LE8
    if a["nic4"] == "yes" and score > 0:
        score = max(0, score - 20)
    # бросивший без вейпа и курения дома — балл растёт только со временем, шага на неделю нет
    modifiable = status == "current" or a["nic3"] == "yes" or a["nic4"] == "yes"
    return {"core": score, "items": {"nicotine": (score, 1.0)}, "modifiable": modifiable}


def _alcohol(a, tier):
    total = audit_c(a)
    items = {k: (100 - (int(a[k]) if a["a1"] != "0" else 0) / 4 * 100, 1 / 3) for k in ("a1", "a2", "a3")}
    out = {"core": 100 - total / 12 * 100, "audit_c": total, "positive": audit_c_positive(a), "items": items}
    if TIER_RANK[tier] >= 2 and out["positive"]:
        full = total + sum(int(a[f"a{i}"]) for i in range(4, 11))
        out["audit"] = full
        out["audit_zone"] = 1 if full <= 7 else 2 if full <= 15 else 3 if full <= 19 else 4
    return out


def _wellbeing(a):
    srh = SRH[a["w1"]]
    lonely = sum(int(a[k]) for k in ("w2", "w3", "w4"))
    loneliness_score = 100 - (lonely - 3) / 6 * 100
    return {"refined": (srh + loneliness_score) / 2, "loneliness": lonely,
            "items": {"w1": (srh, .5), "loneliness": (loneliness_score, .5)}}


def _body(a):
    """Четыре показателя здоровья LE8 по внесённым данным. Анализы старше года не используются."""
    parts, info = {}, {}
    if a.get("height") and a.get("weight"):
        bmi = a["weight"] / (a["height"] / 100) ** 2
        info["bmi"] = round(bmi, 1)
        parts["bmi"] = _table(bmi, LE8_BMI)
    if a.get("sbp") and a.get("dbp"):
        s, d = a["sbp"], a["dbp"]
        bp = 0 if s >= 160 or d >= 100 else 25 if s >= 140 or d >= 90 else 50 if s >= 130 or d >= 80 \
            else 75 if s >= 120 else 100
        if a.get("bp_tx") == "yes":
            bp = max(0, bp - 20)
        parts["bp"] = bp
    labs_fresh = a.get("lab_age") != "gt12m"
    if labs_fresh and a.get("chol") and a.get("hdl"):
        nonhdl = a["chol"] - a["hdl"]
        info["nonhdl"] = round(nonhdl, 2)
        lip = _table(nonhdl, LE8_NONHDL_MMOL)
        if a.get("lip_tx") == "yes":
            lip = max(0, lip - 20)
        parts["lipids"] = lip
    if labs_fresh and (a.get("glu") or a.get("hba1c")):
        g, h = a.get("glu"), a.get("hba1c")
        if a.get("dm") == "yes":
            if h:
                parts["glucose"] = 40 if h < 7 else 30 if h < 8 else 20 if h < 9 else 10 if h < 10 else 0
        else:
            prediabetes = (g is not None and g >= 5.6) or (h is not None and h >= 5.7)
            parts["glucose"] = 60 if prediabetes else 100
    if not parts:
        return None
    return {"refined": sum(parts.values()) / len(parts), "parts": parts, "known": len(parts), **info}


# ---------- Красные флаги ----------

def _flag(code, level, title, text, **extra):
    return {"code": code, "level": level, "title": title, "text": text, **extra}


def red_flags(a, d, tier):
    m, flags = d["mental"], []
    phq8, gad7 = m.get("phq8"), m.get("gad7")
    if m["phq4"] >= 9:
        flags.append(_flag("distress", "urgent", "Не откладывайте разговор со специалистом",
                           "Ваши ответы говорят о выраженном эмоциональном напряжении. Это не диагноз — короткий "
                           "опросник лишь помогает заметить, что нужна поддержка. Обратитесь к терапевту, психиатру "
                           "или психотерапевту в ближайшие дни.", contacts=True))
    else:
        dep = m["phq2"] >= 3 or (phq8 is not None and phq8 >= 10)
        anx = m["gad2"] >= 3 or (gad7 is not None and gad7 >= 10)
        if dep or anx:
            signs = " и ".join(s for s, on in (("подавленного настроения", dep), ("тревоги", anx)) if on)
            flags.append(_flag("mood", "warn", "Стоит обсудить своё состояние со специалистом",
                               f"В ответах есть признаки {signs}. Это не диагноз, а повод обратиться к терапевту, "
                               "психиатру или психотерапевту."))
    if a["sl2"] == "3plus":
        flags.append(_flag("insomnia", "warn", "Проблемы со сном стоит обсудить с врачом",
                           "Если трудности с засыпанием или ночные пробуждения 3 ночи в неделю длятся 3 месяца и "
                           "дольше, обратитесь к врачу. Метод первой линии — когнитивно-поведенческая терапия "
                           "инсомнии, а не снотворное."))
    alc = d["alcohol"]
    if alc.get("audit_zone") == 4:
        flags.append(_flag("alcohol", "warn", "Употребление алкоголя стоит обсудить с врачом",
                           "Ответы указывают на возможную зависимость. Врач поможет оценить ситуацию и подобрать помощь."))
    b = d.get("body") or {}
    s, dia = a.get("sbp"), a.get("dbp")
    if s and dia and (s >= 180 or dia >= 120):
        flags.append(_flag("bp_crisis", "urgent", "Очень высокое давление",
                           "Перемерьте давление через несколько минут в покое. Если оно остаётся таким или есть боль "
                           "в груди, одышка, слабость в руке или нарушение речи — звоните 112.", contacts=True))
    elif s and dia and ((a.get("bp_src") == "home" and (s >= 135 or dia >= 85)) or s >= 140 or dia >= 90):
        flags.append(_flag("bp_high", "warn", "Давление выше порога гипертонии",
                           "Покажите эти измерения врачу: давление в таком диапазоне стоит обсудить."))
    labs_fresh = a.get("lab_age") != "gt12m"
    if labs_fresh and a.get("dm") != "yes" and ((a.get("glu") or 0) >= 7.0 or (a.get("hba1c") or 0) >= 6.5):
        flags.append(_flag("glucose", "warn", "Сахар крови в диапазоне диабета",
                           "Значение требует подтверждения у врача — обратитесь к терапевту."))
    if labs_fresh and ((a.get("ldl") or 0) > 4.9 or (a.get("chol") or 0) > 8):
        flags.append(_flag("lipids", "warn", "Холестерин резко повышен",
                           "Это значимый фактор риска для сердца и сосудов — обсудите его с врачом."))
    if b.get("bmi") is not None and b["bmi"] < 18.5:
        flags.append(_flag("underweight", "warn", "Вес ниже нормы",
                           "ИМТ меньше 18,5 — обсудите это с врачом. Советов по снижению веса Adelina Health не даёт."))
    if a["restriction"] != "no":
        flags.append(_flag("restriction", "info", "Советы по движению — только после разговора с врачом",
                           "Врач ограничил нагрузку или вы беременны: общие рекомендации могут не подойти. "
                           "Балл считается как обычно."))
    # профосмотр — ежегодно в любом возрасте, диспансеризация — раз в 3 года в 18–39 и ежегодно с 40 (№ 404н)
    if a.get("checkup") and a["checkup"] != "lt1y":
        flags.append(_flag("checkup", "info", "Пора пройти профосмотр или диспансеризацию",
                           "Это бесплатно по ОМС: измерят давление, холестерин и глюкозу. Профосмотр — каждый год, "
                           "диспансеризация — раз в 3 года в 18–39 лет и каждый год с 40 лет."))
    return flags


# ---------- Шаги фокуса недели и рекомендации ----------

STEPS_LIBRARY = {
    "sl1": ("Ложитесь на 30 минут раньше в будни", "Сдвиньте отход ко сну на 30 минут — это приблизит вас к 7–9 часам сна."),
    "sl1_long": ("Вставайте в одно и то же время", "Сон дольше 9 часов — повод держать постоянное время подъёма; если "
                 "усталость не проходит, обсудите это с врачом."),
    "strength": ("Одна силовая тренировка в неделю", "20 минут с собственным весом: приседания, отжимания от стены, "
                 "планка, упражнения с резинкой. ВОЗ рекомендует 2 и больше дней в неделю."),
    "n1": ("Ещё одна порция овощей", "Добавьте порцию овощей или фруктов (≈ 80 г) к одному приёму пищи — цель ВОЗ: "
           "5 порций в день."),
    "n2": ("На один день без сладких напитков больше", "В один из дней замените сладкий напиток водой, чаем или кофе "
           "без сахара."),
    "n3": ("Меньше колбасы и фастфуда", "Замените колбасу, сосиски или фастфуд в один из дней на рыбу, курицу, яйца "
           "или бобовые."),
    "n4": ("Сладкое — на день реже", "Сократите сладости и выпечку на один день в неделю."),
    "n5": ("Цельные злаки и бобовые", "Добавьте день с гречкой, овсянкой, цельнозерновым хлебом, фасолью или горстью "
           "орехов."),
    "mental_dep": ("Одно приятное дело в день", "Запланируйте 15 минут на то, что раньше радовало: прогулка, музыка, "
                   "встреча."),
    "mental_anx": ("Дыхание 4–6", "Несколько раз в день по 2 минуты: вдох на 4 счёта, выдох на 6."),
    "mental_body": ("Режим сна и пауз", "Ложитесь в одно время и делайте короткие перерывы днём — это поддерживает силы "
                    "и концентрацию."),
    "smoke": ("План отказа от курения", "Назначьте дату отказа и обратитесь к врачу: с поддержкой и препаратами "
              "бросить удаётся чаще."),
    "vape": ("Откажитесь от вейпа", "Вейп тоже доставляет никотин; врач поможет подобрать способ отказа."),
    "home_smoke": ("Дом без табачного дыма", "Договоритесь с домашними курить только на улице."),
    "a1": ("На один день без алкоголя больше", "Добавьте в неделю ещё один день совсем без алкоголя."),
    "a2": ("Меньше порций за раз", "Ограничьте себя одной-двумя порциями и чередуйте их с водой."),
    "a3": ("Без больших доз", "Избегайте 6 и больше порций за раз — это самый вредный способ пить."),
    "w1": ("Один шаг для самочувствия", "Выберите одно действие из других сфер, которое даёт вам больше сил, и "
           "сделайте его 3 раза за неделю."),
    "loneliness": ("Одна встреча или звонок", "Запланируйте на неделе встречу или звонок с человеком, с которым "
                   "приятно общаться."),
}
MAINTAIN = {k: ("Поддерживайте", f"{DOMAIN_NAMES[k]}: ваши привычки близки к рекомендациям — продолжайте.")
            for k in DOMAIN_NAMES}


def step_for(item, a, d):
    """Следующая ступень рекомендации для пункта: (заголовок, текст)."""
    if item in ("aerobic", "strength") and a["restriction"] != "no":
        return ("Обсудите нагрузку с врачом",
                "Врач ограничил вам нагрузку или вы беременны — спросите, какая активность вам безопасна.")
    if item == "sl1":
        return STEPS_LIBRARY["sl1_long" if a["sl1"] in ("9_10", "ge10") else "sl1"]
    if item == "aerobic":
        have = d["activity"].get("eq_minutes", d["activity"]["minutes"])
        walks = max(1, math.ceil((PA_MINUTES_ANCHOR - have) / 30))
        word = _plural(walks, "прогулку", "прогулки", "прогулок")
        return (f"+{walks} {word} по 30 минут",
                f"Добавьте {walks} {word} быстрым шагом по 30 минут в неделю — это доведёт вас до 150 минут "
                "умеренной активности (ВОЗ).")
    if item in ("p1", "p2", "ph6"):
        return STEPS_LIBRARY["mental_dep"]
    if item in ("p3", "p4", "ga3", "ga4", "ga5", "ga6", "ga7"):
        return STEPS_LIBRARY["mental_anx"]
    if item in ("ph3", "ph4", "ph5", "ph7", "ph8"):
        return STEPS_LIBRARY["mental_body"]
    if item == "nicotine":
        return STEPS_LIBRARY["smoke" if a["nic1"] == "current" else "vape" if a["nic3"] == "yes" else "home_smoke"]
    return STEPS_LIBRARY[item]


def _domain_score(dom):
    return dom.get("refined", dom.get("core"))


def _gaps(domain, dom):
    return sorted(((100 - score) * weight, item) for item, (score, weight) in dom["items"].items())[::-1]


def _focus_candidates(d):
    keys = [k for k in DETAILED_DOMAINS if k in d]
    return [k for k in keys if not (k == "nicotine" and not d[k]["modifiable"])]


def build_recommendations(a, d):
    """Все шаги по сферам — от самой слабой сферы, внутри — от самого большого отставания."""
    keys = [k for k in DETAILED_DOMAINS if k in d]
    recs = []
    for k in sorted(keys, key=lambda k: (_domain_score(d[k]), keys.index(k))):
        score = _round(_domain_score(d[k]))
        level = sphere_level(score)
        base = {"sphere": k, "sphere_name": DOMAIN_NAMES[k], "level": level, "level_name": SPHERE_LEVEL_NAMES[level]}
        seen = set()
        for gap, item in _gaps(k, d[k]):
            if gap <= 0 or (k == "nicotine" and not d[k]["modifiable"]):
                continue
            title, text = step_for(item, a, d)
            if title not in seen:
                seen.add(title)
                recs.append({**base, "item": item, "title": title, "text": text})
        if not seen:
            title, text = MAINTAIN[k]
            recs.append({**base, "item": None, "title": title, "text": text})
    return recs


def focus_of_week(flags, a, d):
    serious = [f for f in flags if f["level"] in ("urgent", "warn")]
    if serious:
        return {"type": "specialist", "sphere": None, "item": None,
                "title": "Фокус недели — консультация специалиста", "text": serious[0]["title"] + "."}
    keys = _focus_candidates(d)
    weakest = min(keys, key=lambda k: (_domain_score(d[k]), keys.index(k)))
    gaps = _gaps(weakest, d[weakest])
    if not gaps or gaps[0][0] <= 0:
        title, text = MAINTAIN[weakest]
        return {"type": "maintain", "sphere": weakest, "item": None, "title": title, "text": text}
    title, text = step_for(gaps[0][1], a, d)
    return {"type": "step", "sphere": weakest, "item": gaps[0][1], "title": title, "text": text}


# ---------- Итог ----------

def calculate_score(answers, history=None):
    """Считает VitaScore v2.0.

    history — уточнённые измерения сфер из прошлых анкет того же клиента:
    {сфера: {"score": балл, "tier": уровень, "age_days": давность}} — для каскада точности.
    """
    tier, a = validate(answers)
    d = {"sleep": _sleep(a), "activity": _activity(a, tier), "nutrition": _nutrition(a, tier),
         "mental": _mental(a, tier), "nicotine": _nicotine(a), "alcohol": _alcohol(a, tier)}
    if TIER_RANK[tier] >= 1:
        d["wellbeing"] = _wellbeing(a)
    if TIER_RANK[tier] >= 2:
        body = _body(a)
        if body:
            d["body"] = body

    core = {k: _round(d[k]["core"]) for k in CORE_DOMAINS}
    core_total = _round(sum(core.values()) / len(core))

    # каскад точности: самое подробное свежее измерение каждой сферы
    detailed, sources = {}, {}
    for k in DETAILED_DOMAINS:
        if k in d and "refined" in d[k]:
            detailed[k], sources[k] = _round(d[k]["refined"]), tier
        elif history and k in history and history[k]["age_days"] <= VALIDITY_DAYS[k]:
            detailed[k], sources[k] = history[k]["score"], history[k]["tier"]
        elif k in core:
            detailed[k], sources[k] = core[k], "short"
    detailed_total = _round(sum(detailed.values()) / len(detailed)) if "wellbeing" in detailed else None

    flags = red_flags(a, d, tier)
    focus = focus_of_week(flags, a, d)
    _, level, level_name, _ = level_for(core_total)
    refined = {k: _round(d[k]["refined"]) for k in DETAILED_DOMAINS + ("body",) if k in d and "refined" in d[k]}
    return {
        "version": METHOD_VERSION,
        "tier": tier,
        "answers": a,
        "total": core_total,
        "level": level,
        "level_name": level_name,
        "summary": summary_for(core_total),
        "breakdown": core,
        "weakest": min(CORE_DOMAINS, key=lambda k: (core[k], CORE_DOMAINS.index(k))),
        "refined": refined,
        "detailed": {"total": detailed_total, "domains": detailed, "sources": sources} if detailed_total is not None
        else None,
        "body": {k: v for k, v in d["body"].items() if k != "refined"} | {"score": refined["body"]} if "body" in d else None,
        "le8": None,  # полный LE8 требует MEPA (LICENSED_INSTRUMENTS) — до лицензии не считается
        "screens": {"phq4": d["mental"]["phq4"], "phq8": d["mental"].get("phq8"), "gad7": d["mental"].get("gad7"),
                    "audit_c": d["alcohol"]["audit_c"], "audit": d["alcohol"].get("audit"),
                    "audit_zone": d["alcohol"].get("audit_zone"), "pa_minutes": d["activity"]["minutes"],
                    "met_minutes": d["activity"].get("met_minutes"), "sitting": a.get("pa5"), "steps": a.get("steps")},
        "flags": flags,
        "focus": focus,
        "tip": focus["text"],
        "recommendations": build_recommendations(a, d),
    }


def describe_answers(answers):
    """[(название шага, [(вопрос кратко, ответ словами)])] в порядке анкеты."""
    groups = []
    for _, title, _, questions in STEPS:
        rows = []
        for item in questions:
            if item["id"] not in answers:
                continue
            value = answers[item["id"]]
            if item["kind"] == "number":
                shown = f"{value:g} {item['unit']}"
            else:
                shown = dict(item["options"]).get(str(value), str(value))
            rows.append((item["short"], shown))
        if rows:
            groups.append((title, rows))
    return groups


def public_questions():
    """Вопросы для фронтенда: условия показа и уровни, без функций."""
    return [{"key": key, "title": title, "subtitle": sub, "questions": items} for key, title, sub, items in STEPS]
