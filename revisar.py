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
import hashlib
import sys
import time

import envios_shalom
import mensajes
import renovacion
import storage
import telegram_bot as tg
from shalompro import ShalomPro

DEMORA_DIAS = 5            # avisar demora si sigue en tránsito tras estos días
AVISAR_EN = ("En destino", "En reparto")

# Campos con datos personales que las versiones viejas guardaban en orders.json.
CAMPOS_PERSONALES = ("cliente", "telefono", "destino")


# El estado en curso, para que el manejador de fallos guarde ESTE y no una
# copia recien leida del disco. Sin esto, un fallo despues de procesar_comandos
# tiraba el avance de telegram_offset y el bot volvia a contestar los mismos
# mensajes en cada corrida caida.
_estado_en_curso = None


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
        "registro_avisado": False,
        "cerrado": False,
        "demora_avisada": False,
        "registrado": now().isoformat(),
        "last_checked": now().isoformat(),
    }


def avisar_registro(pro, pedido):
    """Al descubrir un envío nuevo: manda los datos de seguimiento + el ticket.

    Es lo que el cliente pide nada más comprar, y sustituye a la foto de la
    boleta. Si el ticket falla, el mensaje se manda igual: los datos de
    seguimiento valen por sí solos y no se pierde el aviso por un PDF.
    """
    d = pro.detalle(pedido["orden"])
    if not d:
        print(f"[{pedido['orden']}] registrado, pero sin detalle todavía; "
              f"se reintenta en la próxima corrida.")
        return False

    texto = mensajes.mensaje_registro(
        d.get("destinatario", ""), d.get("orden") or pedido["orden"],
        d.get("codigo") or pedido.get("codigo", ""),
        d.get("destino", ""), d.get("destino_ubigeo", ""))
    link = mensajes.wa_link(d.get("telefono", ""), texto)

    tg.send_message(
        f"📦 <b>Pedido registrado</b>\n\n"
        f"Cliente: <b>{d.get('destinatario') or '—'}</b>\n"
        f"Pedido: {pedido['orden']} · cód. {d.get('codigo') or '—'}\n"
        f"Destino: {mensajes.agencia(d.get('destino',''), d.get('destino_ubigeo',''))}\n\n"
        f"Mensaje: <i>{texto}</i>\n\n"
        f"⚠️ Completa la clave antes de enviarlo.\n"
        f"👉 Toca para enviarle por WhatsApp:\n{link}"
    )

    pdf = pro.ticket_pdf(pedido["orden"])
    if pdf:
        tg.send_document(pdf, f"ticket-{pedido['orden']}.pdf",
                         caption="🎫 Ticket Shalom — reenvíaselo si te lo pide.")
        print(f"[{pedido['orden']}] aviso de registro + ticket enviados.")
    else:
        print(f"[{pedido['orden']}] aviso de registro enviado (sin ticket).")
    return True


def avisar_en_shalom(pro, pedido, clave=""):
    """Una orden que creó el bot acaba de salir en el seguimiento: el paquete
    ya se dejó en la agencia.

    Al crearla se avisó con la clave, pero entonces el ticket todavía no
    existía y el paquete ni siquiera estaba en Shalom. Este es el aviso del
    momento de la entrega: mensaje para el cliente (con la clave si el
    registro la tiene) y el ticket.
    """
    d = pro.detalle(pedido["orden"])
    if not d:
        print(f"[{pedido['orden']}] ya está en Shalom, pero sin detalle todavía; "
              f"se reintenta en la próxima corrida.")
        return False

    texto = mensajes.mensaje_registro(
        d.get("destinatario", ""), d.get("orden") or pedido["orden"],
        d.get("codigo") or pedido.get("codigo", ""),
        d.get("destino", ""), d.get("destino_ubigeo", ""))
    if clave:
        texto = texto.replace(mensajes.HUECO_CLAVE, clave)
    link = mensajes.wa_link(d.get("telefono", ""), texto)
    _e = envios_shalom._e

    tg.send_message(
        f"📦 <b>Ya está en Shalom</b>\n\n"
        f"Cliente: <b>{_e(d.get('destinatario') or '—')}</b>\n"
        f"Pedido: {_e(pedido['orden'])} · cód. {_e(d.get('codigo') or pedido.get('codigo') or '—')}\n"
        f"Destino: {_e(mensajes.agencia(d.get('destino',''), d.get('destino_ubigeo','')))}\n\n"
        f"Mensaje: <i>{_e(texto)}</i>\n\n"
        + ("" if clave else "⚠️ Completa la clave antes de enviarlo.\n")
        + f"👉 Toca para enviarle por WhatsApp:\n{link}"
    )

    pdf = pro.ticket_pdf(pedido["orden"])
    if pdf:
        tg.send_document(pdf, f"ticket-{pedido['orden']}.pdf",
                         caption="🎫 Ticket Shalom — reenvíaselo si te lo pide.")
    # El log es público: solo el número de orden.
    print(f"[{pedido['orden']}] ya está en Shalom: aviso enviado"
          f"{' con ticket' if pdf else ' (sin ticket)'}.")
    return True


