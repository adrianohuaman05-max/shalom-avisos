# -*- coding: utf-8 -*-
"""
Envíos por Shalom que se registran solos, con ✅ de Aldahir.

El flujo, de punta a punta:

  1. Aldahir carga el pedido en el panel con su fecha. Si el cliente tiene
     guardado en Cotizar "envío por Shalom" (agencia de la lista, DNI de
     quien recoge), ese pedido sale por Shalom ese día.
  2. La revisión de cada media hora (de 7:00 a 22:00 de Lima) pregunta al
     registro qué sale hoy y mañana, y manda a Telegram un resumen por envío
     con la caja sugerida (se cambia con un toque) y dos botones:
       ✅ Registrar ahora   para lo que sale hoy (a las 4 o 6 de la tarde)
       ⏰ Mañana 8:00        queda aprobado y se registra solo a las 8:00
  3. Solo con uno de esos dos toques se crea la orden en pro.shalom.pe. Al
     terminar llega el número de orden, el código, la clave y el mensaje
     para el cliente.
  4. Después el seguimiento de siempre (revisar.py) avisa cuando llega.

Nunca dos veces el mismo pedido: antes de tocar Shalom se pide permiso al
registro ('creando'), que lo da una sola vez. Si una corrida se cae a la
mitad, el envío queda 'incierto' y NO se reintenta solo: Aldahir revisa en
Shalom y, si no está, lo pide de nuevo con 🔁.

Flete: siempre pagado en destino (decisión de Aldahir).

PRIVACIDAD: state.json va al repo público. Aquí solo se guarda el id opaco
del envío (un hash; no lleva el nombre), su estado, la caja elegida y el id
del mensaje de Telegram. Nombre, DNI y celular se piden al registro en el
momento, viajan a Telegram y no se escriben nunca a disco ni a los logs.
"""
import datetime as dt
import html

import mensajes
import registro_api as api_registro
import telegram_bot as tg_real

LIMA = dt.timezone(dt.timedelta(hours=-5))      # Perú no cambia de hora
HORA_DESDE, HORA_HASTA = 7, 22                  # se proponen envíos en este horario de Lima
HORA_PROGRAMADA = 8                             # "⏰ Mañana 8:00" se registra a esta hora
DIAS_QUE_SE_RECUERDA = 7

CAJAS = ["sobre", "xxs", "xs", "s", "m", "l"]
NOMBRE_CAJA = {"sobre": "Sobre", "xxs": "XXS", "xs": "XS", "s": "S", "m": "M", "l": "L"}

# Estados locales (state.json → "envios"):
#   falta       no se puede registrar (sin DNI, agencia fuera de la lista...)
#   propuesto   mandado a Telegram, esperando ✅
#   programado  tocó ⏰: aprobado; se registra solo a las 8:00 ("para")
#   confirmado  tocó ✅ (o llegó la hora del ⏰): se crea en seguida
#   creando     dentro de Shalom ahora mismo. Si una corrida empieza y lo
#               encuentra así, la anterior se cayó a la mitad → incierto
#   incierto    no se sabe si quedó creado: espera a que Aldahir revise
#   ok          registrado
#   cancelado   tocó "Hoy no"


class Contexto:
    """Lo que el flujo necesita del mundo. En las pruebas se cambia por falsos."""

    def __init__(self, api=None, tg=None, ahora=None):
        self.api = api or api_registro
        self.tg = tg or tg_real
        self._ahora = ahora

    def ahora(self):
        return self._ahora() if self._ahora else dt.datetime.now(LIMA)


def memoria(state):
    return state.setdefault("envios", {})


def hoy(ctx):
    return ctx.ahora().astimezone(LIMA).strftime("%Y-%m-%d")


def olvidar_viejos(state, ctx):
    """Lo de hace más de una semana ya no se va a tocar: fuera de state.json."""
    limite = (ctx.ahora().astimezone(LIMA).date()
              - dt.timedelta(days=DIAS_QUE_SE_RECUERDA)).isoformat()
    mem = memoria(state)
    for k in [k for k, v in mem.items() if (v.get("fecha") or "") < limite]:
        del mem[k]


# ── textos ─────────────────────────────────────────────────────────────

def _e(t):
    return html.escape(str(t or ""), quote=False)


def cantidad_texto(e):
    partes = []
    if e.get("pequenas"):
        partes.append(f"{int(e['pequenas'])} pequeñas")
    if e.get("grandes"):
        partes.append(f"{int(e['grandes'])} grandes")
    linea = " y ".join(partes) or "0 galletas"
    sabores = ", ".join(f"{int(s['cantidad'])} {s['sabor']}" for s in e.get("sabores") or [])
    return f"{linea} ({sabores})" if sabores else linea


