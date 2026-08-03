# -*- coding: utf-8 -*-
"""
Script principal (corre en GitHub Actions).

La fuente de verdad es el portal ShalomPRO, no lo que se registre a mano: una
sola carga de la vista de seguimiento trae todos los envíos activos con su
estado. Los pedidos se descubren solos.

En cada ejecución:
  1. Lee los envíos activos del portal.
  2. Registra los que aún no conocía y actualiza los estados que cambiaron.
  3. Cuando uno llega a "En destino" (o "En reparto"), pide su detalle —ahí está
     el celular del destinatario— y manda a Telegram el mensaje + link wa.me.
  4. Avisa si un pedido lleva demasiados días en tránsito.
  5. Los envíos que desaparecen del portal se dan por entregados y se cierran.

PRIVACIDAD: este repo es público, así que orders.json guarda SOLO datos de
logística (orden, código, estado). El nombre y el celular del cliente se leen
del portal en el momento del aviso, viajan al chat privado de Telegram y no se
escriben nunca a disco ni a los logs.

Uso:
  python revisar.py                 # normal
  python revisar.py --sin-avisos    # solo sincroniza estados, sin avisar a nadie
"""
import datetime as dt
import sys

import mensajes
import storage
import telegram_bot as tg
from shalompro import ShalomPro

DEMORA_DIAS = 5            # avisar demora si sigue en tránsito tras estos días
AVISAR_EN = ("En destino", "En reparto")

# Campos con datos personales que las versiones viejas guardaban en orders.json.
CAMPOS_PERSONALES = ("cliente", "telefono", "destino")


def now():
    return dt.datetime.now(dt.timezone.utc)


def horas_desde(iso):
    if not iso:
        return None
    try:
        return (now() - dt.datetime.fromisoformat(iso)).total_seconds() / 3600.0
    except Exception:
        return None


def dias_desde_envio(pedido):
    """Días desde que se envió el paquete, según la fecha del portal ('02-08-2026').

    Importa que sea la fecha real de envío y no la de registro: ahora los
    pedidos se descubren solos, y uno puede aparecer llevando ya días en
    tránsito. Contar desde el descubrimiento retrasaría la alerta de demora.
    """
    fecha = (pedido.get("fecha_envio") or "").strip()
    try:
        d = dt.datetime.strptime(fecha[:10], "%d-%m-%Y").replace(
            tzinfo=dt.timezone.utc)
        return (now() - d).total_seconds() / 86400.0
    except Exception:
        horas = horas_desde(pedido.get("registrado"))
        return horas / 24.0 if horas is not None else 0.0


def limpiar_datos_personales(orders):
    """Borra de orders.json los datos de clientes que guardaba la versión vieja.

    No deshace lo ya publicado en el historial de commits, pero corta la fuga
    de aquí en adelante.
    """
    limpiados = 0
    for o in orders:
        if any(c in o for c in CAMPOS_PERSONALES):
            for c in CAMPOS_PERSONALES:
                o.pop(c, None)
            limpiados += 1
    if limpiados:
        print(f"Limpieza: datos personales borrados de {limpiados} pedido(s).")
    return limpiados


def nuevo_registro(envio):
    return {
        "orden": envio["orden"],
        "codigo": envio["codigo"],
        "estado": envio["estado"],
        "fecha_envio": envio.get("fecha", ""),
        "avisado": False,
        "cerrado": False,
        "demora_avisada": False,
        "registrado": now().isoformat(),
        "last_checked": now().isoformat(),
    }


def avisar_llegada(pro, pedido, estado):
    """Pide el detalle (trae el celular) y manda el aviso a Telegram."""
    d = pro.detalle(pedido["orden"])
    if not d:
        print(f"[{pedido['orden']}] llegó a '{estado}' pero no se pudo leer el "
              f"detalle; se reintentará en la próxima corrida.")
        return False

    texto = mensajes.mensaje_cliente(
        d.get("destinatario", ""), d.get("destino", ""),
        d.get("destino_ubigeo", ""), estado)
    link = mensajes.wa_link(d.get("telefono", ""), texto)

    titulo = ("🚚 <b>¡Pedido en reparto!</b>" if estado == "En reparto"
              else "🎉 <b>¡Pedido listo para recoger!</b>")
    tg.send_message(
        f"{titulo}\n\n"
        f"Cliente: <b>{d.get('destinatario') or '—'}</b>\n"
        f"Pedido: {pedido['orden']} · {mensajes.agencia(d.get('destino',''), d.get('destino_ubigeo',''))}\n\n"
        f"Mensaje: <i>{texto}</i>\n\n"
        f"👉 Toca para enviarle por WhatsApp:\n{link}"
    )
    # El log es público: solo el número de orden, nada del cliente.
    print(f"[{pedido['orden']}] aviso enviado a Telegram ({estado}).")
    return True


