"""Согласие на cookie и обработку персональных данных."""
from flask import request

CONSENT_COOKIE = "vs_consent"
CONSENT_VERSION_COOKIE = "vs_consent_v"  # версия политики, с которой дан выбор
CONSENT_ALL = "all"            # необходимые + аналитика (Метрика и собственный лог)
CONSENT_NECESSARY = "necessary"
CONSENT_CHOICES = {CONSENT_ALL, CONSENT_NECESSARY}
CONSENT_MAX_AGE = 60 * 60 * 24 * 365

# Меняйте при каждой правке текста политики: версия сохраняется вместе с согласием,
# а посетители, соглашавшиеся с прошлой версией, увидят баннер снова
POLICY_VERSION = "2026-10-03"


def current_consent():
    """Выбор посетителя для действующей версии политики или None, если выбора нет или он устарел."""
    if request.cookies.get(CONSENT_VERSION_COOKIE) != POLICY_VERSION:
        return None
    return request.cookies.get(CONSENT_COOKIE)


def analytics_allowed():
    return current_consent() == CONSENT_ALL

# Редакция пользовательского соглашения (/terms); сохраняется при регистрации в users.terms_version
TERMS_VERSION = "2026-10-03"