def lugar_agencia(e):
    """'MALL LAMBRAMANI (Arequipa)': el nombre exacto que se buscará en Shalom."""
    return e.get("destino") or e.get("agencia") or "—"


def recibe_texto(r):
    partes = [r.get("nombre") or "(Shalom lo saca del DNI)"]
    if r.get("dni"):
        partes.append(f"{'RUC' if len(r['dni']) == 11 else 'DNI'} {r['dni']}")
    partes.append(f"cel {r['cel']}" if r.get("cel") else "sin celular")
    return " · ".join(partes)


def cuando_sale(e, ctx):
    """'hoy', 'mañana' o la fecha, para el título."""
    hoy_ = ctx.ahora().astimezone(LIMA).date()
    try:
        f = dt.date.fromisoformat(e.get("fecha", ""))
    except ValueError:
        return e.get("fecha", "")
    if f == hoy_:
        return "hoy"
    if f == hoy_ + dt.timedelta(days=1):
        return "mañana"
    return f.strftime("%d/%m")


def proxima_hora_programada(ctx):
    """Las próximas 8:00 de Lima: hoy si todavía no son, si no mañana."""
    ahora = ctx.ahora().astimezone(LIMA)
    para = ahora.replace(hour=HORA_PROGRAMADA, minute=0, second=0, microsecond=0)
    return para if ahora < para else para + dt.timedelta(days=1)


def etiqueta_programada(ctx):
    para = proxima_hora_programada(ctx)
    dia = "Hoy" if para.date() == ctx.ahora().astimezone(LIMA).date() else "Mañana"
    return f"{dia} {HORA_PROGRAMADA}:00"


def texto_propuesta(e, caja, ctx):
    cuando = cuando_sale(e, ctx)
    lineas = [
        f"📦 <b>Sale {cuando} por Shalom</b>",
        "",
        f"Cliente: <b>{_e(e['cliente'])}</b>",
        f"Lleva: {_e(cantidad_texto(e))}",
        f"Agencia de destino: <b>{_e(lugar_agencia(e))}</b>",
        f"Recoge: {_e(recibe_texto(e.get('recibe') or {}))}",
        "Flete: lo paga el cliente en destino",
        f"Clave para recoger: <b>{_e(e.get('clave'))}</b>",
        f"Caja: <b>{NOMBRE_CAJA.get(caja, caja)}</b> — {_e(e.get('cajaPorque') or '')}",
    ]
    for a in e.get("avisos") or []:
        lineas.append(f"⚠️ {_e(a)}")
    if cuando != "hoy":
        # Shalom da 24 h para dejar el paquete en la agencia desde que se registra.
        lineas.append("⏳ Si lo registras ahora, Shalom da 24 h para dejarlo en la agencia: "
                      f"para un envío de {cuando} conviene ⏰.")
    lineas += ["", "¿Lo registro en Shalom? Si la caja no es esa, tócala abajo antes."]
    return "\n".join(lineas)


def teclado(id_envio, caja, ctx):
    """✅ ahora y ⏰ a las 8:00 arriba, las cajas en una fila, y "Hoy no".

    callback_data cabe holgado en los 64 bytes de Telegram: 'env:c:<12>:xxs'.
    """
    return [
        [{"text": f"✅ Registrar ahora · {NOMBRE_CAJA.get(caja, caja)}",
          "callback_data": f"env:ok:{id_envio}"},
         {"text": f"⏰ {etiqueta_programada(ctx)}", "callback_data": f"env:m:{id_envio}"}],
        [{"text": ("• " if c == caja else "") + NOMBRE_CAJA[c],
          "callback_data": f"env:c:{id_envio}:{c}"} for c in CAJAS],
        [{"text": "✖ Hoy no", "callback_data": f"env:no:{id_envio}"}],
    ]


def teclado_programado(id_envio):
    """Ya aprobado para las 8:00: se puede adelantar o cancelar."""
    return [[{"text": "✅ Mejor registrarlo ahora", "callback_data": f"env:ok:{id_envio}"},
             {"text": "✖ Cancelar", "callback_data": f"env:no:{id_envio}"}]]


def teclado_reintentar(id_envio):
    return [[{"text": "🔁 No está en Shalom: crearlo", "callback_data": f"env:re:{id_envio}"}]]