def atender_recien_dejado(pro, pedido, state):
    """Si es una orden del bot que sale por primera vez en el portal, avisa
    que ya está en Shalom. Mismo `is False` que registro_avisado: los pedidos
    de antes no tienen el campo y no se tocan."""
    if pedido.get("en_portal") is not False:
        return
    if pedido.get("estado") in AVISAR_EN:
        # Apareció ya en destino: el aviso de llegada lo cubre.
        pedido["en_portal"] = True
        return
    clave = envios_shalom.clave_de(pedido["orden"], state, _ctx_envios())
    if avisar_en_shalom(pro, pedido, clave):
        pedido["en_portal"] = True


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


def huella_bot(token):
    """Una marca del bot de Telegram que no revela el token (state.json es público)."""
    bot_id = (token or "").split(":")[0]
    return hashlib.sha256(bot_id.encode()).hexdigest()[:12] if bot_id else ""


def revisar_cambio_de_bot(state):
    """Si cambió el bot de Telegram (otro token), su offset no sirve: los
    update_id del bot nuevo empiezan en otro número, y con el offset viejo
    Telegram daría por leídos todos los toques. Se empieza de cero."""
    huella = huella_bot(tg.TOKEN)
    antes = state.get("telegram_bot")
    if not huella or antes == huella:
        return False
    state["telegram_bot"] = huella
    if not antes:
        # Primera vez que se anota: es el mismo bot de siempre, el offset vale.
        # Volver a 0 aquí podría releer un ✅ viejo y crear una orden repetida.
        return False
    print("Bot de Telegram nuevo: se lee desde el principio.")
    state["telegram_offset"] = 0
    return True


def procesar_comandos(orders, state, espera=0):
    """Atiende /listar, /ayuda y los botones de los envíos por Shalom.

    Es el UNICO lector de getUpdates del bot: Telegram entrega cada
    novedad una vez y la da por leida al avanzar el offset, asi que un
    segundo lector se quedaria con la mitad de los toques. Con espera > 0
    aguarda hasta esos segundos a que llegue algo (para el ✅ de la mañana).

    Ese lector único tiene que ser de verdad único: hasta el 14/11 el bot de
    ventas del celular usaba el MISMO bot de Telegram y se quedaba con los ✅.
    """
    revisar_cambio_de_bot(state)
    updates = tg.get_updates(offset=state.get("telegram_offset", 0), timeout=espera)
    for u in updates:
        state["telegram_offset"] = u["update_id"] + 1
        cb = u.get("callback_query")
        if cb:
            try:
                envios_shalom.atender_boton(cb, state, _ctx_envios())
            except Exception as err:
                print("Fallo al atender un boton:", type(err).__name__)
            continue
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
                    estado = ("registrado, falta dejarlo en la agencia"
                              if o.get("en_portal") is False else o.get("estado") or "¿?")
                    lineas.append(f"• {o['orden']} — {estado}{aviso}")
                tg.send_message("\n".join(lineas), chat_id=chat_id)
        elif texto:
            tg.send_message(mensajes.AYUDA, chat_id=chat_id)


