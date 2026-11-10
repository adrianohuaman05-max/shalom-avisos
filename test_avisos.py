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

import envios_shalom
import mensajes
import revisar
import variantes
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

print("\n=== Versiones del aviso: todas dicen lo que hay que decir ===")
# La 0 es el mensaje de antes de que hubiera versiones. Tiene que seguir igual
# letra por letra: es la que se repite al reavisar pedidos antiguos.
check("la 0 de agencia es el mensaje de siempre", txt_ag,
      "Hola Luis 👋 Tu pedido ya llegó a la agencia Shalom de Tingo Maria Co "
      "Buenos Aires y está listo para recoger. Recuerda llevar tu DNI. "
      "¡Gracias por tu compra! 🙌")
check("la 0 de reparto es el mensaje de siempre", txt_rep,
      "Hola Luis 👋 Tu pedido ya está en reparto y va camino a tu dirección. "
      "Ten a la mano tu DNI para recibirlo. ¡Gracias por tu compra! 🙌")

for estado in ("En destino", "En reparto"):
    cuantas = len(mensajes.variantes_de(estado))
    textos = [mensajes.mensaje_cliente(d["destinatario"], d["destino"],
                                       d["destino_ubigeo"], estado, v)
              for v in range(cuantas)]
    anonimos = [mensajes.mensaje_cliente("", d["destino"], d["destino_ubigeo"],
                                         estado, v) for v in range(cuantas)]
    for t in textos:
        print(f"  {t}")
    check(f"{estado}: hay varias", cuantas > 1, True)
    check(f"{estado}: ninguna repetida", len(set(textos)), cuantas)
    check(f"{estado}: todas saludan por el nombre",
          all("Hola Luis" in t for t in textos), True)
    check(f"{estado}: todas piden DNI", all("DNI" in t for t in textos), True)
    check(f"{estado}: ninguna deja un hueco sin rellenar",
          any("{" in t or "}" in t for t in textos + anonimos), False)
    check(f"{estado}: sin nombre el saludo no queda cojo",
          any("Hola ," in t or "Hola !" in t or "  " in t for t in anonimos), False)
    if estado == "En destino":
        check("agencia: todas nombran el destino",
              all("la agencia Shalom de Tingo Maria Co Buenos Aires" in t
                  for t in textos), True)
        check("agencia: ninguna cuela el distrito",
              any("Rupa Rupa" in t for t in textos), False)
    else:
        check("reparto: ninguna manda a la agencia",
              any("agencia" in t.lower() for t in textos), False)
        check("reparto: todas hablan de la dirección",
              all("dirección" in t for t in textos), True)

check("pasarse de largo da la vuelta",
      mensajes.mensaje_cliente("Ana", "Chala", "", "En destino",
                               len(mensajes.LLEGADA_AGENCIA)),
      mensajes.mensaje_cliente("Ana", "Chala", "", "En destino", 0))
check("sin destino no dice 'de la agencia'",
      "la agencia Shalom y está" in mensajes.mensaje_cliente("Ana", "", ""), True)

print("\n=== A un cliente que vuelve no le toca la misma versión ===")
N = len(mensajes.LLEGADA_AGENCIA)
mem = variantes.Memoria("", persistente=True)
turnos = [mem.elegir("987654321", str(5000 + i), N) for i in range(N)]
check("en N pedidos recibe las N versiones", sorted(turnos), list(range(N)))
check("el pedido N+1 no repite el anterior",
      mem.elegir("987654321", "6000", N) != turnos[-1], True)
ultimo = mem.datos[variantes.id_cliente("987654321")]
check("el mismo celular escrito con 51 es el mismo cliente",
      mem.elegir("51987654321", "6001", N), (ultimo + 1) % N)
check("y con espacios también",
      mem.elegir("987 654 321", "6002", N), (ultimo + 2) % N)
nuevo = variantes.id_cliente("911111111")
check("un cliente nuevo parte de su pedido y de quién es",
      mem.elegir("911111111", "7000", N), variantes.por_orden(f"7000/{nuevo}", N))
