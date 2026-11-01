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


def _get(path, timeout=10):
    req = urllib.request.Request("https://api.brevo.com/v3" + path, method="GET",
                                 headers={"api-key": os.environ["BREVO_API_KEY"], "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def check(timeout=10):
    """Проверка настройки без отправки писем: ключ принят Brevo, отправитель подтверждён.

    → список (статус, текст), статус: "ok" | "fail" | "warn". Значения ключа не возвращаются и не логируются."""
    out = []
    key, sender = os.environ.get("BREVO_API_KEY"), os.environ.get("BREVO_SENDER_EMAIL")
    out.append(("ok" if key else "fail", "BREVO_API_KEY задан" if key else "BREVO_API_KEY не задан"))
    out.append(("ok" if sender else "fail", f"BREVO_SENDER_EMAIL задан ({sender})" if sender else "BREVO_SENDER_EMAIL не задан"))
    if not (key and sender):
        return out
    try:
        account = _get("/account", timeout)
        out.append(("ok", f"Ключ принят Brevo, аккаунт {account.get('email', '?')}"))
    except urllib.error.HTTPError as e:
        out.append(("fail", "Brevo не принял ключ (HTTP 401): проверьте BREVO_API_KEY" if e.code == 401 else f"Brevo HTTP {e.code}"))
        return out
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        out.append(("fail", f"Brevo недоступен: {type(e).__name__}"))
        return out
    try:
        senders = _get("/senders", timeout).get("senders", [])
        mine = [x for x in senders if str(x.get("email", "")).lower() == sender.lower()]
        if not mine:
            out.append(("fail", f"Отправитель {sender} не добавлен в Brevo (Senders & IP → Senders)"))
        elif not mine[0].get("active", False):
            out.append(("fail", f"Отправитель {sender} не подтверждён: откройте письмо от Brevo и подтвердите адрес"))
        else:
            out.append(("ok", f"Отправитель {sender} подтверждён"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as e:
        out.append(("warn", f"Список отправителей получить не удалось: {type(e).__name__}"))
    return out