DIAS_SIN_APARECER = 7       # una orden del bot que nunca se dejó en la agencia


def cerrar_desaparecidos(orders, vistos):
    """Un envío que ya no está en seguimiento fue entregado y sale de la vista.

    Salvo las órdenes que creó el bot y todavía no salieron en el portal
    (en_portal=False): esas no están porque el paquete aún no se dejó, no
    porque ya se entregó. Si en una semana no aparecen, se cierran igual.
    """
    cerrados = 0
    for o in orders:
        if o.get("cerrado") or o["orden"] in vistos:
            continue
        if o.get("en_portal") is False:
            horas = horas_desde(o.get("registrado"))
            if horas is None or horas < DIAS_SIN_APARECER * 24:
                continue
        o["cerrado"] = True
        o["estado"] = "Entregado"
        cerrados += 1
    if cerrados:
        print(f"Cerrados {cerrados} pedido(s) que ya no están en seguimiento.")


def probar_ticket(orden):
    """Manda a Telegram el aviso de registro de un pedido concreto, sin tocar
    nada del estado. Sirve para comprobar que el ticket se descarga bien sin
    tener que esperar al siguiente envío real."""
    print(f"Prueba de ticket para el pedido {orden}...")
    with ShalomPro(headless=True) as pro:
        activos = pro.listar()
        if orden not in {e["orden"] for e in activos}:
            print(f"El pedido {orden} no está en seguimiento. Activos: "
                  f"{[e['orden'] for e in activos]}")
            return 1
        ok = avisar_registro(pro, {"orden": orden, "codigo": ""})
    print("Listo." if ok else "No se pudo completar la prueba.")
    return 0 if ok else 1


def reavisar(ordenes):
    """Reenvia el aviso de llegada de pedidos concretos, sin tocar el estado.

    Util cuando ya se avisaron pero hace falta el mensaje otra vez (se perdio el
    chat, el cliente lo pide de nuevo). Lee el estado real del portal, asi que
    manda el mensaje que corresponda a como este el pedido ahora.
    """
    print(f"Reenviando aviso de: {', '.join(ordenes)}")
    enviados = 0
    with ShalomPro(headless=True) as pro:
        activos = {e["orden"]: e for e in pro.listar()}
        for orden in ordenes:
            envio = activos.get(orden)
            if not envio:
                print(f"[{orden}] no esta en seguimiento; se omite.")
                continue
            if envio["estado"] not in AVISAR_EN:
                print(f"[{orden}] esta '{envio['estado']}', todavia no ha llegado; "
                      f"se omite.")
                continue
            if avisar_llegada(pro, {"orden": orden}, envio["estado"]):
                enviados += 1
    print(f"Reenviados {enviados} de {len(ordenes)}.")
    return 0 if enviados else 1


# ── Envios por Shalom que se registran solos (envios_shalom.py) ─────────
# Minutos que la corrida de la mañana se queda esperando el ✅ despues de
# proponer. Sin esto, tocar ✅ a las 8:05 crearia la orden recien en la
# corrida de las 8:30. Solo se espera si esta corrida propuso algo: el
# resto del dia, un toque se atiende en la siguiente revision.
MINUTOS_ESPERANDO_OK = 15
HORAS_ENTRE_AVISOS_ENVIOS = 6
_ctx = None


def _ctx_envios():
    global _ctx
    if _ctx is None:
        _ctx = envios_shalom.Contexto()
    return _ctx


def registrar_envios_del_dia(pro, orders, state):
    """Propone los envios de hoy, crea los que tienen ✅ y espera un rato.

    Un fallo aqui no puede tumbar el seguimiento: los avisos de llegada son
    lo que ya funcionaba. Se avisa por Telegram, como mucho cada 6 h.
    """
    ctx = _ctx_envios()
    if not ctx.api.disponible():
        return
    try:
        envios_shalom.olvidar_viejos(state, ctx)
        envios_shalom.revisar_atascados(state, ctx)
        propuestos = envios_shalom.proponer(state, ctx)
        envios_shalom.crear_confirmados(pro, state, ctx, orders)
        if propuestos:
            esperar_ok(pro, orders, state, ctx)
    except Exception as err:
        print("Fallo en el registro de envios:", type(err).__name__, str(err)[:200])
        ultimo = horas_desde(state.get("envios_ultimo_fallo"))
        if ultimo is None or ultimo >= HORAS_ENTRE_AVISOS_ENVIOS:
            tg.send_message(
                "⚠️ <b>No pude revisar los envíos por Shalom de hoy</b>\n\n"
                f"<code>{str(err)[:300]}</code>\n\n"
                "Lo reintento en la próxima revisión. Si se repite, regístralos a mano.")
            state["envios_ultimo_fallo"] = now().isoformat()


