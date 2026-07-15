# -*- coding: utf-8 -*-
"""
Script principal (corre en GitHub Actions).

En cada ejecución:
  1. Lee mensajes nuevos de Telegram -> registra pedidos nuevos.
  2. Revisa en Shalom el estado de los pedidos pendientes (con +24h y no revisados
     hace poco).
  3. Cuando un pedido llega a "En destino"/"Entregado", te manda por Telegram el
     mensaje corto + link de WhatsApp del cliente.
  4. Avisa si un pedido lleva +5 días "En tránsito".
  5. Guarda el estado (orders.json / state.json). GitHub Actions hace el commit.
"""
import datetime as dt

import mensajes
import storage
import telegram_bot as tg

CHECK_EVERY_HOURS = 6      # cada cuánto re-consultar un mismo pedido
MIN_AGE_HOURS = 24         # no revisar pedidos con menos de 24h
DEMORA_DIAS = 5            # avisar demora si sigue en tránsito tras estos días


def now():
    return dt.datetime.now(dt.timezone.utc)


def parse_iso(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def horas_desde(iso):
    d = parse_iso(iso)
    if not d:
        return None
    return (now() - d).total_seconds() / 3600.0


# ---------------------------------------------------------------------------
# 1) Registro de pedidos nuevos vía Telegram
# ---------------------------------------------------------------------------
def procesar_telegram(orders, state):
    updates = tg.get_updates(offset=state.get("telegram_offset", 0))
    nuevos = 0
    for u in updates:
        state["telegram_offset"] = u["update_id"] + 1
        msg = u.get("message") or u.get("edited_message")
        if not msg:
            continue
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "") or msg.get("caption", "")

        # Solo atender al dueño configurado (si TELEGRAM_CHAT_ID está seteado)
        if tg.CHAT_ID and chat_id != str(tg.CHAT_ID):
            continue

        low = text.strip().lower()
        if low in ("/start", "/ayuda", "/help", "ayuda"):
            tg.send_message(mensajes.AYUDA, chat_id=chat_id)
            continue
        if low.startswith("/listar") or low == "listar":
            _listar(orders, chat_id)
            continue
        if msg.get("photo") and not text:
            tg.send_message(
                "📸 Por ahora mándame los datos en texto (Orden, Código, Cliente, "
                "Teléfono, Destino). Escribe /ayuda para ver el formato.",
                chat_id=chat_id,
            )
            continue

        data = mensajes.parse_pedido(text)
        if data.get("orden") and data.get("codigo"):
            if storage.find_order(orders, data["orden"]):
                tg.send_message(f"⚠️ El pedido {data['orden']} ya estaba registrado.", chat_id=chat_id)
                continue
            pedido = {
                "orden": data["orden"],
                "codigo": data["codigo"],
                "cliente": data.get("cliente", ""),
                "telefono": data.get("telefono", ""),
                "destino": data.get("destino", ""),
                "estado": "",
                "avisado": False,
                "registrado": now().isoformat(),
                "last_checked": None,
                "demora_avisada": False,
            }
            orders.append(pedido)
            nuevos += 1
            tg.send_message(
                f"✅ Pedido registrado:\n"
                f"<b>{pedido['orden']}</b> · {pedido['cliente'] or 'cliente'} → "
                f"{pedido['destino'] or '¿destino?'}\n"
                f"Te aviso apenas llegue. 📦",
                chat_id=chat_id,
            )
        elif text.strip():
            tg.send_message(
                "No pude leer los datos. Escribe /ayuda para ver el formato exacto.",
                chat_id=chat_id,
            )
    return nuevos


def _listar(orders, chat_id):
    pend = [o for o in orders if (o.get("estado") or "").lower() != "entregado"]
    if not pend:
        tg.send_message("No tienes pedidos pendientes. 🎉", chat_id=chat_id)
        return
    lines = ["📋 <b>Pedidos pendientes</b>"]
    for o in pend:
        lines.append(
            f"• {o['orden']} · {o.get('cliente') or 'cliente'} → "
            f"{o.get('destino') or '¿?'} — {o.get('estado') or 'sin revisar'}"
        )
    tg.send_message("\n".join(lines), chat_id=chat_id)


# ---------------------------------------------------------------------------
# 2) Revisar Shalom
# ---------------------------------------------------------------------------
def debe_revisar(o):
    if (o.get("estado") or "").lower() == "entregado":
        return False
    edad = horas_desde(o.get("registrado"))
    if edad is not None and edad < MIN_AGE_HOURS:
        return False
    h = horas_desde(o.get("last_checked"))
    return h is None or h >= CHECK_EVERY_HOURS


def revisar_shalom(orders):
    pendientes = [o for o in orders if debe_revisar(o)]
    if not pendientes:
        print("No hay pedidos que consultar ahora.")
        return

    from shalom_tracker import ShalomTracker

    with ShalomTracker(headless=True) as tracker:
        for o in pendientes:
            estado = tracker.track(o["orden"], o["codigo"])
            o["last_checked"] = now().isoformat()
            if not estado:
                print(f"[{o['orden']}] no se pudo leer estado")
                continue
            print(f"[{o['orden']}] {o.get('estado','?')} -> {estado}")
            o["estado"] = estado
            estado_l = estado.lower()

            # ¿Llegó?
            if estado_l in ("en destino", "entregado") and not o.get("avisado"):
                _alertar_llegada(o)
                o["avisado"] = True

            # ¿Demora?
            elif estado_l == "en tránsito" and not o.get("demora_avisada"):
                edad = horas_desde(o.get("registrado"))
                if edad and edad / 24.0 > DEMORA_DIAS:
                    tg.send_message(
                        f"⏰ <b>Posible demora</b>\nEl pedido {o['orden']} de "
                        f"{o.get('cliente') or 'tu cliente'} lleva más de {DEMORA_DIAS} "
                        f"días en tránsito. Quizá convenga reclamar a Shalom."
                    )
                    o["demora_avisada"] = True


def _alertar_llegada(o):
    txt = mensajes.mensaje_cliente(o.get("cliente", ""), o.get("destino", ""))
    link = mensajes.wa_link(o.get("telefono", ""), txt)
    tg.send_message(
        f"🎉 <b>¡Pedido listo para recoger!</b>\n\n"
        f"Cliente: <b>{o.get('cliente') or '—'}</b>\n"
        f"Agencia: {o.get('destino') or '—'}\n\n"
        f"Mensaje: <i>{txt}</i>\n\n"
        f"👉 Toca para enviarle por WhatsApp:\n{link}"
    )


def main():
    orders = storage.load_orders()
    state = storage.load_state()

    nuevos = procesar_telegram(orders, state)
    print(f"Pedidos nuevos registrados: {nuevos}")

    revisar_shalom(orders)

    storage.save_orders(orders)
    storage.save_state(state)
    print("Listo.")


if __name__ == "__main__":
    main()
