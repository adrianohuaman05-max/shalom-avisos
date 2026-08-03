# -*- coding: utf-8 -*-
"""Mensajes al cliente y links de WhatsApp.

Ya no hay parseo de pedidos: los envíos se leen del portal ShalomPRO, no se
registran a mano por Telegram.
"""
import urllib.parse


def fmt_wa(telefono):
    d = "".join(ch for ch in str(telefono) if ch.isdigit())
    if len(d) == 9:            # celular peruano local -> agregar código de país
        d = "51" + d
    return d


def wa_link(telefono, texto):
    return f"https://wa.me/{fmt_wa(telefono)}?text={urllib.parse.quote(texto)}"


def nombre_corto(destinatario):
    """'Ramirez Soto Ana Lucia' -> 'Lucia'. El portal a veces pone el
    apellido primero y a veces solo el nombre, así que esto es aproximado; por
    eso el mensaje se revisa antes de enviarlo."""
    partes = (destinatario or "").split()
    return partes[-1].capitalize() if len(partes) >= 3 else (
        partes[0].capitalize() if partes else "")


def agencia(destino, ubigeo=""):
    """'Av. Carlos Izaguirre Cdra. 14' + 'Lima / Lima / Los Olivos'
       -> 'Av. Carlos Izaguirre Cdra. 14 (Los Olivos)'"""
    distrito = ""
    if ubigeo and "/" in ubigeo:
        distrito = ubigeo.split("/")[-1].strip()
    if distrito and distrito.lower() not in (destino or "").lower():
        return f"{destino} ({distrito})"
    return destino or "la agencia"


def mensaje_cliente(destinatario, destino, ubigeo="", estado="En destino"):
    nombre = nombre_corto(destinatario)
    saludo = f"Hola {nombre} 👋" if nombre else "¡Hola! 👋"

    if estado == "En reparto":
        # Entrega a domicilio: no tiene que ir a ninguna agencia.
        return (
            f"{saludo} Tu pedido ya está en reparto y va camino a tu dirección. "
            f"Ten a la mano tu DNI para recibirlo. ¡Gracias por tu compra! 🙌"
        )

    return (
        f"{saludo} Tu pedido ya llegó a la agencia Shalom de "
        f"{agencia(destino, ubigeo)} y está listo para recoger. "
        f"Recuerda llevar tu DNI. ¡Gracias por tu compra! 🙌"
    )


AYUDA = (
    "🤖 <b>Bot de avisos Shalom</b>\n\n"
    "Ya no hace falta que registres nada: leo tus envíos directamente de "
    "ShalomPRO. Apenas uno llegue a destino te mando aquí el mensaje y el link "
    "de WhatsApp listo para enviar. ✅\n\n"
    "Comandos: /listar"
)