def esperar_ok(pro, orders, state, ctx):
    """Se queda escuchando los botones mientras quede algo por confirmar."""
    limite = time.time() + MINUTOS_ESPERANDO_OK * 60
    print(f"Esperando el ✅ hasta {MINUTOS_ESPERANDO_OK} min...")
    while time.time() < limite and envios_shalom.hay_por_confirmar(state, ctx):
        procesar_comandos(orders, state, espera=25)
        envios_shalom.crear_confirmados(pro, state, ctx, orders)


HORAS_ENTRE_RENOVACIONES = 12
HORAS_MARGEN_CADUCIDAD = 3


def horas_hasta_caducar(estado):
    """Horas hasta que caduque la PRIMERA cookie de shalom, o None si ninguna
    tiene fecha. Manda la mas corta: en cuanto una muere, la sesion se rompe."""
    plazos = [c.get("expires") or 0 for c in (estado.get("cookies") or [])
              if "shalom" in (c.get("domain") or "")]
    plazos = [p for p in plazos if p > 0]
    return (min(plazos) - time.time()) / 3600.0 if plazos else None


def renovar_sesion_si_toca(pro, state):
    """Guarda las cookies frescas en el secret para que la sesion no caduque.

    El ritmo no puede ser un numero fijo. Shalom NO emite cookie de "Recuerdame"
    aunque se marque la casilla (comprobado: solo manda enviashalom_session y
    XSRF-TOKEN), asi que lo unico que sostiene la sesion es la cookie de sesion
    de Laravel, que dura un par de horas. El navegador la recibe fresca en cada
    visita, pero en el secret sigue la copia vieja: si se renovara solo cada 12 h
    esa copia ya estaria caducada mucho antes, Playwright la descartaria al
    cargarla y volveriamos al formulario. Por eso manda la caducidad real de las
    cookies y no el reloj.
    """
    if not renovacion.disponible():
        print("Sin GH_SECRETS_TOKEN la sesión NO se renueva: cuando caduque la "
              "cookie habrá que rehacerla a mano con guardar_sesion.py.")
        return
    try:
        estado = pro.context.storage_state()
    except Exception as e:
        print("No se pudo leer la sesion del navegador:", type(e).__name__)
        return

    quedan = horas_hasta_caducar(estado)
    desde = horas_desde(state.get("ultima_renovacion_sesion"))

    if quedan is not None and quedan < HORAS_MARGEN_CADUCIDAD:
        print(f"La sesión guardada caduca en {quedan:.1f} h: se renueva ya.")
    elif pro.uso_formulario:
        # Entrar por el formulario es lo raro: reCAPTCHA lo rechaza casi
        # siempre. Cuando por fin cuela, esa sesion se guarda YA — es justo la
        # que evita tener que volver a pasar por ahi.
        print("Se entró por el formulario: se guarda esta sesión de inmediato.")
    elif desde is not None and desde < HORAS_ENTRE_RENOVACIONES:
        return

    if renovacion.guardar_sesion(estado):
        state["ultima_renovacion_sesion"] = now().isoformat()