check("con el mismo número de orden, otro cliente nuevo no saca siempre la misma",
      len({variantes.Memoria("", persistente=True).elegir(str(900000000 + i), "7000", N)
           for i in range(40)}) > 1, True)
check("que no altera el turno del otro",
      mem.elegir("987654321", "6003", N), (ultimo + 3) % N)
check("reparto tiene menos versiones y no se sale",
      mem.elegir("987654321", "6004", len(mensajes.LLEGADA_REPARTO))
      < len(mensajes.LLEGADA_REPARTO), True)

guardado = json.dumps(mem.datos)
check("la memoria no lleva el celular",
      "987654321" in guardado or "911111111" in guardado, False)
otra_corrida = variantes.Memoria(guardado, persistente=True)
sigue = mem.datos[variantes.id_cliente("911111111")]
check("la corrida siguiente retoma donde quedó",
      otra_corrida.elegir("911111111", "7001", N), (sigue + 1) % N)

sin_donde = variantes.Memoria("", persistente=False)
check("sin dónde guardar: sale del número de orden",
      [sin_donde.elegir("987654321", o, N) for o in ("1", "2", "3")],
      [variantes.por_orden(o, N) for o in ("1", "2", "3")])
check("y no anota nada", (sin_donde.datos, sin_donde.cambiada), ({}, False))
check("sin celular tampoco anota",
      (variantes.Memoria("", persistente=True).elegir("", "9", N),
       variantes.id_cliente("")), (variantes.por_orden("9", N), ""))
check("un secret estropeado no revienta",
      variantes.Memoria("{esto no es json", persistente=True).datos, {})
check("ni uno con otra forma",
      variantes.Memoria("[1, 2]", persistente=True).datos, {})

tope = variantes.MAX_CLIENTES
variantes.MAX_CLIENTES = 3
llena = variantes.Memoria("", persistente=True)
for i in range(5):
    llena.elegir(f"90000000{i}", "1", N)
variantes.MAX_CLIENTES = tope
check("con la memoria llena salen los más antiguos", list(llena.datos),
      [variantes.id_cliente(f"90000000{i}") for i in (2, 3, 4)])

print("\n=== La memoria se guarda en el secret, no en el repo ===")
subidas = []
guardar_real = variantes.renovacion.guardar_secret
variantes.renovacion.guardar_secret = lambda n, v: subidas.append((n, v)) or True
check("sin cambios no se sube nada",
      (variantes.Memoria("", persistente=True).guardar(), subidas), (True, []))
mem.guardar()
check("con cambios se sube una vez, al secret AVISOS_VARIANTES",
      [n for n, _ in subidas], ["AVISOS_VARIANTES"])
check("lo subido es la memoria", json.loads(subidas[0][1]), mem.datos)
mem.guardar()
check("y no se vuelve a subir si no cambió", len(subidas), 1)
variantes.renovacion.guardar_secret = lambda n, v: False
mem.elegir("987654321", "6005", N)
check("si GitHub no lo acepta, lo dice", mem.guardar(), False)
check("y queda pendiente", mem.cambiada, True)
variantes.renovacion.guardar_secret = guardar_real

print("\n=== El aviso usa la versión que toca ===")
class PortalFalso:
    """Devuelve siempre el mismo destinatario: un cliente que vuelve."""
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def listar(self):
        return [{"orden": "111", "estado": "En destino"},
                {"orden": "222", "estado": "En reparto"},
                {"orden": "333", "estado": "En tránsito"}]
    def detalle(self, orden):
        return dict(d, orden=orden)

enviados_tg = []
enviar_real = revisar.tg.send_message
revisar.tg.send_message = lambda texto, **kw: enviados_tg.append(texto)

def texto_de(variante, estado="En destino"):
    return mensajes.mensaje_cliente(d["destinatario"], d["destino"],
                                    d["destino_ubigeo"], estado, variante)

mem2 = variantes.Memoria("", persistente=True)
p1, p2 = {"orden": "8001"}, {"orden": "8002"}
revisar.avisar_llegada(PortalFalso(), p1, "En destino", mem2)
revisar.avisar_llegada(PortalFalso(), p2, "En destino", mem2)
check("el pedido anota su versión", p1["variante"],
      variantes.por_orden(f"8001/{variantes.id_cliente(d['telefono'])}", N))
