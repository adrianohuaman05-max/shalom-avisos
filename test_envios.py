# -*- coding: utf-8 -*-
"""
Pruebas del registro automático de envíos por Shalom (envios_shalom.py).

Sin red ni credenciales: Telegram, el registro (Apps Script) y Shalom Pro son
falsos. El falso del registro copia la regla de candado de accionShalomAnotar
(un 'ok' no se pisa; 'creando' se da una sola vez). Los datos de las personas
son inventados: en un test no entran datos de clientes.

    python test_envios.py
"""
import datetime as dt
import json
import sys

import envios_shalom as es

fallos = []


def check(nombre, obtenido, esperado):
    if obtenido == esperado:
        print(f"OK    {nombre}")
        return
    print(f"FALLO {nombre}\n      esperado: {esperado!r}\n      obtenido: {obtenido!r}")
    fallos.append(nombre)


# ── falsos ───────────────────────────────────────────────────────────

class TgFalso:
    CHAT_ID = "111"

    def __init__(self):
        self.mensajes, self.botones, self.ediciones, self.respuestas, self.docs = [], [], [], [], []
        self._n = 100

    def send_message(self, text, **k):
        self.mensajes.append(text)
        return {"ok": True}

    def send_buttons(self, text, teclado, **k):
        self._n += 1
        self.botones.append((self._n, text, teclado))
        return self._n

    def edit_buttons(self, message_id, teclado, **k):
        self.ediciones.append((message_id, teclado))

    def answer_callback(self, cid, text=""):
        self.respuestas.append(text)

    def send_document(self, *a, **k):
        self.docs.append(a)


class ApiFalsa:
    """El registro: envíos del día y el candado de shalomAnotar."""

    def __init__(self, envios):
        self._envios = envios
        self.registros = {}
        self.anotados = []

    def disponible(self):
        return True

    def envios(self, fecha):
        out = []
        for e in self._envios:
            if e["fecha"] != fecha:
                continue
            x = json.loads(json.dumps(e))
            x["registro"] = self.registros.get(e["id"])
            out.append(x)
        return out

    def anotar(self, id_envio, estado, **extra):
        self.anotados.append((id_envio, estado, extra))
        antes = self.registros.get(id_envio)
        if antes and antes["estado"] == "ok":
            return {"permitido": False, "registro": antes}
        if estado == "creando" and antes and antes["estado"] in ("creando", "incierto") and not extra.get("forzar"):
            return {"permitido": False, "registro": antes}
        nuevo = {"estado": estado}
        if estado == "ok":
            nuevo.update(orden=extra.get("orden"), codigo=extra.get("codigo"), caja=extra.get("caja"))
        self.registros[id_envio] = nuevo
        return {"permitido": True, "registro": nuevo}


class ErrorAntes(RuntimeError):
    antes_de_enviar = True


class ProFalso:
    def __init__(self, falla=None):
        self.creados = []
        self.falla = falla

    def crear_envio(self, datos):
        if self.falla:
            raise self.falla
        self.creados.append(datos)
        return {"orden": f"9000000{len(self.creados)}", "codigo": "AB1" + str(len(self.creados)), "precio": 18}

    def ticket_pdf(self, orden):
        return b"%PDF-falso"


def envio(id_envio="a1b2c3d4e5f6", fecha="2026-11-12", **cambios):
    e = {
        "id": id_envio, "fecha": fecha, "cliente": "Cliente Prueba",
        "pequenas": 200, "grandes": 0,
        "sabores": [{"sabor": "Chocochips", "cantidad": 150}, {"sabor": "Chocolate", "cantidad": 50}],
        "agencia": "MALL LAMBRAMANI", "agenciaId": "677", "destino": "MALL LAMBRAMANI · AREQUIPA",
        "recibe": {"nombre": "Persona Inventada", "dni": "00000000", "cel": "900000000"},
        "clave": "4821", "caja": "l", "cajaPorque": "por tu regla: de 200 a 300 galletas va en L",
        "faltan": [], "avisos": [],
    }
    e.update(cambios)
    return e


def reloj(hora, fecha="2026-11-12"):
    y, m, d = map(int, fecha.split("-"))
    return lambda: dt.datetime(y, m, d, hora, 5, tzinfo=es.LIMA)


