"""Покупки без ручных действий: заказ → оплата на странице платёжного провайдера → вебхук сам открывает доступ.

Провайдер подключается двумя переменными окружения, код менять не нужно:
  PAYMENT_URL_REPORT / PAYMENT_URL_PLUS — ссылка на платёжную страницу, в ней {order} и {amount} заменяются на номер
      заказа и сумму (например https://pay.example/checkout?order={order}&amount={amount});
  BILLING_WEBHOOK_SECRET — общий секрет: провайдер (или его адаптер) присылает POST /billing/webhook с JSON
      {"order_id": 12, "status": "paid", "amount": 149, "provider_ref": "…"} и заголовком X-Signature —
      HMAC-SHA256 от сырого тела этим секретом (hex).
Пока провайдер не подключён, покупка записывает заявку (как прежняя форма Plus) и честно сообщает об этом.
Заказ оплачивается один раз: повторный вебхук ничего не меняет.
"""
import hashlib
import hmac
import json
import os

from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, request, url_for

from .auth import check_csrf, login_required
from .db import get_db
from . import plus

bp = Blueprint("billing", __name__)

REPORT_PRICE_RUB = 149
PRODUCTS = {
    "report": {"name": "Отчёт месяца, разово", "price": REPORT_PRICE_RUB, "days": 30, "env": "PAYMENT_URL_REPORT"},
    "plus": {"name": "Del Health Plus", "price": plus.PRICE_RUB, "days": 30, "env": "PAYMENT_URL_PLUS"},
}


def _fulfil(order):
    if order["product"] == "plus":
        plus.grant(order["user_id"], PRODUCTS["plus"]["days"])
    elif order["product"] == "report":
        plus.grant_report(order["user_id"], PRODUCTS["report"]["days"])


def mark_paid(order_id, provider_ref=None, amount=None):
    """→ True, если заказ оплачен именно сейчас. Повторные вызовы и неверная сумма ничего не выдают."""
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None or order["status"] != "pending":
        return False
    if amount is not None and int(amount) != order["amount"]:
        current_app.logger.warning("order %s: amount mismatch %s != %s", order_id, amount, order["amount"])
        return False
    cur = db.execute("UPDATE orders SET status = 'paid', paid_at = datetime('now'), provider_ref = ? "
                     "WHERE id = ? AND status = 'pending'", (provider_ref, order_id))
    db.commit()
    if not cur.rowcount:
        return False
    _fulfil(order)
    return True


@bp.post("/account/buy/<product>")
@login_required
def buy(product):
    check_csrf()
    item = PRODUCTS.get(product)
    if item is None:
        abort(404)
    db = get_db()
    cur = db.execute("INSERT INTO orders (user_id, product, amount) VALUES (?, ?, ?)",
                     (g.user["id"], product, item["price"]))
    db.commit()
    template = os.environ.get(item["env"], "").strip()
    if template:
        return redirect(template.format(order=cur.lastrowid, amount=item["price"]))
    db.execute("INSERT INTO leads (email, plan, user_id, policy_version) VALUES (?, ?, ?, ?)",
               (g.user["email"], item["name"], g.user["id"], g.user["policy_version"]))
    db.commit()
    flash("Онлайн-оплату мы ещё подключаем: ваш заказ записан, напишем на e-mail, как только оплата заработает.")
    return redirect(url_for("account.dashboard") + "#plus")


@bp.post("/billing/webhook")
def webhook():
    secret = os.environ.get("BILLING_WEBHOOK_SECRET", "")
    if not secret:
        abort(404)                      # без секрета приём вебхуков выключен
    body = request.get_data()
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("X-Signature", "")):
        abort(403)
    try:
        data = json.loads(body)
        order_id = int(data["order_id"])
    except (ValueError, KeyError, TypeError):
        abort(400)
    if data.get("status") != "paid":
        return jsonify(ok=True, changed=False)
    changed = mark_paid(order_id, data.get("provider_ref"), data.get("amount"))
    return jsonify(ok=True, changed=changed)
