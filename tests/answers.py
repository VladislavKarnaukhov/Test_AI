"""Готовые ответы анкеты VitaScore v2.0 для тестов."""

SHORT_BEST = {
    "tier": "short", "age": "18_39", "sex": "female", "restriction": "no",
    "sl1": "7_9", "sl2": "0",
    "pa1": "5", "pa2": "30",
    "n1": "5", "n2": "0", "n3": "0",
    "p1": "0", "p2": "0", "p3": "0", "p4": "0",
    "nic1": "never", "nic3": "no", "nic4": "no",
    "a1": "0",
}

# «Пример расчёта» из методики v2.0 (короткий уровень): 70 / 80 / 63 / 75 / 50 / 75 → 69
SHORT_EXAMPLE = {
    **SHORT_BEST,
    "sex": "male",
    "sl1": "6_7",
    "pa1": "3", "pa2": "30",
    "n1": "3", "n2": "2", "n3": "3",
    "p1": "1", "p2": "1", "p3": "1", "p4": "0",
    "nic1": "former", "nic2": "1_5",
    "a1": "2", "a2": "1", "a3": "0",
}

MEDIUM_EXTRA = {
    "pa3": "moderate", "pa4": "2plus", "pa5": "4_6",
    "n4": "1", "n5": "5",
    "ph3": "0", "ph4": "1", "ph5": "0", "ph6": "0", "ph7": "0", "ph8": "0",
    "ga3": "1", "ga4": "0", "ga5": "0", "ga6": "0", "ga7": "0",
    "w1": "3", "w2": "1", "w3": "1", "w4": "2",
}

EXTENDED_EXTRA = {
    "ip_vd": "2", "ip_vm": "30", "ip_md": "2", "ip_mm": "30", "ip_wd": "5", "ip_wm": "30",
    "height": 170, "weight": 70, "sbp": 118, "dbp": 76, "bp_src": "clinic", "bp_tx": "no",
    "chol": 5.0, "hdl": 1.5, "lip_tx": "no", "dm": "no", "glu": 5.0, "lab_age": "lt3m", "checkup": "lt1y",
}


def short(**changes):
    return {**SHORT_BEST, **changes}


def medium(**changes):
    return {**SHORT_BEST, **MEDIUM_EXTRA, "tier": "medium", **changes}


def extended(**changes):
    return {**SHORT_BEST, **MEDIUM_EXTRA, **EXTENDED_EXTRA, "tier": "extended", **changes}


def with_consent(data):
    return {**data, "health_consent": True}