check("el segundo pedido del cliente lleva otra", p2["variante"], (p1["variante"] + 1) % N)
check("y es el texto que sale a Telegram",
      (texto_de(p1["variante"]) in enviados_tg[0],
       texto_de(p2["variante"]) in enviados_tg[1]), (True, True))
check("con su link de WhatsApp",
      mensajes.wa_link(d["telefono"], texto_de(p2["variante"])) in enviados_tg[1], True)

antes = dict(mem2.datos)
del enviados_tg[:]
revisar.avisar_llegada(PortalFalso(), dict(p1), "En destino", mem2)
check("reavisar repite el mismo texto", texto_de(p1["variante"]) in enviados_tg[0], True)
check("y no le gasta el turno al cliente", mem2.datos, antes)

sin_memoria = {"orden": "8003"}
revisar.avisar_llegada(PortalFalso(), sin_memoria, "En destino")
check("sin memoria sale del número de orden",
      sin_memoria["variante"], variantes.por_orden("8003", N))

# --reavisar entero: el pedido con versión anotada la repite; el de antes de
# que hubiera versiones (sin anotar) recibe el mensaje de siempre.
del enviados_tg[:]
portal_real, cargar_real = revisar.ShalomPro, revisar.storage.load_orders
revisar.ShalomPro = lambda headless=True: PortalFalso()
revisar.storage.load_orders = lambda: [{"orden": "111", "variante": 3},
                                       {"orden": "222"}]
check("--reavisar manda los dos que ya llegaron",
      (revisar.reavisar(["111", "222", "333"]), len(enviados_tg)), (0, 2))
check("el anotado repite su versión", texto_de(3) in enviados_tg[0], True)
check("el antiguo recibe la de siempre",
      texto_de(0, "En reparto") in enviados_tg[1], True)
revisar.ShalomPro, revisar.storage.load_orders = portal_real, cargar_real

print("\n=== Aviso de que Shalom ya recibió la caja ===")
# Un envío registrado por internet sale "En origen" con la caja aún en casa.
# El aviso para decirle al cliente "ya envié" tiene que esperar a que Shalom
# la tenga, y eso se ve cuando el portal lo pasa a "En tránsito".
class RegistroFalso:
    """El registro del taller: devuelve el envío del panel con su clave."""
    def __init__(self, envios, vivo=True):
        self._envios, self.vivo = envios, vivo
    def disponible(self):
        return True
    def envios(self, fecha):
        if not self.vivo:
            raise RuntimeError("caído")
        return [e for e in self._envios if e["fecha"] == fecha]

DEL_PANEL = {"id": "abc123abc123", "fecha": "2026-11-12", "cliente": "Apodo <Panel>",
             "agencia": "CHALA", "destino": "CHALA · AREQUIPA", "clave": "4821",
             "recibe": {"nombre": "Persona Inventada", "cel": "900000000"}}
ESTADO_BOT = {"envios": {"abc123abc123": {"estado": "ok", "fecha": "2026-11-12",
                                          "orden": "5001"}}}
ctx_real = revisar._ctx
revisar._ctx = envios_shalom.Contexto(api=RegistroFalso([DEL_PANEL]))

del enviados_tg[:]
check("un envío del panel se avisa",
      revisar.avisar_entrega(PortalFalso(), {"orden": "5001", "codigo": "K9W7"}, ESTADO_BOT), True)
txt_panel = envios_shalom.mensaje_para_cliente(DEL_PANEL, "5001", "K9W7")
check("con el nombre que tiene en el panel, la orden y el destino",
      all(x in enviados_tg[0] for x in ("Shalom ya recibió", "Apodo &lt;Panel&gt;",
                                        "5001", "K9W7", "CHALA · AREQUIPA")), True)
check("el mensaje lleva la clave puesta, sin hueco",
      ("Clave: 4821" in txt_panel, mensajes.HUECO_CLAVE in enviados_tg[0],
       "Completa la clave" in enviados_tg[0]), (True, False, False))
