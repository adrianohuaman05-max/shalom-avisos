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
import json
import sys

import mensajes
import revisar
from shalompro import _parsear_drawer, clasificar_fallo_login, normalizar_estado

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

print("\n=== Órdenes que creó el bot y aún no se dejaron en la agencia ===")
def hace_horas(h):
    return (revisar.now() - dt.timedelta(hours=h)).isoformat()

orders = [{"orden": "C", "estado": "En origen", "en_portal": False, "registrado": hace_horas(1)},
          {"orden": "D", "estado": "En origen", "en_portal": False, "registrado": hace_horas(8 * 24)}]
revisar.cerrar_desaparecidos(orders, vistos=set())
check("recién creada y sin aparecer: no se da por entregada", (orders[0].get("cerrado"), orders[0]["estado"]), (None, "En origen"))
check("si en una semana no aparece, se cierra igual", orders[1]["cerrado"], True)


class ProFalso:
    def __init__(self, detalle=True):
        self._detalle = detalle
        self.tickets = []

    def detalle(self, orden):
        if not self._detalle:
            return None
        return {"destinatario": "Rojas Diaz Ana", "orden": orden, "codigo": "K9W7",
                "destino": "Mall Lambramani", "telefono": "900000000"}

    def ticket_pdf(self, orden):
        self.tickets.append(orden)
        return b"%PDF-falso"


enviados, docs = [], []
_send, _doc, _clave = revisar.tg.send_message, revisar.tg.send_document, revisar.envios_shalom.clave_de
revisar.tg.send_message = lambda texto, **k: enviados.append(texto)
revisar.tg.send_document = lambda *a, **k: docs.append(a)
claves = {"103348163": "4821"}
revisar.envios_shalom.clave_de = lambda orden, state, ctx: claves.get(orden, "")
revisar._ctx = object()   # no hace falta el registro de verdad
try:
    pro = ProFalso()
    p = {"orden": "103348163", "codigo": "K9W7", "estado": "En origen", "en_portal": False}
    revisar.atender_recien_dejado(pro, p, {})
    check("al aparecer en el portal avisa 'Ya está en Shalom'", "Ya está en Shalom" in enviados[-1], True)
    check("con la clave del registro puesta en el mensaje al cliente",
          ["Clave: 4821" in enviados[-1], "Completa la clave" in enviados[-1]], [True, False])
    check("con link de WhatsApp al cliente", "wa.me/51900000000" in enviados[-1], True)
    check("y manda el ticket", (pro.tickets, len(docs)), (["103348163"], 1))
    check("queda como visto en el portal", p["en_portal"], True)
    revisar.atender_recien_dejado(pro, p, {})
    check("no se repite en la corrida siguiente", (len(enviados), len(docs)), (1, 1))

    p2 = {"orden": "103359713", "estado": "En origen", "en_portal": False}
    revisar.atender_recien_dejado(ProFalso(), p2, {})
    check("sin clave en el registro, pide completarla", "Completa la clave" in enviados[-1], True)

    p3 = {"orden": "1", "estado": "En origen", "en_portal": False}
    revisar.atender_recien_dejado(ProFalso(detalle=False), p3, {})
    check("si el detalle no carga, se reintenta luego", (p3["en_portal"], len(enviados)), (False, 2))

    p4 = {"orden": "2", "estado": "En destino", "en_portal": False}
    revisar.atender_recien_dejado(ProFalso(), p4, {})
    check("si aparece ya en destino, el aviso de llegada lo cubre", (p4["en_portal"], len(enviados)), (True, 2))

    viejo = {"orden": "3", "estado": "En origen", "registro_avisado": True}
    revisar.atender_recien_dejado(ProFalso(), viejo, {})
    check("los pedidos de antes (sin el campo) no se tocan", ("en_portal" in viejo, len(enviados)), (False, 2))

    nombre_raro = ProFalso()
    nombre_raro.detalle = lambda orden: {"destinatario": "Tienda <Fit> & Co", "codigo": "X",
                                          "destino": "Chala", "telefono": "900000000"}
    revisar.atender_recien_dejado(nombre_raro, {"orden": "4", "estado": "En origen", "en_portal": False}, {})
    check("un nombre con < o & no rompe el HTML de Telegram",
          "Tienda &lt;Fit&gt; &amp; Co" in enviados[-1], True)
