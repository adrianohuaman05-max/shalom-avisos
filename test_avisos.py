# -*- coding: utf-8 -*-
"""
Prueba del camino del aviso: parseo del panel -> mensaje -> link de WhatsApp.

Es la parte que no se puede validar en una corrida normal, porque solo se
ejecuta cuando un pedido llega a destino. No necesita credenciales ni red.

    python test_avisos.py

La ESTRUCTURA del panel es la del portal real (capturada del DOM), pero los
datos del destinatario —nombre, DNI, celular y número de orden— son inventados:
en un test no entran datos de clientes.
"""
import datetime as dt
import sys

import mensajes
import revisar
from shalompro import _parsear_drawer, normalizar_estado

fallos = []


def check(nombre, obtenido, esperado):
    if obtenido == esperado:
        print(f"OK    {nombre}")
        return
    print(f"FALLO {nombre}\n      esperado: {esperado!r}\n      obtenido: {obtenido!r}")
    fallos.append(nombre)


# Panel con el label y el valor en líneas separadas.
DRAWER_AGENCIA = """N° Orden: 12345678
Cód: 3TNH
30-07-2026 09:38h
Destinatario
Luis Ramirez
DNI:
00000000
CEL:
987654321
Forma de entrega
En agencia - Terrestre
Origen
Parcona
Ica / Ica / Parcona
Destino
Tingo Maria Co Buenos Aires
Huanuco / Leoncio Prado / Rupa Rupa
Detalle del paquete
1 Paqueteria Min
S/
10.00
Ver servicios adicionales"""

# El portal alterna: a veces label y valor van en la misma línea.
DRAWER_INLINE = """N° Orden: 87654321
Cód: NKMM
02-08-2026 10:07h
Destinatario
Ana
DNI: 11111111
CEL: 987654321
Forma de entrega
En agencia - Terrestre
Origen
Parcona
Ica / Ica / Parcona
Destino
Av. Carlos Izaguirre Cdra. 14
Lima / Lima / Los Olivos
Detalle del paquete
1 Paqueteria"""


print("\n=== Parseo del panel de detalle ===")
d = _parsear_drawer(DRAWER_AGENCIA)
check("orden", d["orden"], "12345678")
check("codigo", d["codigo"], "3TNH")
check("fecha", d["fecha"], "30-07-2026 09:38h")
check("destinatario", d["destinatario"], "Luis Ramirez")
check("dni", d["dni"], "00000000")
check("telefono", d["telefono"], "987654321")
check("forma_entrega", d["forma_entrega"], "En agencia - Terrestre")
check("origen", d["origen"], "Parcona")
check("destino", d["destino"], "Tingo Maria Co Buenos Aires")
check("ubigeo", d["destino_ubigeo"], "Huanuco / Leoncio Prado / Rupa Rupa")

print("\n=== Parseo con label y valor en la misma línea ===")
d2 = _parsear_drawer(DRAWER_INLINE)
check("orden", d2["orden"], "87654321")
check("dni", d2["dni"], "11111111")
check("telefono", d2["telefono"], "987654321")
check("destino", d2["destino"], "Av. Carlos Izaguirre Cdra. 14")

print("\n=== Estados (el portal los escribe sin tilde) ===")
check("En transito", normalizar_estado("En transito"), "En tránsito")
check("En destino", normalizar_estado("En destino"), "En destino")
check("En reparto", normalizar_estado("En reparto"), "En reparto")
check("En origen", normalizar_estado("En origen"), "En origen")

print("\n=== Nombre del cliente ===")
check("3+ palabras usa el ultimo", mensajes.nombre_corto("Ramirez Soto Ana Lucia"), "Lucia")
check("1 palabra", mensajes.nombre_corto("Ana"), "Ana")
check("vacío", mensajes.nombre_corto(""), "")

print("\n=== Agencia: el distrito solo si el destino es una calle ===")
check("calle + distrito",
      mensajes.agencia("Av. Carlos Izaguirre Cdra. 14", "Lima / Lima / Los Olivos"),
      "Av. Carlos Izaguirre Cdra. 14 (Los Olivos)")