check("y el link va al celular del panel con ese mismo mensaje",
      mensajes.wa_link("900000000", txt_panel) in enviados_tg[0], True)

del enviados_tg[:]
check("uno registrado a mano se avisa con lo que diga el portal",
      revisar.avisar_entrega(PortalFalso(), {"orden": "5002", "codigo": "ZZ99"}, ESTADO_BOT), True)
check("con la clave en blanco y el recordatorio de completarla",
      (mensajes.HUECO_CLAVE in enviados_tg[0], "Completa la clave" in enviados_tg[0],
       "wa.me/51987654321" in enviados_tg[0]), (True, True, True))

del enviados_tg[:]
revisar._ctx = envios_shalom.Contexto(api=RegistroFalso([DEL_PANEL], vivo=False))
check("si el registro del taller no contesta, sale igual por el portal",
      (revisar.avisar_entrega(PortalFalso(), {"orden": "5001", "codigo": "K9W7"}, ESTADO_BOT),
       mensajes.HUECO_CLAVE in enviados_tg[0]), (True, True))

class PortalSinDetalle(PortalFalso):
    def detalle(self, orden):
        return None
del enviados_tg[:]
check("sin detalle no avisa y queda para la próxima corrida",
      (revisar.avisar_entrega(PortalSinDetalle(), {"orden": "5002"}, ESTADO_BOT), enviados_tg),
      (False, []))
revisar._ctx = ctx_real

print("\n=== El aviso sale una vez, al pasar de 'En origen' a 'En tránsito' ===")
class PortalCon(PortalFalso):
    """El seguimiento del portal con los estados que se le digan."""
    uso_formulario = False
    def __init__(self, estados):
        self.estados = estados
    def listar(self):
        return [{"orden": o, "codigo": "C" + o, "estado": e, "fecha": "12-11-2026"}
                for o, e in self.estados.items()]
    def ticket_pdf(self, orden):
        return None

disco = {"orders": [], "state": {"telegram_offset": 0}}
reales = (revisar.storage.load_orders, revisar.storage.load_state,
          revisar.storage.save_orders, revisar.storage.save_state,
          revisar.tg.get_updates, revisar.renovar_sesion_si_toca, sys.argv)
revisar.storage.load_orders = lambda: json.loads(json.dumps(disco["orders"]))
revisar.storage.load_state = lambda: json.loads(json.dumps(disco["state"]))
revisar.storage.save_orders = lambda o: disco.__setitem__("orders", o)
revisar.storage.save_state = lambda s: disco.__setitem__("state", s)
revisar.tg.get_updates = lambda **kw: []
revisar.renovar_sesion_si_toca = lambda pro, state: None
sys.argv = ["revisar.py"]

def corrida(estados):
    """Una revisión entera. Devuelve los títulos de lo que llegó a Telegram."""
    del enviados_tg[:]
    revisar.ShalomPro = lambda headless=True: PortalCon(estados)
    revisar._revisar()
    return [m.split("\n")[0] for m in enviados_tg]

def pedido_de(orden):
    return next(o for o in disco["orders"] if o["orden"] == orden)

RECIBIDO = "🚚 <b>Shalom ya recibió el envío</b>"
LLEGO = "🎉 <b>¡Pedido listo para recoger!</b>"

# "A" lo creó el bot desde el panel (así lo apunta envios_shalom); "V" es de
# antes de este aviso y ya iba en camino: no trae el campo.
envios_shalom._apuntar_en_seguimiento(disco["orders"], {"orden": "A", "codigo": "CA"}, "2026-11-12")
disco["orders"].append({"orden": "V", "codigo": "CV", "estado": "En tránsito",
                        "avisado": False, "registro_avisado": True, "cerrado": False,
                        "demora_avisada": True, "fecha_envio": "12-11-2026"})

check("registrado pero aún en casa: no avisa nada",
      corrida({"A": "En origen", "V": "En tránsito"}), [])
