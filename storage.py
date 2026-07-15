# -*- coding: utf-8 -*-
"""Lectura/escritura del estado del proyecto (pedidos + offset de Telegram)."""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
ORDERS_FILE = os.path.join(BASE, "orders.json")
STATE_FILE = os.path.join(BASE, "state.json")


def load_orders():
    if not os.path.exists(ORDERS_FILE):
        return []
    with open(ORDERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_orders(orders):
    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"telegram_offset": 0}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def find_order(orders, orden):
    for o in orders:
        if str(o.get("orden")) == str(orden):
            return o
    return None
