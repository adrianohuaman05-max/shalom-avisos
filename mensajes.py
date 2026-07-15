# -*- coding: utf-8 -*-
"""Generación del mensaje corto al cliente, link wa.me, y parseo de registros."""
import re
import urllib.parse


def fmt_wa(phone):
    d = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(d) == 9:            # celular peruano local -> agregar código país
        d = "51" + d
    return d


def mensaje_cliente(cliente, destino):
    nombre = cliente.split()[0].capitalize() if cliente else "Hola"
    return (
        f"Hola {nombre} 👋 Tu pedido ya llegó a la agencia Shalom de "
        f"{destino} y está listo para recoger. Recuerda llevar tu DNI. "
        f"¡Gracias por tu compra! 🙌"
    )


def wa_link(phone, texto):
    return f"https://wa.me/{fmt_wa(phone)}?text={urllib.parse.quote(texto)}"


# --- Parseo de un nuevo pedido enviado por Telegram ---------------------------
LABELS = {
    "orden": ["orden", "nro", "n orden", "n de orden", "numero"],
    "codigo": ["codigo", "código", "cod"],
    "cliente": ["cliente", "nombre"],
    "telefono": ["telefono", "teléfono", "whatsapp", "wsp", "cel", "celular"],
    "destino": ["destino", "agencia"],
}


def _by_labels(text):
    out = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip().lower()
        v = v.strip()
        for field, aliases in LABELS.items():
            if k in aliases:
                out[field] = v
    return out


def _heuristic(text):
    """Detecta orden (8 dígitos), código (alfanumérico con letra), teléfono (9 díg)."""
    out = {}
    tokens = text.replace(",", " ").split()
    for t in tokens:
        if re.fullmatch(r"\d{8}", t) and "orden" not in out:
            out["orden"] = t
        elif re.fullmatch(r"9\d{8}", t) and "telefono" not in out:
            out["telefono"] = t
        elif re.fullmatch(r"[A-Za-z0-9]{3,6}", t) and re.search(r"[A-Za-z]", t) and "codigo" not in out:
            out["codigo"] = t.upper()
    return out


def parse_pedido(text):
    """
    Devuelve dict con orden, codigo, cliente, telefono, destino (los que encuentre).
    Acepta formato con etiquetas (Orden: 123...) o libre.
    """
    data = _heuristic(text)
    data.update(_by_labels(text))  # las etiquetas tienen prioridad
    # normalizar
    if "orden" in data:
        data["orden"] = "".join(ch for ch in data["orden"] if ch.isdigit())
    if "codigo" in data:
        data["codigo"] = data["codigo"].strip().upper()
    return data


AYUDA = (
    "🤖 <b>Bot de avisos Shalom</b>\n\n"
    "Para registrar un pedido, mándame los datos así (puedes copiar y editar):\n\n"
    "<code>Orden: 87137991\n"
    "Codigo: 9DCJ\n"
    "Cliente: Brenda Gonzales\n"
    "Telefono: 982302017\n"
    "Destino: Chala</code>\n\n"
    "Yo reviso Shalom solo y, cuando el pedido llegue a destino, te aviso aquí "
    "con el mensaje y el link de WhatsApp listo para enviar. ✅"
)