check("pueblo sin distrito",
      mensajes.agencia("Tingo Maria Co Buenos Aires", "Huanuco / Leoncio Prado / Rupa Rupa"),
      "Tingo Maria Co Buenos Aires")
check("agencia de una palabra", mensajes.agencia("Chala", "Arequipa / Caraveli / Chala"), "Chala")
check("calle sin punto",
      mensajes.agencia("Av Bolívar", "Lima / Lima / Pueblo Libre"),
      "Av Bolívar (Pueblo Libre)")
check("destino vacío", mensajes.agencia("", "Lima / Lima / Lince"), "la agencia")

print("\n=== Teléfono para wa.me ===")
check("9 dígitos -> +51", mensajes.fmt_wa("987654321"), "51987654321")
check("ya trae 51", mensajes.fmt_wa("51987654321"), "51987654321")
check("con espacios", mensajes.fmt_wa("987 654 321"), "51987654321")

print("\n=== El aviso completo ===")
txt_ag = mensajes.mensaje_cliente(d["destinatario"], d["destino"], d["destino_ubigeo"], "En destino")
txt_rep = mensajes.mensaje_cliente(d["destinatario"], d["destino"], d["destino_ubigeo"], "En reparto")
link = mensajes.wa_link(d["telefono"], txt_ag)
print(f"  AGENCIA: {txt_ag}")
print(f"  REPARTO: {txt_rep}")
check("nombra el destino", "Tingo Maria" in txt_ag, True)
check("pide DNI", "DNI" in txt_ag, True)
check("no cuela el distrito", "Rupa Rupa" not in txt_ag, True)
check("reparto no manda a la agencia", "agencia" not in txt_rep.lower(), True)
check("reparto habla de dirección", "dirección" in txt_rep, True)
check("link al número correcto", link.startswith("https://wa.me/51987654321?text="), True)

print("\n=== Aviso de registro (el que sustituye a la foto del ticket) ===")
reg = mensajes.mensaje_registro(d["destinatario"], d["orden"], d["codigo"],
                                d["destino"], d["destino_ubigeo"])
print("  " + reg.replace("\n", "\n  "))
check("lleva el n° de orden", d["orden"] in reg, True)
check("lleva el código", "3TNH" in reg, True)
check("deja hueco para la clave", mensajes.HUECO_CLAVE in reg, True)
check("dice a dónde va", "Tingo Maria" in reg, True)
check("no promete que ya llegó", "listo para recoger" not in reg, True)
check("link wa.me correcto",
      mensajes.wa_link(d["telefono"], reg).startswith("https://wa.me/51987654321?"), True)

print("\n=== Demora: se cuenta desde la fecha real de envío ===")
def hace(dias):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=dias)).strftime("%d-%m-%Y")

check("10 días supera el umbral",
      revisar.dias_desde_envio({"fecha_envio": hace(10)}) > revisar.DEMORA_DIAS, True)
check("2 días no lo supera",
      revisar.dias_desde_envio({"fecha_envio": hace(2)}) > revisar.DEMORA_DIAS, False)
check("sin fecha no revienta", revisar.dias_desde_envio({}) >= 0, True)

print("\n=== Privacidad: nada de clientes en orders.json ===")
viejos = [{"orden": "1", "cliente": "Juan Perez", "telefono": "999888777",
           "destino": "Chala", "estado": "Entregado"}]
revisar.limpiar_datos_personales(viejos)
check("sin cliente", "cliente" not in viejos[0], True)
check("sin telefono", "telefono" not in viejos[0], True)
check("sin destino", "destino" not in viejos[0], True)
check("conserva la orden", viejos[0]["orden"], "1")

print("\n=== Cierre de los que salen del seguimiento ===")
orders = [{"orden": "A", "estado": "En tránsito"}, {"orden": "B", "estado": "En destino"}]
revisar.cerrar_desaparecidos(orders, vistos={"A"})
check("el visto sigue activo", orders[0].get("cerrado"), None)
check("el ausente se cierra", orders[1]["cerrado"], True)
check("y pasa a Entregado", orders[1]["estado"], "Entregado")

print("\n" + "=" * 55)
print(f"FALLOS: {len(fallos)}" + (f" -> {fallos}" if fallos else " (todo OK)"))
sys.exit(1 if fallos else 0)