finally:
    revisar.tg.send_message, revisar.tg.send_document = _send, _doc
    revisar.envios_shalom.clave_de = _clave
    revisar._ctx = None

print("\n=== Por que no dejo entrar el portal ===")
# El texto real que devolvio el portal en la caida de agosto de 2026. Que se
# reconozca es lo que separa "renueva la sesion" de "revisa tu contrasena": los
# dos fallos se veian igual y mandaban a mirar donde no era.
PANTALLA_RECAPTCHA = (
    "Iniciar sesión Ingresa tus datos para registrar tus envíos online. "
    "Verificación de seguridad fallida. Intenta de nuevo. Recuérdame "
    "Olvidé mi contraseña Iniciar sesión")
check("reconoce el rechazo de reCAPTCHA",
      clasificar_fallo_login(PANTALLA_RECAPTCHA), "recaptcha")
check("y no lo confunde con la clave",
      clasificar_fallo_login("Credenciales incorrectas"), "credenciales")
check("cuenta bloqueada",
      clasificar_fallo_login("Su cuenta ha sido bloqueada"), "bloqueada")
check("el formulario limpio no dice nada",
      clasificar_fallo_login("Iniciar sesión Recuérdame"), "desconocido")

print("\n=== Cada fallo lleva su instruccion ===")
for motivo in ("recaptcha", "credenciales", "bloqueada", "sin_credenciales"):
    err = type("E", (Exception,), {})()
    err.motivo, err.pista = motivo, ""
    check(f"hay arreglo para '{motivo}'", bool(revisar.arreglo_de(err)), True)
sin_motivo = RuntimeError("algo raro")
check("un error cualquiera no inventa arreglo", revisar.arreglo_de(sin_motivo), "")

print("\n=== Cambio de bot de Telegram ===")
_token = revisar.tg.TOKEN
try:
    revisar.tg.TOKEN = "111111:viejo"
    st = {"telegram_offset": 841229816}
    check("la primera vez solo anota el bot, sin tocar el offset",
          (revisar.revisar_cambio_de_bot(st), st["telegram_offset"], bool(st.get("telegram_bot"))), (False, 841229816, True))
    check("el mismo bot otra vez no cambia nada", (revisar.revisar_cambio_de_bot(st), st["telegram_offset"]), (False, 841229816))
    revisar.tg.TOKEN = "222222:nuevo"
    check("con otro bot el offset vuelve a 0", (revisar.revisar_cambio_de_bot(st), st["telegram_offset"]), (True, 0))
    check("la huella no deja ver el token ni el id del bot",
          any(x in json.dumps(st) for x in ("222222", "nuevo")), False)
    revisar.tg.TOKEN = ""
    check("sin token no toca nada", revisar.revisar_cambio_de_bot(st), False)
finally:
    revisar.tg.TOKEN = _token

print("\n=== Las horas caidas salen del cron de verdad ===")
# Antes multiplicaba por 2 h cuando el cron sale cada 30 min: 23 fallos se
# anunciaban como "46 horas" en vez de las ~12 reales.
check("30 min por corrida", revisar.MINUTOS_ENTRE_CORRIDAS, 30)
check("23 fallos son ~12 h",
      round(23 * revisar.MINUTOS_ENTRE_CORRIDAS / 60), 12)

print("\n" + "=" * 55)
print(f"FALLOS: {len(fallos)}" + (f" -> {fallos}" if fallos else " (todo OK)"))
sys.exit(1 if fallos else 0)
