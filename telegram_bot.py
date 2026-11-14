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
            # Con timeout > 0 Telegram espera hasta tener algo (long polling):
            # la conexión tiene que aguantar más que esa espera.
            timeout=30 + timeout,
        )
        data = r.json()
        if not data.get("ok"):
            # Antes se callaba: un 409 (otro programa leyendo el mismo bot, o un
            # webhook puesto) dejaba los ✅ cargando sin que nada lo dijera.
            print(f"get_updates rechazado por Telegram: {data.get('error_code')} "
                  f"{str(data.get('description', ''))[:200]}")
            return []
        return data.get("result", [])
    except Exception as e:
        print("Error get_updates:", e)
        return []


def send_document(contenido, nombre, caption="", chat_id=None):
    """Manda un archivo en memoria (el ticket PDF) al chat privado."""
    chat_id = chat_id or CHAT_ID
    if not TOKEN or not chat_id or not contenido:
        return None
    try:
        r = requests.post(
            f"{API}/sendDocument",
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"document": (nombre, contenido, "application/pdf")},
            timeout=60,
        )
        return r.json()
    except Exception as e:
        print("Error send_document:", e)
        return None


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


# ── Botones (el ✅ de los envíos por Shalom) ─────────────────────────
# Telegram manda el toque de un botón como `callback_query` en getUpdates,
# junto con los mensajes. Lo atiende revisar.py (procesar_comandos), que es
# el ÚNICO que lee getUpdates: dos lectores se robarían los toques.

def send_buttons(text, teclado, chat_id=None):
    """Como send_message, con botones debajo. Devuelve el message_id o None."""
    chat_id = chat_id or CHAT_ID
    if not TOKEN or not chat_id:
        print("Falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")
        return None
    try:
        r = requests.post(
            f"{API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": {"inline_keyboard": teclado},
            },
            timeout=30,
        )
        data = r.json()
        return (data.get("result") or {}).get("message_id") if data.get("ok") else None
    except Exception as e:
        print("Error send_buttons:", type(e).__name__)
        return None


def edit_buttons(message_id, teclado, chat_id=None):
    """Cambia (o quita, con []) los botones de un mensaje ya mandado."""
    chat_id = chat_id or CHAT_ID
    if not TOKEN or not chat_id or not message_id:
        return None
    try:
        r = requests.post(
            f"{API}/editMessageReplyMarkup",
            json={"chat_id": chat_id, "message_id": message_id,
                  "reply_markup": {"inline_keyboard": teclado}},
            timeout=30,
        )
        return r.json()
    except Exception as e:
        print("Error edit_buttons:", type(e).__name__)
        return None


def answer_callback(callback_id, text=""):
    """Responde al toque (el aviso corto arriba de la pantalla).

    Telegram deja el botón "cargando" hasta que se responde. Un toque viejo
    (de hace más de unos minutos) ya no se puede responder: el error se
    ignora, el toque se atiende igual.
    """
    if not TOKEN or not callback_id:
        return None
    try:
        r = requests.post(f"{API}/answerCallbackQuery",
                          json={"callback_query_id": callback_id, "text": text[:190]},
                          timeout=30)
        return r.json()
    except Exception:
        return None
