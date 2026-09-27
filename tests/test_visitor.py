import pytest

from app.visitor import classify_source, guess_country, parse_user_agent, referrer_domain

UA = {
    "iphone": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "ipad": "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "android_tablet": "Mozilla/5.0 (Linux; Android 13; SM-X700) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "win_edge": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0",
    "mac_chrome": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "yandex": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 YaBrowser/24.7.0.0 Safari/537.36",
    "firefox_linux": "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "yandexbot": "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
}


@pytest.mark.parametrize("key,expected", [
    ("iphone", ("mobile", "iOS", "Safari")),
    ("ipad", ("tablet", "iOS", "Safari")),
    ("android_tablet", ("tablet", "Android", "Chrome")),
    ("win_edge", ("desktop", "Windows", "Edge")),
    ("mac_chrome", ("desktop", "macOS", "Chrome")),
    ("yandex", ("desktop", "Windows", "Yandex")),
    ("firefox_linux", ("desktop", "Linux", "Firefox")),
])
def test_parse_user_agent(key, expected):
    r = parse_user_agent(UA[key])
    assert (r["device_type"], r["os"], r["browser"]) == expected


def test_parse_user_agent_bot_and_empty():
    assert parse_user_agent(UA["yandexbot"])["device_type"] == "bot"
    assert parse_user_agent("") == {"device_type": None, "os": None, "browser": None}


@pytest.mark.parametrize("tz,lang,country", [
    ("Europe/Moscow", "en-US", "RU"),       # часовой пояс важнее языка
    ("Asia/Novosibirsk", "ru", "RU"),
    ("Asia/Almaty", "ru-RU", "KZ"),
    ("Pacific/Fiji", "en-FJ", "FJ"),        # неизвестный пояс — регион языка
    (None, "ru", None),
    (None, None, None),
])
def test_guess_country(tz, lang, country):
    assert guess_country(tz, lang) == country


def test_sources():
    assert referrer_domain("https://www.google.com/search?q=1") == "google.com"
    assert referrer_domain("https://site.test/page", own_host="site.test:443") is None
    assert referrer_domain("") is None
    assert classify_source(" VK ", "https://google.com/") == "vk"
    assert classify_source(None, "https://t.me/channel") == "t.me"
    assert classify_source(None, None) == "(direct)"