def texto_falta(e, ctx):
    lineas = [f"⚠️ <b>No puedo registrar solo el envío de {_e(e['cliente'])}</b> "
              f"(sale {cuando_sale(e, ctx)} por Shalom)", ""]
    lineas += [f"• {_e(f)}" for f in e.get("faltan") or []]
    lineas += ["", "Corrígelo en el panel → Cotizar y en la próxima revisión te lo propongo."]
    return "\n".join(lineas)


# ── 1 · proponer ──────────────────────────────────────────────────────

def proponer(state, ctx):
    """Manda a Telegram los envíos de hoy y de mañana que no se propusieron.

    Corre en cada revisión de 7:00 a 22:00: un pedido cargado a media tarde
    para hoy (sale a las 4 o 6) se propone en la siguiente media hora, y uno
    para mañana se puede dejar aprobado con ⏰. Uno que no se podía
    registrar ('falta') se vuelve a mirar en cada pasada, por si ya se
    corrigió en Cotizar.
    """
    hora = ctx.ahora().astimezone(LIMA).hour
    if not ctx.api.disponible() or not (HORA_DESDE <= hora < HORA_HASTA):
        return 0
    hoy_ = ctx.ahora().astimezone(LIMA).date()
    mem = memoria(state)
    mandados = 0
    envios = []
    for f in (hoy_, hoy_ + dt.timedelta(days=1)):
        envios += ctx.api.envios(f.isoformat())
    for e in envios:
        fecha = e["fecha"]
        local = mem.get(e["id"])
        if local and local.get("estado") != "falta":
            continue
        reg = e.get("registro") or {}
        if reg.get("estado") == "ok":
            # Se registró por otro lado (otra corrida, un estado perdido).
            mem[e["id"]] = {"estado": "ok", "fecha": fecha, "orden": reg.get("orden", "")}
            continue
        if e.get("faltan"):
            if not local:      # se avisa una vez; luego se re-mira en silencio
                ctx.tg.send_message(texto_falta(e, ctx))
                print(f"[envío {e['id']}] no se puede registrar: falta información.")
            mem[e["id"]] = {"estado": "falta", "fecha": fecha}
            continue
        caja = e.get("caja") if e.get("caja") in CAJAS else "m"
        msg = ctx.tg.send_buttons(texto_propuesta(e, caja, ctx), teclado(e["id"], caja, ctx))
        if not msg:
            print(f"[envío {e['id']}] no se pudo mandar la propuesta; se reintenta luego.")
            continue
        mem[e["id"]] = {"estado": "propuesto", "fecha": fecha, "caja": caja, "msg": msg}
        mandados += 1
        print(f"[envío {e['id']}] propuesto (caja {caja}).")
    return mandados


# ── 2 · los toques ────────────────────────────────────────────────────

def atender_boton(cb, state, ctx):
    """Un toque en un botón de envío. Solo cambia el estado local: crear la
    orden pasa después, con el navegador ya abierto (crear_confirmados)."""
    datos = (cb.get("data") or "").split(":")
    if len(datos) < 3 or datos[0] != "env":
        return False
    chat = str(((cb.get("message") or {}).get("chat") or {}).get("id", ""))
    if ctx.tg.CHAT_ID and chat != str(ctx.tg.CHAT_ID):
        return True        # botón de otro chat: ni se contesta
    accion, id_envio = datos[1], datos[2]
    mem = memoria(state)
    local = mem.get(id_envio)
    responder = lambda t: ctx.tg.answer_callback(cb.get("id"), t)

    if not local:
        responder("Ese envío ya no está pendiente.")
        return True
    estado = local.get("estado")

    if accion == "c" and len(datos) == 4 and datos[3] in CAJAS:
        if estado != "propuesto":
            responder(_por_que_no(local))
            return True
        local["caja"] = datos[3]
        ctx.tg.edit_buttons(local.get("msg"), teclado(id_envio, datos[3], ctx))
        responder(f"Caja {NOMBRE_CAJA[datos[3]]}")
    elif accion == "ok":
        if estado not in ("propuesto", "programado"):
            responder(_por_que_no(local))
            return True
        local["estado"] = "confirmado"
        local.pop("para", None)
        ctx.tg.edit_buttons(local.get("msg"), [])
        responder(f"Registrando con caja {NOMBRE_CAJA.get(local.get('caja'), '?')}…")
        print(f"[envío {id_envio}] confirmado con ✅.")
    elif accion == "m":
        if estado != "propuesto":
            responder(_por_que_no(local))
            return True
        para = proxima_hora_programada(ctx)
        local["estado"] = "programado"
        local["para"] = para.isoformat()
        ctx.tg.edit_buttons(local.get("msg"), teclado_programado(id_envio))
        responder(f"Listo: lo registro solo {etiqueta_programada(ctx).lower()} "
                  f"con caja {NOMBRE_CAJA.get(local.get('caja'), '?')}.")
        print(f"[envío {id_envio}] programado para {para.isoformat()}.")
    elif accion == "no":
        if estado not in ("propuesto", "programado"):
            responder(_por_que_no(local))
            return True
        local["estado"] = "cancelado"
        ctx.tg.edit_buttons(local.get("msg"), [])
        try:
            ctx.api.anotar(id_envio, "cancelado", fecha=local.get("fecha", ""))
        except Exception as err:
            print(f"[envío {id_envio}] no se pudo anotar la cancelación: {type(err).__name__}")
        responder("Listo: hoy no se registra.")
    elif accion == "re":
        if estado != "incierto":
            responder(_por_que_no(local))
            return True
        local["estado"] = "confirmado"
        local["forzar"] = True
        ctx.tg.edit_buttons(local.get("msg_incierto"), [])
        responder("Lo creo de nuevo…")
    else:
        responder("No entendí ese botón.")
    return True


