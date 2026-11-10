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
    """'Ramirez Soto Ana Lucia' -> 'Lucia'. El portal a veces pone el apellido
    primero y a veces solo el nombre, así que esto es aproximado; por eso el
    mensaje se revisa antes de enviarlo."""
    partes = (destinatario or "").split()
    return partes[-1].capitalize() if len(partes) >= 3 else (
        partes[0].capitalize() if partes else "")


ical = ("av", "av.", "jr", "jr.", "calle", "psje", "pasaje", "mz", "urb",
        "prolongacion", "prolongación", "carretera", "ca.", "esq")


def agencia(destino, ubigeo=""):
    """Nombre de agencia legible para el cliente.

    El distrito solo se añade cuando el destino es una CALLE, porque ahí sin él
    es ambiguo ('Av. Carlos Izaguirre Cdra. 14' -> '... (Los Olivos)'). Cuando
    la agencia se llama como el sitio ('Tingo Maria Co Buenos Aires', 'Chala')
    añadirlo estorba: el cliente reconoce el pueblo, no el distrito.
    """
    destino = (destino or "").strip()
    if not destino:
        return "la agencia"

    primera = destino.split()[0].lower() if destino.split() else ""
    if primera not in ical:
        return destino

    distrito = ""
    if ubigeo and "/" in ubigeo:
        distrito = ubigeo.split("/")[-1].strip()
    if distrito and distrito.lower() not in destino.lower():
        return f"{destino} ({distrito})"
    return destino


# ── Aviso de llegada: varias versiones del mismo mensaje ─────────────
# Un cliente que vuelve a comprar recibía siempre el mismo texto, letra por
# letra. Ahora hay varias versiones y a cada cliente le toca una distinta de
# la anterior (el turno lo lleva variantes.py).
#
# Para cambiar o añadir textos basta con tocar estas dos listas. Reglas:
#   - {saludo} es "Hola Lucia 👋" (o "¡Hola! 👋" si no hay nombre).
#   - {hola} es "Hola Lucia" (o "Hola"), para saludos con otra puntuación.
#   - {lugar} es "la agencia Shalom de Chala". Solo en las de agencia.
#   - Todas dicen dónde está el pedido y que hay que llevar el DNI.
#   - La primera de cada lista es el mensaje de siempre: no la muevas de sitio,
#     es la que se usa al reenviar avisos de pedidos antiguos.
LLEGADA_AGENCIA = (
    "{saludo} Tu pedido ya llegó a {lugar} y está listo para recoger. "
    "Recuerda llevar tu DNI. ¡Gracias por tu compra! 🙌",

    "¡{hola}! Buenas noticias: tu pedido ya está en {lugar}. Puedes pasar a "
    "recogerlo cuando gustes, solo lleva tu DNI. ¡Gracias por la confianza! 💪",

    "{saludo} Te aviso que tu pedido ya llegó a {lugar}. Ya lo puedes recoger, "
    "no te olvides de llevar tu DNI. ¡Que lo disfrutes! 😋",

    "{hola}, ¿qué tal? 👋 Tu pedido ya te espera en {lugar}. Para recogerlo "
    "solo necesitas tu DNI. ¡Gracias por tu compra! 🙌",

    "{saludo} Ya llegó tu pedido. Está en {lugar}, listo para que lo "
    "recojas. Lleva tu DNI cuando vayas. ¡Gracias por tu preferencia! 🎉",

    "¡{hola}! Paso a avisarte que tu pedido ya está listo para recoger en "
    "{lugar}. Recuerda llevar tu DNI. Cualquier cosa, me escribes. ¡Gracias! 🙌",
)

# Entrega a domicilio: no tiene que ir a ninguna agencia.
LLEGADA_REPARTO = (
    "{saludo} Tu pedido ya está en reparto y va camino a tu dirección. "
    "Ten a la mano tu DNI para recibirlo. ¡Gracias por tu compra! 🙌",

    "¡{hola}! Buenas noticias: tu pedido ya salió a reparto y va rumbo a tu "
    "dirección. Solo necesitas tu DNI para recibirlo. ¡Gracias por la "
    "confianza! 💪",

    "{saludo} Te aviso que tu pedido ya está en reparto, va en camino a tu "
    "dirección. No te olvides de tener tu DNI a la mano. ¡Que lo disfrutes! 😋",

    "{hola}, ¿qué tal? 👋 Tu pedido ya va en camino a tu dirección, está en "
    "reparto. Ten tu DNI listo para recibirlo. ¡Gracias por tu compra! 🙌",
)


def variantes_de(estado):
    """Las versiones del aviso que valen para este estado del pedido."""
    return LLEGADA_REPARTO if estado == "En reparto" else LLEGADA_AGENCIA


def mensaje_cliente(destinatario, destino, ubigeo="", estado="En destino",
                    variante=0):
    """El aviso de llegada. `variante` elige cuál de las versiones sale; si se
    pasa de largo da la vuelta, así no revienta al quitar textos de la lista."""
    nombre = nombre_corto(destinatario)
    lugar = "la agencia Shalom"
    if (destino or "").strip():
        lugar += f" de {agencia(destino, ubigeo)}"

    plantillas = variantes_de(estado)
    return plantillas[variante % len(plantillas)].format(
        saludo=f"Hola {nombre} 👋" if nombre else "¡Hola! 👋",
        hola=f"Hola {nombre}" if nombre else "Hola",
        lugar=lugar,
    )


HUECO_CLAVE = "____"


def mensaje_registro(destinatario, orden, codigo, destino, ubigeo=""):
    """Mensaje para el cliente al enviar el paquete, con los datos de seguimiento.

    La clave la elige Aldahir al registrar el envío, así que el portal no la
    tiene: va como hueco para rellenar antes de enviar. Se deja al final para
    que sea lo último que se ve y no se escape sin completar.
    """
    nombre = nombre_corto(destinatario)
    saludo = f"Hola {nombre} 👋" if nombre else "¡Hola! 👋"
    return (
        f"{saludo} Ya envié tu pedido por Shalom, va en camino a "
        f"{agencia(destino, ubigeo)}.\n\n"
        f"Para hacerle seguimiento:\n"
        f"N° de orden: {orden}\n"
        f"Código: {codigo}\n"
        f"Clave: {HUECO_CLAVE}\n\n"
        f"Te aviso apenas llegue a la agencia. ¡Gracias por tu compra! 🙌"
    )


AYUDA = (
    "🤖 <b>Bot de avisos Shalom</b>\n\n"
    "Ya no hace falta que registres nada: leo tus envíos directamente de "
    "ShalomPRO. Apenas uno llegue a destino te mando aquí el mensaje y el link "
    "de WhatsApp listo para enviar. ✅\n\n"
    "Comandos: /listar"
)