def mundo(envios, hora=8, fecha="2026-11-12"):
    tg, api = TgFalso(), ApiFalsa(envios)
    return {}, es.Contexto(api=api, tg=tg, ahora=reloj(hora, fecha)), tg, api


def toque(data, chat="111"):
    return {"id": "cb", "data": data, "message": {"chat": {"id": chat}}}


# ── proponer ─────────────────────────────────────────────────────────

state, ctx, tg, api = mundo([envio()], hora=6)
check("de madrugada no se propone nada", es.proponer(state, ctx), 0)
state, ctx, tg, api = mundo([envio()], hora=22)
check("de noche tampoco", es.proponer(state, ctx), 0)

state, ctx, tg, api = mundo([envio(), envio("ffffffffffff", fecha="2026-11-13"), envio("eeeeeeeeeeee", fecha="2026-11-14")])
check("se proponen los envíos de hoy y de mañana (no los de pasado)", es.proponer(state, ctx), 2)
check("el de mañana dice mañana y avisa de las 24 h", ("Sale mañana" in tg.botones[1][1], "24 h" in tg.botones[1][1]), (True, True))
check("el de hoy no habla de las 24 h", ("Sale hoy" in tg.botones[0][1], "24 h" in tg.botones[0][1]), (True, False))
msg_id, texto, teclado = tg.botones[0]
check("la propuesta trae cliente, agencia, clave, caja y flete en destino",
      all(x in texto for x in ("Cliente Prueba", "MALL LAMBRAMANI", "4821", "Caja: <b>L</b>",
                               "lo paga el cliente en destino", "200 pequeñas (150 Chocochips, 50 Chocolate)")), True)
check("botones: ✅ ahora y ⏰ 8:00, las 6 cajas, y Hoy no",
      [len(f) for f in teclado], [2, 6, 1])
check("⏰ dice mañana si ya pasaron las 8", teclado[0][1]["text"], "⏰ Mañana 8:00")
check("la caja sugerida va marcada", [b["text"] for b in teclado[1]], ["Sobre", "XXS", "XS", "S", "M", "• L"])
check("ningún botón pasa los 64 bytes de Telegram",
      all(len(b["callback_data"].encode()) <= 64 for f in teclado for b in f), True)
guardado = json.dumps(state, ensure_ascii=False)
check("state.json (repo público) no guarda nombre, DNI, celular ni clave",
      any(x in guardado for x in ("Cliente Prueba", "Persona", "00000000", "900000000", "4821", "LAMBRAMANI")), False)
check("se recuerda el envío propuesto", state["envios"]["a1b2c3d4e5f6"], {"estado": "propuesto", "fecha": "2026-11-12", "caja": "l", "msg": msg_id})
_s, _c, _t, _a = mundo([envio()], hora=7)
es.proponer(_s, _c)
check("a las 7, ⏰ es de hoy", _t.botones[0][2][0][1]["text"], "⏰ Hoy 8:00")
check("la siguiente revisión no lo vuelve a proponer", es.proponer(state, ctx), 0)

# un pedido cargado a media mañana también sale
api._envios.append(envio("0123456789ab"))
check("un pedido nuevo de hoy se propone en la siguiente revisión", es.proponer(state, ctx), 1)

# ya registrado por otro lado
state, ctx, tg, api = mundo([envio()])
api.registros["a1b2c3d4e5f6"] = {"estado": "ok", "orden": "777"}
check("si el registro dice que ya está, no se propone", (es.proponer(state, ctx), state["envios"]["a1b2c3d4e5f6"]["estado"]), (0, "ok"))

# falta información
state, ctx, tg, api = mundo([envio(faltan=["falta el DNI de quien recoge: ponlo en Cotizar"])])
es.proponer(state, ctx)
check("si falta algo, avisa qué y no pone ✅", (len(tg.mensajes), len(tg.botones), "falta el DNI" in tg.mensajes[0]), (1, 0, True))
es.proponer(state, ctx)
check("el aviso de lo que falta sale una sola vez", len(tg.mensajes), 1)
api._envios[0]["faltan"] = []
check("corregido en Cotizar, en la siguiente revisión se propone", es.proponer(state, ctx), 1)

# ── botones ──────────────────────────────────────────────────────────