def _por_que_no(local):
    return {
        "confirmado": "Ya lo estoy registrando.",
        "programado": f"Ya está programado para las {HORA_PROGRAMADA}:00.",
        "creando": "Ya lo estoy registrando.",
        "ok": f"Ya está registrado (orden {local.get('orden', '?')}).",
        "cancelado": "Ese envío se canceló hoy.",
        "incierto": "Primero revisa en Shalom si quedó creado.",
        "falta": "A ese envío le falta información.",
    }.get(local.get("estado"), "Ese botón ya no vale.")


# ── 3 · crear ─────────────────────────────────────────────────────────

def revisar_atascados(state, ctx):
    """Un 'creando' al empezar = la corrida anterior se cayó dentro de Shalom.

    No se sabe si la orden quedó creada, así que NO se reintenta solo: se
    marca incierto y se le pide a Aldahir que mire.
    """
    for id_envio, local in memoria(state).items():
        if local.get("estado") != "creando":
            continue
        _marcar_incierto(id_envio, local, ctx, "la corrida anterior se cortó mientras lo registraba")


def _marcar_incierto(id_envio, local, ctx, motivo):
    local["estado"] = "incierto"
    try:
        ctx.api.anotar(id_envio, "incierto", fecha=local.get("fecha", ""), error=motivo)
    except Exception as err:
        print(f"[envío {id_envio}] no se pudo anotar 'incierto': {type(err).__name__}")
    local["msg_incierto"] = ctx.tg.send_buttons(
        "⚠️ <b>No sé si el envío quedó creado en Shalom</b>\n\n"
        f"Motivo: {_e(motivo)}.\n\n"
        "Mira en Shalom Pro → Seguimiento si aparece una orden de hoy para "
        "ese cliente. Si <b>no</b> está, toca el botón y lo creo. Si está, no "
        "toques nada: el aviso de llegada sale igual.",
        teclado_reintentar(id_envio))
    print(f"[envío {id_envio}] incierto: {motivo}.")


def programados_que_tocan(state, ctx):
    """Los ⏰ cuya hora ya llegó pasan a confirmados (se crean en esta pasada)."""
    ahora = ctx.ahora().astimezone(LIMA)
    for id_envio, local in memoria(state).items():
        if local.get("estado") != "programado":
            continue
        try:
            para = dt.datetime.fromisoformat(local.get("para", ""))
        except ValueError:
            para = ahora
        if para <= ahora:
            local["estado"] = "confirmado"
            local.pop("para", None)
            print(f"[envío {id_envio}] llegó su hora programada.")


