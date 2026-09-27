"""Контекст посетителя: устройство, примерная страна, источник перехода. Без Flask и сторонних библиотек."""
import re
from urllib.parse import urlparse

# ---------- User-Agent ----------

_BOT_RE = re.compile(r"bot|crawl|spider|slurp|preview|headless|monitor", re.I)
_TABLET_RE = re.compile(r"iPad|Tablet|PlayBook|Silk|(Android(?!.*Mobile))", re.I)
_MOBILE_RE = re.compile(r"Mobi|iPhone|iPod|Android.*Mobile|Windows Phone", re.I)

# порядок важен: более специфичные признаки раньше общих
_OS_RULES = [
    ("Windows", re.compile(r"Windows")),
    ("iOS", re.compile(r"iPhone|iPad|iPod")),
    ("Android", re.compile(r"Android")),
    ("ChromeOS", re.compile(r"CrOS")),
    ("macOS", re.compile(r"Macintosh|Mac OS X")),
    ("Linux", re.compile(r"Linux")),
]
_BROWSER_RULES = [
    ("Yandex", re.compile(r"YaBrowser|YaSearchBrowser")),
    ("Edge", re.compile(r"Edg(e|A|iOS)?/")),
    ("Opera", re.compile(r"OPR/|Opera")),
    ("Samsung", re.compile(r"SamsungBrowser")),
    ("Firefox", re.compile(r"Firefox/|FxiOS")),
    ("Chrome", re.compile(r"Chrome/|CriOS")),
    ("Safari", re.compile(r"Version/.*Safari/")),
]


def _first_match(rules, ua):
    return next((name for name, rx in rules if rx.search(ua)), "other")


def parse_user_agent(ua):
    """Грубая классификация: {"device_type", "os", "browser"}."""
    ua = ua or ""
    if not ua:
        return {"device_type": None, "os": None, "browser": None}
    if _BOT_RE.search(ua):
        device = "bot"
    elif _TABLET_RE.search(ua):
        device = "tablet"
    elif _MOBILE_RE.search(ua):
        device = "mobile"
    else:
        device = "desktop"
    return {"device_type": device, "os": _first_match(_OS_RULES, ua), "browser": _first_match(_BROWSER_RULES, ua)}


# ---------- Примерная страна ----------

_RU_ZONES = (
    "Europe/Kaliningrad Europe/Moscow Europe/Kirov Europe/Volgograd Europe/Samara Europe/Saratov "
    "Europe/Ulyanovsk Europe/Astrakhan Asia/Yekaterinburg Asia/Omsk Asia/Novosibirsk Asia/Barnaul "
    "Asia/Tomsk Asia/Novokuznetsk Asia/Krasnoyarsk Asia/Irkutsk Asia/Chita Asia/Yakutsk Asia/Khandyga "
    "Asia/Vladivostok Asia/Ust-Nera Asia/Magadan Asia/Sakhalin Asia/Srednekolymsk Asia/Kamchatka Asia/Anadyr"
).split()

TIMEZONE_COUNTRY = {tz: "RU" for tz in _RU_ZONES}
TIMEZONE_COUNTRY.update({
    "Europe/Minsk": "BY", "Europe/Kyiv": "UA", "Europe/Kiev": "UA", "Europe/Chisinau": "MD",
    "Asia/Almaty": "KZ", "Asia/Qostanay": "KZ", "Asia/Aqtobe": "KZ", "Asia/Aqtau": "KZ",
    "Asia/Atyrau": "KZ", "Asia/Oral": "KZ", "Asia/Qyzylorda": "KZ",
    "Asia/Tashkent": "UZ", "Asia/Samarkand": "UZ", "Asia/Bishkek": "KG", "Asia/Dushanbe": "TJ",
    "Asia/Ashgabat": "TM", "Asia/Baku": "AZ", "Asia/Yerevan": "AM", "Asia/Tbilisi": "GE",
    "Europe/Riga": "LV", "Europe/Vilnius": "LT", "Europe/Tallinn": "EE", "Europe/Helsinki": "FI",
    "Europe/Warsaw": "PL", "Europe/Prague": "CZ", "Europe/Budapest": "HU", "Europe/Belgrade": "RS",
    "Europe/Podgorica": "ME", "Europe/Berlin": "DE", "Europe/Vienna": "AT", "Europe/Zurich": "CH",
    "Europe/Amsterdam": "NL", "Europe/Brussels": "BE", "Europe/Paris": "FR", "Europe/Madrid": "ES",
    "Europe/Lisbon": "PT", "Europe/Rome": "IT", "Europe/London": "GB", "Europe/Dublin": "IE",
    "Europe/Istanbul": "TR", "Asia/Nicosia": "CY", "Europe/Nicosia": "CY", "Asia/Jerusalem": "IL",
    "Asia/Dubai": "AE", "Asia/Bangkok": "TH", "Asia/Ho_Chi_Minh": "VN", "Asia/Shanghai": "CN",
    "Asia/Kolkata": "IN", "America/New_York": "US", "America/Chicago": "US",
    "America/Denver": "US", "America/Los_Angeles": "US",
})

_LANG_REGION_RE = re.compile(r"^[a-z]{2,3}-([A-Z]{2})\b", re.I)


def guess_country(timezone, language):
    """Страна по часовому поясу браузера, иначе по региону языка (ru-RU → RU). Это оценка, не геолокация."""
    if timezone in TIMEZONE_COUNTRY:
        return TIMEZONE_COUNTRY[timezone]
    m = _LANG_REGION_RE.match(language or "")
    return m.group(1).upper() if m else None


# ---------- Источник перехода ----------

def referrer_domain(referrer, own_host=None):
    """Домен внешнего реферера без www.; None для прямых заходов и переходов внутри сайта."""
    if not referrer:
        return None
    host = (urlparse(referrer).hostname or "").lower()
    if not host or (own_host and host == own_host.split(":")[0].lower()):
        return None
    return host[4:] if host.startswith("www.") else host


def classify_source(utm_source, referrer, own_host=None):
    """utm_source → домен внешнего реферера → "(direct)"."""
    if utm_source:
        return utm_source.strip().lower()
    return referrer_domain(referrer, own_host) or "(direct)"