state, ctx, tg, api = mundo([envio()])
es.proponer(state, ctx)
local = state["envios"]["a1b2c3d4e5f6"]
es.atender_boton(toque("env:c:a1b2c3d4e5f6:m"), state, ctx)
check("cambiar la caja la guarda y redibuja los botones", (local["caja"], tg.ediciones[-1][1][0][0]["text"]), ("m", "✅ Registrar ahora · M"))
es.atender_boton(toque("env:c:a1b2c3d4e5f6:xl"), state, ctx)
check("una caja que no existe no se acepta", local["caja"], "m")
es.atender_boton(toque("env:ok:a1b2c3d4e5f6", chat="999"), state, ctx)
check("un toque desde otro chat no hace nada", local["estado"], "propuesto")
es.atender_boton(toque("env:ok:a1b2c3d4e5f6"), state, ctx)
check("✅ lo deja confirmado y quita los botones", (local["estado"], tg.ediciones[-1][1]), ("confirmado", []))
es.atender_boton(toque("env:ok:a1b2c3d4e5f6"), state, ctx)
check("un segundo ✅ no hace nada más", (local["estado"], tg.respuestas[-1]), ("confirmado", "Ya lo estoy registrando."))
es.atender_boton(toque("env:c:a1b2c3d4e5f6:s"), state, ctx)
check("ya confirmado, la caja no cambia", local["caja"], "m")
check("un botón de un envío olvidado avisa", (es.atender_boton(toque("env:ok:000000000000"), state, ctx), tg.respuestas[-1]),
      (True, "Ese envío ya no está pendiente."))
check("un botón que no es de envíos no se toca", es.atender_boton(toque("otra:cosa"), state, ctx), False)

# ── crear ────────────────────────────────────────────────────────────

pro = ProFalso()
orders = []
check("con ✅ se crea una vez", es.crear_confirmados(pro, state, ctx, orders), 1)
check("en Shalom con la caja elegida, flete en destino, DNI, celular y clave",
      pro.creados[0], {"agencia": "MALL LAMBRAMANI", "agencia_id": "677", "dni": "00000000", "nombre": "Persona Inventada",
                       "celular": "900000000", "caja": "m", "clave": "4821", "cantidad": 1, "flete": "destino"})
check("antes de crear pidió permiso; después anotó ok con lo que llevaba",
      [(a[1], a[2].get("caja"), a[2].get("pequenas")) for a in api.anotados], [("creando", None, None), ("ok", "m", 200)])
aviso = tg.mensajes[-1]
check("el aviso trae orden, código, clave y flete",
      all(x in aviso for x in ("90000001", "AB11", "Clave: <b>4821</b>", "Flete: S/18.00")), True)
check("pero no el mensaje ni el link al cliente (van al dejarlo en la agencia)",
      ["wa.me/" in aviso, "Mensaje:" in aviso], [False, False])
check("el ticket no va al crear (aún no existe: el paquete no se dejó)", len(tg.docs), 0)
check("y avisa que el ticket llega al dejarlo en la agencia", "te aviso de nuevo, con el ticket" in aviso, True)
check("la orden entra al seguimiento ya avisada (no se repite el 'pedido registrado')",
      (orders[0]["orden"], orders[0]["registro_avisado"], orders[0]["fecha_envio"]), ("90000001", True, "12-11-2026"))
check("y marcada como que todavía no sale en el portal", orders[0]["en_portal"], False)
check("la clave se recupera del registro por la orden", es.clave_de("90000001", state, ctx), "4821")
check("una orden que no creó el bot no tiene clave", es.clave_de("12345678", state, ctx), "")
check("ni la clave ni datos del cliente quedan en el seguimiento (repo público)",
      any(x in json.dumps(orders) for x in ("4821", "Persona", "900000000", "00000000")), False)
check("una segunda pasada no crea otra", (es.crear_confirmados(pro, state, ctx, orders), len(pro.creados)), (0, 1))
check("y queda ok en la memoria", (local["estado"], local["orden"]), ("ok", "90000001"))
es.atender_boton(toque("env:ok:a1b2c3d4e5f6"), state, ctx)
check("un ✅ viejo dice que ya está registrado", tg.respuestas[-1], "Ya está registrado (orden 90000001).")