def crear_confirmados(pro, state, ctx, orders=None):
    """Crea en Shalom los envíos con ✅ (y los ⏰ cuya hora llegó).

    Devuelve cuántos quedaron registrados."""
    programados_que_tocan(state, ctx)
    mem = memoria(state)
    pendientes = [k for k, v in mem.items() if v.get("estado") == "confirmado"]
    if not pendientes:
        return 0
    frescos = {}          # fecha -> {id: envío}; los datos personales, solo en memoria
    hechos = 0
    for id_envio in pendientes:
        local = mem[id_envio]
        fecha = local.get("fecha") or hoy(ctx)
        if fecha not in frescos:
            frescos[fecha] = {e["id"]: e for e in ctx.api.envios(fecha)}
        e = frescos[fecha].get(id_envio)
        if not e:
            local["estado"] = "cancelado"
            ctx.tg.send_message("⚠️ Tocaste ✅ en un envío que ya no está en el registro "
                                "(¿se borró o cambió el pedido?). No registré nada.")
            continue
        if e.get("faltan"):
            local["estado"] = "falta"
            ctx.tg.send_message(texto_falta(e, ctx))
            continue

        permiso = ctx.api.anotar(id_envio, "creando", fecha=fecha,
                                 forzar=bool(local.get("forzar")))
        if not permiso.get("permitido"):
            reg = permiso.get("registro") or {}
            local["estado"] = "ok" if reg.get("estado") == "ok" else (reg.get("estado") or "incierto")
            if reg.get("estado") == "ok":
                local["orden"] = reg.get("orden", "")
                ctx.tg.send_message(f"ℹ️ El envío de {_e(e['cliente'])} ya estaba registrado: "
                                    f"orden <b>{_e(reg.get('orden'))}</b>. No creé otro.")
            else:
                ctx.tg.send_message(f"ℹ️ El envío de {_e(e['cliente'])} ya se está registrando "
                                    "por otro lado. No creé otro.")
            print(f"[envío {id_envio}] sin permiso para crear: ya estaba {reg.get('estado')}.")
            continue

        local["estado"] = "creando"
        local.pop("forzar", None)
        caja = local.get("caja") or e.get("caja") or "m"
        datos = datos_para_shalom(e, caja)
        print(f"[envío {id_envio}] creando en Shalom (caja {caja})...")
        try:
            res = pro.crear_envio(datos)
        except Exception as err:
            if getattr(err, "antes_de_enviar", False):
                # Seguro que no se creó: se puede volver a intentar.
                local["estado"] = "propuesto"
                try:
                    ctx.api.anotar(id_envio, "error", fecha=fecha, error=str(err)[:250])
                except Exception:
                    pass
                local["msg"] = ctx.tg.send_buttons(
                    f"❌ <b>No pude registrar el envío de {_e(e['cliente'])}</b>\n\n"
                    f"{_e(str(err)[:300])}\n\nNo se creó nada en Shalom. "
                    "Puedes intentarlo de nuevo o dejarlo para hacerlo a mano.",
                    teclado(id_envio, caja, ctx))
                print(f"[envío {id_envio}] falló antes de enviar: {type(err).__name__}.")
            else:
                _marcar_incierto(id_envio, local, ctx, f"falló después de enviar el formulario ({type(err).__name__})")
            continue

        local["estado"] = "ok"
        local["orden"] = res.get("orden", "")
        try:
            ctx.api.anotar(id_envio, "ok", fecha=fecha, orden=res.get("orden", ""),
                           codigo=res.get("codigo", ""), caja=caja,
                           pequenas=e.get("pequenas", 0), grandes=e.get("grandes", 0))
        except Exception as err:
            # La orden SÍ existe: se avisa igual. El registro se pone al día
            # en la próxima pasada (proponer ve que ya está y no repite).
            print(f"[envío {id_envio}] creado, pero no se pudo anotar: {type(err).__name__}")
        avisar_creado(e, res, caja, ctx)
        _mandar_ticket(pro, res, ctx)
        if orders is not None:
            _apuntar_en_seguimiento(orders, res, fecha)
        hechos += 1
        print(f"[envío {id_envio}] registrado: orden {res.get('orden')}.")
    return hechos


def datos_para_shalom(e, caja):
    r = e.get("recibe") or {}
    return {
        "agencia": e.get("agencia", ""), "agencia_id": e.get("agenciaId", ""),
        "dni": r.get("dni", ""), "nombre": r.get("nombre", ""), "celular": r.get("cel", ""),
        "caja": caja, "clave": e.get("clave", ""), "cantidad": 1,
        "flete": "destino",
    }


def mensaje_para_cliente(e, orden, codigo):
    """El "ya envié tu pedido" con orden, código y clave, listo para WhatsApp.

    Lo usan el aviso de registro y el de "Shalom ya lo recibió" (revisar.py):
    tiene que ser el mismo texto en los dos."""
    return mensajes.mensaje_registro(
        (e.get("recibe") or {}).get("nombre", ""), orden, codigo,
        e.get("agencia", "")).replace(mensajes.HUECO_CLAVE, e.get("clave", ""))