def _revisar():
    if "--reavisar" in sys.argv:
        i = sys.argv.index("--reavisar")
        if i + 1 >= len(sys.argv):
            print("Falta la lista de pedidos: --reavisar 123,456")
            return 1
        ordenes = [o.strip() for o in sys.argv[i + 1].split(",") if o.strip()]
        return reavisar(ordenes)

    if "--probar-ticket" in sys.argv:
        i = sys.argv.index("--probar-ticket")
        if i + 1 >= len(sys.argv):
            print("Falta el número de pedido: --probar-ticket 90455950")
            return 1
        return probar_ticket(sys.argv[i + 1])

    sin_avisos = "--sin-avisos" in sys.argv

    global _estado_en_curso
    orders = storage.load_orders()
    state = storage.load_state()
    _estado_en_curso = state
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
                if not sin_avisos and pedido["estado"] not in AVISAR_EN:
                    # Si ya llegó, no tiene sentido mandar "va en camino":
                    # el aviso de llegada de abajo lo cubre.
                    if avisar_registro(pro, pedido):
                        pedido["registro_avisado"] = True
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
                if pedido.get("en_portal") is False:
                    pedido["en_portal"] = True
                continue

            estado = pedido["estado"]

            # Reintento si el aviso de registro falló (sin detalle, ticket caído).
            # Ojo al `is False`: los pedidos de antes de esta función no tienen
            # el campo, y a esos NO hay que avisarles — el cliente ya sabe de
            # ellos y recibiría un "va en camino" con semanas de retraso.
            if pedido.get("registro_avisado") is False and estado not in AVISAR_EN:
                if avisar_registro(pro, pedido):
                    pedido["registro_avisado"] = True

            atender_recien_dejado(pro, pedido, state)

            if estado in AVISAR_EN and not pedido.get("avisado"):
                if avisar_llegada(pro, pedido, estado):
                    pedido["avisado"] = True
            elif estado == "En tránsito" and not pedido.get("demora_avisada"):
                if avisar_demora(pedido):
                    pedido["demora_avisada"] = True

        cerrar_desaparecidos(orders, vistos)
        if not sin_avisos:
            registrar_envios_del_dia(pro, orders, state)
        renovar_sesion_si_toca(pro, state)

    registrar_resultado(state, ok=True)
    storage.save_orders(orders)
    storage.save_state(state)
    if sin_avisos:
        print("Modo --sin-avisos: estados sincronizados, no se avisó a nadie.")
    print("Listo.")


HORAS_ENTRE_AVISOS_DE_FALLO = 6
MINUTOS_ENTRE_CORRIDAS = 30     # el cron de revisar.yml
FALLOS_PARA_MANTENIMIENTO = 3
CADA_CUANTOS_FALLOS_INSISTIR = 12

# Que hacer segun por que no dejo entrar el portal. El dueno lee esto en el
# movil: tiene que decir el siguiente paso, no el traceback.
ARREGLOS = {
    "recaptcha": (
        "El portal da por robot al navegador del bot (su reCAPTCHA no ve una "
        "persona detrás). No es tu contraseña.\n\n"
        "<b>Arreglo:</b> abre una sesión desde tu PC con "
        "<code>python guardar_sesion.py</code> y pega lo que genere en el "
        "secret <code>SHALOM_STORAGE_STATE</code> del repo. Con eso el bot deja "
        "de iniciar sesión: entra ya logueado y reCAPTCHA no aparece."),
    "credenciales": (
        "El portal dice que el correo o la contraseña no son correctos.\n\n"
        "<b>Arreglo:</b> entra a mano a pro.shalom.pe. Si te cambió la clave, "
        "actualiza los secrets <code>SHALOM_EMAIL</code> y "
        "<code>SHALOM_PASSWORD</code>."),
    "bloqueada": (
        "El portal dice que la cuenta está bloqueada o suspendida.\n\n"
        "<b>Arreglo:</b> entra a mano a pro.shalom.pe y desbloquéala; el bot "
        "solo lee, no puede hacerlo por ti."),
    "sin_credenciales": (
        "Faltan los secrets del portal.\n\n"
        "<b>Arreglo:</b> revisa que existan <code>SHALOM_EMAIL</code> y "
        "<code>SHALOM_PASSWORD</code> en Settings → Secrets → Actions."),
}


def arreglo_de(err):
    """Instruccion concreta para este fallo, o cadena vacia si no se sabe."""
    texto = ARREGLOS.get(getattr(err, "motivo", ""), "")
    pista = getattr(err, "pista", "")
    if texto and pista:
        texto += f"\n\n<i>De paso: {pista}.</i>"
    return texto