# otra corrida (o el estado perdido) que vuelve a confirmar: el registro manda
state2, ctx2, tg2, _ = mundo([envio()])
ctx2.api = api
es.proponer(state2, ctx2)
check("con el registro en ok, ni se vuelve a proponer", len(tg2.botones), 0)
state2["envios"]["a1b2c3d4e5f6"] = {"estado": "confirmado", "fecha": "2026-11-12", "caja": "l"}
pro2 = ProFalso()
es.crear_confirmados(pro2, state2, ctx2, [])
check("aunque la memoria diga confirmado, si el registro ya tiene ok no se crea", len(pro2.creados), 0)

# ── fallos ───────────────────────────────────────────────────────────

state, ctx, tg, api = mundo([envio()])
es.proponer(state, ctx)
es.atender_boton(toque("env:ok:a1b2c3d4e5f6"), state, ctx)
es.crear_confirmados(ProFalso(falla=ErrorAntes("No encontré la agencia MALL LAMBRAMANI en Shalom")), state, ctx, [])
local = state["envios"]["a1b2c3d4e5f6"]
check("falló antes de enviar: vuelve a propuesto con botones nuevos",
      (local["estado"], "No se creó nada" in tg.botones[-1][1], local["msg"] == tg.botones[-1][0]), ("propuesto", True, True))
check("y queda anotado como error en el registro", api.registros["a1b2c3d4e5f6"]["estado"], "error")
es.atender_boton(toque("env:ok:a1b2c3d4e5f6"), state, ctx)
pro = ProFalso()
check("reintentar con ✅ funciona", (es.crear_confirmados(pro, state, ctx, []), len(pro.creados)), (1, 1))

state, ctx, tg, api = mundo([envio()])
es.proponer(state, ctx)
es.atender_boton(toque("env:ok:a1b2c3d4e5f6"), state, ctx)
es.crear_confirmados(ProFalso(falla=TimeoutError("se colgó al confirmar")), state, ctx, [])
local = state["envios"]["a1b2c3d4e5f6"]
check("falló después de enviar: incierto, con botón de reintento", (local["estado"], tg.botones[-1][2][0][0]["callback_data"]),
      ("incierto", "env:re:a1b2c3d4e5f6"))
pro = ProFalso()
es.crear_confirmados(pro, state, ctx, [])
check("incierto no se reintenta solo", len(pro.creados), 0)
es.atender_boton(toque("env:ok:a1b2c3d4e5f6"), state, ctx)
check("ni con un ✅ viejo", local["estado"], "incierto")
es.atender_boton(toque("env:re:a1b2c3d4e5f6"), state, ctx)
es.crear_confirmados(pro, state, ctx, [])
check("solo con 🔁 (Aldahir revisó que no está), forzando el candado",
      (len(pro.creados), [a[2].get("forzar") for a in api.anotados if a[1] == "creando"][-1]), (1, True))

state, ctx, tg, api = mundo([envio()])
state["envios"] = {"a1b2c3d4e5f6": {"estado": "creando", "fecha": "2026-11-12", "caja": "l"}}
es.revisar_atascados(state, ctx)
check("una corrida que se cayó dentro de Shalom deja el envío incierto",
      (state["envios"]["a1b2c3d4e5f6"]["estado"], api.registros["a1b2c3d4e5f6"]["estado"]), ("incierto", "incierto"))

state, ctx, tg, api = mundo([envio()])
es.proponer(state, ctx)
es.atender_boton(toque("env:no:a1b2c3d4e5f6"), state, ctx)
check("Hoy no: cancelado aquí y en el registro", (state["envios"]["a1b2c3d4e5f6"]["estado"], api.registros["a1b2c3d4e5f6"]["estado"]),
      ("cancelado", "cancelado"))
check("y no queda nada esperando", es.hay_por_confirmar(state, ctx), False)

# ── ⏰ mañana 8:00 ───────────────────────────────────────────────────

class Reloj:
    def __init__(self, cuando):
        self.cuando = cuando

    def __call__(self):
        return self.cuando


