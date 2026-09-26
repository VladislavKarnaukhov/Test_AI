"""Согласие на cookie и обработку персональных данных."""
from flask import request

CONSENT_COOKIE = "vs_consent"
CONSENT_ALL = "all"            # необходимые + аналитика (Метрика и собственный лог)
CONSENT_NECESSARY = "necessary"
CONSENT_CHOICES = {CONSENT_ALL, CONSENT_NECESSARY}
CONSENT_MAX_AGE = 60 * 60 * 24 * 365

# Меняйте при каждой правке текста политики: версия сохраняется вместе с согласием
POLICY_VERSION = "2026-09-27"


def analytics_allowed():
    return request.cookies.get(CONSENT_COOKIE) == CONSENT_ALL