check("y sigue pendiente", pedido_de("A")["entrega_avisada"], False)
check("Shalom lo recibe: avisa", corrida({"A": "En tránsito", "V": "En tránsito"}), [RECIBIDO])
check("queda anotado", pedido_de("A")["entrega_avisada"], True)
check("en la corrida siguiente no repite", corrida({"A": "En tránsito", "V": "En tránsito"}), [])
check("uno que ya iba en camino antes de este aviso no recibe nada a destiempo",
      "entrega_avisada" in pedido_de("V"), False)
check("al llegar sale el aviso de llegada de siempre, y solo ese",
      corrida({"A": "En destino", "V": "En tránsito"}), [LLEGO])

# Recién creado, a veces no sale en el seguimiento y el bot lo da por cerrado.
envios_shalom._apuntar_en_seguimiento(disco["orders"], {"orden": "B", "codigo": "CB"}, "2026-11-12")
corrida({"V": "En tránsito"})
check("uno recién creado que aún no sale en el portal sigue pendiente",
      (pedido_de("B")["cerrado"], pedido_de("B")["entrega_avisada"]), (True, False))
check("si reaparece ya en tránsito (se dejó la caja en seguida), avisa",
      corrida({"B": "En tránsito", "V": "En tránsito"}), [RECIBIDO])

check("uno registrado a mano por internet: primero el aviso de registro",
      corrida({"C": "En origen", "V": "En tránsito"}), ["📦 <b>Pedido registrado</b>"])
check("y al recibirlo Shalom, el aviso nuevo", corrida({"C": "En tránsito"}), [RECIBIDO])

check("uno dejado en el mostrador se descubre ya en tránsito: solo el de registro",
      corrida({"D": "En tránsito"}), ["📦 <b>Pedido registrado</b>"])
check("y no queda nada pendiente", pedido_de("D")["entrega_avisada"], True)
check("ni vuelve a avisar", corrida({"D": "En tránsito"}), [])

# De antes de este aviso, pero todavía en casa: el bot lo ve "En origen".
disco["orders"].append({"orden": "E", "codigo": "CE", "estado": "En origen",
                        "avisado": False, "registro_avisado": True, "cerrado": False,
                        "demora_avisada": False, "fecha_envio": "12-11-2026"})
corrida({"E": "En origen"})
check("uno antiguo que sigue en casa también se avisa cuando Shalom lo recibe",
      corrida({"E": "En tránsito"}), [RECIBIDO])

envios_shalom._apuntar_en_seguimiento(disco["orders"], {"orden": "F", "codigo": "CF"}, "2026-11-12")
check("si llega sin que se le viera en camino, basta el aviso de llegada",
      (corrida({"F": "En destino"}), pedido_de("F")["entrega_avisada"]), ([LLEGO], True))

envios_shalom._apuntar_en_seguimiento(disco["orders"], {"orden": "G", "codigo": "CG"}, "2026-11-12")
sys.argv = ["revisar.py", "--sin-avisos"]
check("--sin-avisos no manda este aviso", corrida({"G": "En tránsito"}), [])
sys.argv = ["revisar.py"]

check("nada de esto deja datos del cliente en disco",
      any(x in json.dumps(disco, ensure_ascii=False)
          for x in (d["destinatario"], d["telefono"], d["dni"])), False)

(revisar.storage.load_orders, revisar.storage.load_state,
 revisar.storage.save_orders, revisar.storage.save_state,
 revisar.tg.get_updates, revisar.renovar_sesion_si_toca, sys.argv) = reales
revisar.ShalomPro = portal_real
revisar.tg.send_message = enviar_real

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

print("\n=== Las horas caidas salen del cron de verdad ===")
# Antes multiplicaba por 2 h cuando el cron sale cada 30 min: 23 fallos se
# anunciaban como "46 horas" en vez de las ~12 reales.
check("30 min por corrida", revisar.MINUTOS_ENTRE_CORRIDAS, 30)
check("23 fallos son ~12 h",
      round(23 * revisar.MINUTOS_ENTRE_CORRIDAS / 60), 12)

print("\n" + "=" * 55)
print(f"FALLOS: {len(fallos)}" + (f" -> {fallos}" if fallos else " (todo OK)"))
sys.exit(1 if fallos else 0)