reloj_mov = Reloj(dt.datetime(2026, 11, 12, 18, 0, tzinfo=es.LIMA))
tg, api = TgFalso(), ApiFalsa([envio(fecha="2026-11-13")])
ctx = es.Contexto(api=api, tg=tg, ahora=reloj_mov)
state = {}
es.proponer(state, ctx)
es.atender_boton(toque("env:m:a1b2c3d4e5f6"), state, ctx)
local = state["envios"]["a1b2c3d4e5f6"]
check("⏰ lo deja programado para mañana a las 8", (local["estado"], local["para"][:16]), ("programado", "2026-11-13T08:00"))
check("y los botones pasan a adelantar o cancelar", [b["callback_data"][:6] for b in tg.ediciones[-1][1][0]], ["env:ok", "env:no"])
pro = ProFalso()
check("antes de las 8 no se crea", (es.crear_confirmados(pro, state, ctx, []), len(pro.creados)), (0, 0))
check("ni queda esperando un toque", es.hay_por_confirmar(state, ctx), False)
reloj_mov.cuando = dt.datetime(2026, 11, 13, 8, 2, tzinfo=es.LIMA)
check("a las 8 se crea solo, sin otro toque", (es.crear_confirmados(pro, state, ctx, []), local["estado"]), (1, "ok"))
check("una vez", es.crear_confirmados(pro, state, ctx, []), 0)

reloj_mov.cuando = dt.datetime(2026, 11, 12, 18, 0, tzinfo=es.LIMA)
tg, api = TgFalso(), ApiFalsa([envio(fecha="2026-11-13")])
ctx = es.Contexto(api=api, tg=tg, ahora=reloj_mov)
state = {}
es.proponer(state, ctx)
es.atender_boton(toque("env:m:a1b2c3d4e5f6"), state, ctx)
es.atender_boton(toque("env:ok:a1b2c3d4e5f6"), state, ctx)
pro = ProFalso()
check("programado, se puede adelantar a ahora", (es.crear_confirmados(pro, state, ctx, []), len(pro.creados)), (1, 1))
state = {}
tg, api = TgFalso(), ApiFalsa([envio(fecha="2026-11-13")])
ctx = es.Contexto(api=api, tg=tg, ahora=reloj_mov)
es.proponer(state, ctx)
es.atender_boton(toque("env:m:a1b2c3d4e5f6"), state, ctx)
es.atender_boton(toque("env:no:a1b2c3d4e5f6"), state, ctx)
reloj_mov.cuando = dt.datetime(2026, 11, 13, 9, 0, tzinfo=es.LIMA)
pro = ProFalso()
check("o cancelar: a las 8 ya no se crea", (state["envios"]["a1b2c3d4e5f6"]["estado"], es.crear_confirmados(pro, state, ctx, [])), ("cancelado", 0))
es.atender_boton(toque("env:m:a1b2c3d4e5f6"), state, ctx)
check("⏰ sobre uno cancelado no hace nada", state["envios"]["a1b2c3d4e5f6"]["estado"], "cancelado")

# ── el nombre, cuando Shalom no conoce el DNI ─────────────────────────
import shalompro_registro as spr
check("nombre y dos apellidos", spr.separar_nombre("Juan Carlos Quispe Mamani"), ("Juan Carlos", "Quispe", "Mamani"))
check("con menos de tres palabras no se adivina", spr.separar_nombre("Juan Quispe"), None)
check("un nombre con / adentro sale entero",
      spr.nombre_de_opcion("LIMA / LIMA / SAN JUAN DE MIRAFLORES / AV LOS PRECURSORES / LAS AMERICAS"),
      "AV LOS PRECURSORES / LAS AMERICAS")
check("la agencia se compara por su último tramo entero",
      [spr._norm(spr.nombre_de_opcion("AREQUIPA / AREQUIPA / AREQUIPA / MALL LAMBRAMANI - AEREO")) == spr._norm("MALL LAMBRAMANI"),
       spr._norm("LIMA / LIMA / SJL / CRUZ\xa0DE MOTUPE".split(" / ")[-1]) == spr._norm("CRUZ DE MOTUPE")], [False, True])

# ── memoria corta ────────────────────────────────────────────────────
state, ctx, tg, api = mundo([], fecha="2026-11-20")
state["envios"] = {"viejo0000000": {"estado": "ok", "fecha": "2026-11-12"}, "nuevo0000000": {"estado": "ok", "fecha": "2026-11-15"}}
es.olvidar_viejos(state, ctx)
check("lo de hace más de una semana se olvida", sorted(state["envios"]), ["nuevo0000000"])

print()
if fallos:
    print(f"{len(fallos)} prueba(s) fallaron.")
    sys.exit(1)
print("Todas las pruebas pasan.")
