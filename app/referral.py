"""Приглашение друга: у каждого пользователя своя ссылка /r/<код>, награда обоим — подарочный Plus.

Награда выдаётся автоматически, когда приглашённый получил первую оценку в кабинете (не за одну регистрацию).
Защита: нельзя пригласить себя, у приглашённого награда только один раз, у пригласившего не больше MAX_REWARDS.
В ссылке нет ничего о самом пользователе, код случайный. Связка «кто пригласил» удаляется вместе с аккаунтом.
"""
import secrets

from flask import Blueprint, abort, redirect, session, url_for

from .db import get_db
from .plus import grant

bp = Blueprint("referral", __name__)

REWARD_DAYS = 30
MAX_REWARDS = 12
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"       # без похожих символов: i, l, o, 0, 1


def _new_code():
    return "".join(secrets.choice(ALPHABET) for _ in range(8))


def ensure_code(user_id):
    """Личный код пользователя; создаётся при первом обращении."""
    db = get_db()
    row = db.execute("SELECT ref_code FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    if row["ref_code"]:
        return row["ref_code"]
    while True:
        code = _new_code()
        if not db.execute("SELECT 1 FROM users WHERE ref_code = ?", (code,)).fetchone():
            break
    db.execute("UPDATE users SET ref_code = ? WHERE id = ?", (code, user_id))
    db.commit()
    return code


@bp.get("/r/<code>")
def invite(code):
    """Ссылка из приглашения: запоминаем код в сессии и ведём на регистрацию."""
    row = get_db().execute("SELECT id FROM users WHERE ref_code = ?", (code.lower(),)).fetchone()
    if row is None:
        abort(404)
    session["ref"] = code.lower()
    return redirect(url_for("auth.register"))


def attach(user_id):
    """Вызывается сразу после регистрации: если человек пришёл по приглашению, запоминаем, кто пригласил."""
    code = session.pop("ref", None)
    if not code:
        return False
    db = get_db()
    inviter = db.execute("SELECT id FROM users WHERE ref_code = ?", (code,)).fetchone()
    if inviter is None or inviter["id"] == user_id:
        return False
    db.execute("INSERT OR IGNORE INTO referrals (referred_id, referrer_id) VALUES (?, ?)", (user_id, inviter["id"]))
    db.commit()
    return True


def reward_if_due(user_id):
    """Награждает обоих, когда приглашённый получил первую оценку. → True, если награда выдана сейчас."""
    db = get_db()
    ref = db.execute("SELECT referrer_id FROM referrals WHERE referred_id = ? AND rewarded_at IS NULL",
                     (user_id,)).fetchone()
    if ref is None:
        return False
    if not db.execute("SELECT 1 FROM score_results WHERE user_id = ? LIMIT 1", (user_id,)).fetchone():
        return False
    done = db.execute("SELECT count(*) FROM referrals WHERE referrer_id = ? AND rewarded_at IS NOT NULL",
                      (ref["referrer_id"],)).fetchone()[0]
    db.execute("UPDATE referrals SET rewarded_at = datetime('now') WHERE referred_id = ?", (user_id,))
    db.commit()
    grant(user_id, REWARD_DAYS)                       # приглашённый получает подарок всегда
    if done < MAX_REWARDS:
        grant(ref["referrer_id"], REWARD_DAYS)
    return True


def overview(user_id):
    db = get_db()
    return {"code": ensure_code(user_id),
            "invited": db.execute("SELECT count(*) FROM referrals WHERE referrer_id = ?", (user_id,)).fetchone()[0],
            "rewarded": db.execute("SELECT count(*) FROM referrals WHERE referrer_id = ? AND rewarded_at IS NOT NULL",
                                   (user_id,)).fetchone()[0],
            "days": REWARD_DAYS, "max": MAX_REWARDS}