def avisar_demora(pedido):
    dias = dias_desde_envio(pedido)
    if dias <= DEMORA_DIAS:
        return False
    tg.send_message(
        f"⏰ <b>Posible demora</b>\nEl pedido {pedido['orden']} lleva "
        f"{int(dias)} días en tránsito (enviado el "
        f"{pedido.get('fecha_envio') or '¿?'}). Quizá convenga reclamar a Shalom."
    )
    print(f"[{pedido['orden']}] aviso de demora enviado.")
    return True


def procesar_comandos(orders, state):
    """Atiende /listar y /ayuda. Ya no se registran pedidos por aquí: los trae
    el portal. Se mantiene solo para poder consultar el estado desde el celular."""
    for u in tg.get_updates(offset=state.get("telegram_offset", 0)):
        state["telegram_offset"] = u["update_id"] + 1
        msg = u.get("message") or u.get("edited_message")
        if not msg:
            continue
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if tg.CHAT_ID and chat_id != str(tg.CHAT_ID):
            continue

        texto = (msg.get("text") or "").strip().lower()
        if texto.startswith("/listar") or texto == "listar":
            pend = [o for o in orders if not o.get("cerrado")]
            if not pend:
                tg.send_message("No tienes pedidos en curso. 🎉", chat_id=chat_id)
            else:
                lineas = ["📋 <b>Pedidos en curso</b>"]
                for o in pend:
                    aviso = " ✅ avisado" if o.get("avisado") else ""
                    lineas.append(f"• {o['orden']} — {o.get('estado') or '¿?'}{aviso}")
                tg.send_message("\n".join(lineas), chat_id=chat_id)
        elif texto:
            tg.send_message(mensajes.AYUDA, chat_id=chat_id)


def cerrar_desaparecidos(orders, vistos):
    """Un envío que ya no está en seguimiento fue entregado y sale de la vista."""
    cerrados = 0
    for o in orders:
        if o.get("cerrado") or o["orden"] in vistos:
            continue
        o["cerrado"] = True
        o["estado"] = "Entregado"
        cerrados += 1
    if cerrados:
        print(f"Cerrados {cerrados} pedido(s) que ya no están en seguimiento.")


def main():
    sin_avisos = "--sin-avisos" in sys.argv

    orders = storage.load_orders()
    state = storage.load_state()
    limpiar_datos_personales(orders)
    procesar_comandos(orders, state)

    with ShalomPro(headless=True) as pro:
        activos = pro.listar()
        print(f"Envíos activos en el portal: {len(activos)}")

        vistos = set()
        for envio in activos:
            vistos.add(envio["orden"])
            pedido = storage.find_order(orders, envio["orden"])

            if not pedido:
                pedido = nuevo_registro(envio)
                orders.append(pedido)
                print(f"[{pedido['orden']}] nuevo, estado '{pedido['estado']}'.")
            else:
                anterior = pedido.get("estado")
                if anterior != envio["estado"]:
                    print(f"[{pedido['orden']}] {anterior} -> {envio['estado']}")
                pedido["estado"] = envio["estado"]
                pedido["codigo"] = envio["codigo"] or pedido.get("codigo", "")
                # Los pedidos que venían de la versión vieja no traen fecha.
                pedido["fecha_envio"] = envio.get("fecha") or pedido.get(
                    "fecha_envio", "")
                pedido["cerrado"] = False
                pedido["last_checked"] = now().isoformat()

            if sin_avisos:
                continue

            estado = pedido["estado"]
            if estado in AVISAR_EN and not pedido.get("avisado"):
                if avisar_llegada(pro, pedido, estado):
                    pedido["avisado"] = True
            elif estado == "En tránsito" and not pedido.get("demora_avisada"):
                if avisar_demora(pedido):
                    pedido["demora_avisada"] = True

        cerrar_desaparecidos(orders, vistos)

    storage.save_orders(orders)
    storage.save_state(state)
    if sin_avisos:
        print("Modo --sin-avisos: estados sincronizados, no se avisó a nadie.")
    print("Listo.")


if __name__ == "__main__":
    main()