def buscar_por_orden(state, ctx, orden):
    """El envío del panel que se registró con este número de orden, o None.

    Sirve para volver a tener la clave y el nombre del cliente horas después
    de registrar, cuando Shalom recibe la caja: en state.json solo quedó el id
    opaco y la fecha, así que los datos se le vuelven a pedir al registro.
    Trae datos personales: no escribirlo a disco ni a los logs.
    """
    if not ctx.api.disponible():
        return None
    orden = str(orden or "")
    for id_envio, local in memoria(state).items():
        if not orden or str(local.get("orden") or "") != orden or not local.get("fecha"):
            continue
        for e in ctx.api.envios(local["fecha"]):
            if e.get("id") == id_envio:
                return e
    return None


def avisar_creado(e, res, caja, ctx):
    texto_cliente = mensaje_para_cliente(e, res.get("orden", ""), res.get("codigo", ""))
    link = mensajes.wa_link((e.get("recibe") or {}).get("cel", ""), texto_cliente)
    ctx.tg.send_message(
        f"✅ <b>Registrado en Shalom</b>\n\n"
        f"Cliente: <b>{_e(e['cliente'])}</b>\n"
        f"Orden: <b>{_e(res.get('orden'))}</b> · Código: <b>{_e(res.get('codigo') or '—')}</b>\n"
        f"Clave: <b>{_e(e.get('clave'))}</b> · Caja {NOMBRE_CAJA.get(caja, caja)}\n"
        f"Destino: {_e(lugar_agencia(e))}\n"
        # La tarifa que mostró Shalom: la paga el cliente al recoger.
        + (f"Flete: S/{float(res['precio']):.2f}, lo paga el cliente en destino\n" if res.get("precio") else "")
        + f""
        + (f"ℹ️ Shalom no conocía ese DNI: quedó como {_e(res['nombre_separado']['nombres'])} / "
           f"{_e(res['nombre_separado']['paterno'])} / {_e(res['nombre_separado']['materno'])}.\n"
           if res.get("nombre_separado") else "")
        + "\n"
        f"Mensaje: <i>{_e(texto_cliente)}</i>\n\n"
        + (f"👉 Toca para enviárselo por WhatsApp:\n{link}" if (e.get("recibe") or {}).get("cel")
           else "Sin celular guardado: cópialo y mándaselo tú."))


def _mandar_ticket(pro, res, ctx):
    """El ticket en PDF, como lo mandaba el aviso de registro. Si no sale (la
    orden recién creada puede tardar en aparecer en el seguimiento), no pasa
    nada: los datos de seguimiento ya llegaron."""
    try:
        pdf = pro.ticket_pdf(res.get("orden")) if res.get("orden") else None
    except Exception:
        pdf = None
    if pdf:
        ctx.tg.send_document(pdf, f"ticket-{res.get('orden')}.pdf",
                             caption="🎫 Ticket Shalom — reenvíaselo si te lo pide.")


def _apuntar_en_seguimiento(orders, res, fecha):
    """La orden nueva entra ya avisada al seguimiento: así revisar.py no manda
    otro "pedido registrado" (este ya llevó la clave, que el otro no sabe).

    Lo que sí queda pendiente es avisar cuando Shalom reciba la caja
    (entrega_avisada). Se apunta aquí y no al verla "En origen" en el portal
    porque a veces la orden recién creada tarda en salir en el seguimiento y,
    si la caja se deja en seguida, aparece ya directamente "En tránsito"."""
    orden = str(res.get("orden") or "")
    if not orden or any(str(o.get("orden")) == orden for o in orders):
        return
    ahora = dt.datetime.now(dt.timezone.utc).isoformat()
    orders.append({
        "orden": orden, "codigo": res.get("codigo", ""), "estado": "En origen",
        "fecha_envio": "-".join(reversed(fecha.split("-"))),
        "avisado": False, "registro_avisado": True, "entrega_avisada": False,
        "cerrado": False,
        "demora_avisada": False, "registrado": ahora, "last_checked": ahora,
    })


def hay_por_confirmar(state, ctx):
    """¿Queda algo de hoy o mañana esperando un toque? Para decidir si esperar."""
    hoy_ = ctx.ahora().astimezone(LIMA).date()
    fechas = {hoy_.isoformat(), (hoy_ + dt.timedelta(days=1)).isoformat()}
    return any(v.get("estado") == "propuesto" and v.get("fecha") in fechas
               for v in memoria(state).values())