def registrar_resultado(state, ok, err=None):
    """Lleva la cuenta de fallos seguidos y avisa cuando toca mantenimiento.

    Un fallo suelto se arregla solo en la siguiente corrida y no merece ruido.
    Varios seguidos ya no: significa que algo cambio (el portal, las
    credenciales, el reCAPTCHA) y hace falta meter mano. Ese caso merece un
    aviso distinto y mas claro que el de un tropiezo puntual.
    """
    seguidos = int(state.get("fallos_seguidos", 0))

    if ok:
        if seguidos >= FALLOS_PARA_MANTENIMIENTO:
            tg.send_message(
                "✅ <b>El bot volvió a funcionar</b>\n\n"
                f"Se había caído {seguidos} corridas seguidas y ya entró bien. "
                "No hay que hacer nada."
            )
            print(f"Recuperado tras {seguidos} fallos seguidos.")
        state["fallos_seguidos"] = 0
        return

    seguidos += 1
    state["fallos_seguidos"] = seguidos

    toca = (seguidos == FALLOS_PARA_MANTENIMIENTO or
            (seguidos > FALLOS_PARA_MANTENIMIENTO and
             (seguidos - FALLOS_PARA_MANTENIMIENTO) % CADA_CUANTOS_FALLOS_INSISTIR == 0))
    if not toca:
        return

    horas = round(seguidos * MINUTOS_ENTRE_CORRIDAS / 60)
    arreglo = arreglo_de(err)
    tg.send_message(
        "🔧 <b>El bot necesita mantenimiento</b>\n\n"
        f"Llevo <b>{seguidos} corridas seguidas</b> sin poder entrar "
        f"(unas {horas} horas).\n\n"
        + (arreglo + "\n\n" if arreglo else
           "Esto ya no se arregla solo.\n\n")
        + "Los pedidos NO se pierden: en cuanto vuelva a entrar se pone al día "
          "de todo."
    )
    print(f"Aviso de mantenimiento enviado ({seguidos} fallos seguidos).")


def avisar_fallo(state, err):
    """Avisa por Telegram si la corrida revienta.

    Sin esto, una caida solo se ve entrando a GitHub a mirar los workflows, y
    lo normal es enterarse dias despues. Se limita a un aviso cada
    HORAS_ENTRE_AVISOS_DE_FALLO para que un fallo persistente (Shalom caido,
    cuenta bloqueada) no llene el chat: seguiria fallando cada 2 horas.
    """
    ultimo = horas_desde(state.get("ultimo_fallo_avisado"))
    if ultimo is not None and ultimo < HORAS_ENTRE_AVISOS_DE_FALLO:
        print("Fallo no avisado por Telegram: ya se aviso hace poco.")
        return
    arreglo = arreglo_de(err)
    tg.send_message(
        "⚠️ <b>El bot no pudo revisar los pedidos</b>\n\n"
        f"<code>{str(err)[:300]}</code>\n\n"
        + (arreglo if arreglo else
           "Reintenta solo en la próxima corrida. Si se repite varias veces, "
           "revisa que la cuenta de ShalomPRO siga entrando bien.")
    )
    state["ultimo_fallo_avisado"] = now().isoformat()


def main():
    try:
        return _revisar()
    except Exception as err:
        # Se guarda el estado que traia la corrida, no una copia limpia del
        # disco: si el fallo llego despues de atender los comandos de Telegram,
        # recargar tiraba el offset y el bot volvia a contestar lo mismo en cada
        # corrida caida. Si reviento antes de leerlo siquiera, se lee ahora.
        try:
            state = (_estado_en_curso if _estado_en_curso is not None
                     else storage.load_state())
            registrar_resultado(state, ok=False, err=err)
            avisar_fallo(state, err)
            storage.save_state(state)
        except Exception as e2:
            print("Ademas fallo el aviso de fallo:", type(e2).__name__)
        raise


if __name__ == "__main__":
    sys.exit(main() or 0)
