"""Отправка писем через Brevo (transactional API). Только стандартная библиотека.

Настройка (переменные окружения): BREVO_API_KEY, BREVO_SENDER_EMAIL (подтверждённый отправитель в Brevo),
BREVO_SENDER_NAME (по умолчанию «Del Health»). Без ключа письма не уходят: send_email возвращает (False, причина).
Ключ нигде не логируется.
"""
import json
import os
import urllib.error
import urllib.request

API_URL = "https://api.brevo.com/v3/smtp/email"


def configured():
    return bool(os.environ.get("BREVO_API_KEY") and os.environ.get("BREVO_SENDER_EMAIL"))


def send_email(to_email, to_name, subject, html, text, unsubscribe_url=None, timeout=10):
    """→ (True, message_id) или (False, причина). Не бросает исключений сети."""
    if not configured():
        return False, "BREVO_API_KEY / BREVO_SENDER_EMAIL не заданы"
    payload = {
        "sender": {"name": os.environ.get("BREVO_SENDER_NAME", "Del Health"), "email": os.environ["BREVO_SENDER_EMAIL"]},
        "to": [{"email": to_email, "name": to_name or to_email}],
        "subject": subject,
        "htmlContent": html,
        "textContent": text,
    }
    if unsubscribe_url:
        payload["headers"] = {"List-Unsubscribe": f"<{unsubscribe_url}>"}
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"api-key": os.environ["BREVO_API_KEY"], "content-type": "application/json", "accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
            return True, body.get("messageId", "")
    except urllib.error.HTTPError as e:
        return False, f"Brevo HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return False, f"Brevo недоступен: {type(e).__name__}"
