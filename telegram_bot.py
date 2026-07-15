# -*- coding: utf-8 -*-
"""Funciones mínimas para hablar con la API de Telegram (sin librerías externas)."""
import os
import urllib.parse
import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
API = f"https://api.telegram.org/bot{TOKEN}"


def get_updates(offset=0, timeout=0):
    """Trae mensajes nuevos enviados al bot."""
    try:
        r = requests.get(
            f"{API}/getUpdates",
            params={"offset": offset, "timeout": timeout},
            timeout=30,
        )
        data = r.json()
        return data.get("result", []) if data.get("ok") else []
    except Exception as e:
        print("Error get_updates:", e)
        return []


def send_message(text, chat_id=None, disable_preview=True):
    """Envía un mensaje al dueño del bot (o a un chat concreto)."""
    chat_id = chat_id or CHAT_ID
    if not TOKEN or not chat_id:
        print("Falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")
        return None
    try:
        r = requests.post(
            f"{API}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": disable_preview,
            },
            timeout=30,
        )
        return r.json()
    except Exception as e:
        print("Error send_message:", e)
        return None
