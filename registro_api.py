# -*- coding: utf-8 -*-
"""
Cliente del registro de PowerCookies (el Apps Script del taller).

De ahí salen los envíos por Shalom de cada día: los pedidos cargados en el
panel cuyo cliente tiene guardado "envío por Shalom" en Cotizar, con quién
recoge y la agencia exacta. Y ahí se anota lo que se registró, que es el
candado contra duplicados: el registro decide, con su propio candado, si
este envío ya se está registrando o ya está registrado.

El bot entra con SU clave (secret REGISTRO_CLAVE), no con la del panel: solo
alcanza estas dos acciones y ninguna devuelve dinero.

PRIVACIDAD: la respuesta de `envios()` trae nombre, DNI y celular de quien
recoge. Se usa en memoria y viaja solo al chat privado de Telegram; nunca a
disco ni a los logs (el repo es público).

Variables de entorno:
  REGISTRO_URL    la URL /exec del Apps Script (la misma del panel)
  REGISTRO_CLAVE  la clave del bot (menú del Sheets: "Envíos Shalom: ver o
                  crear la clave del bot")
"""
import os

import requests

URL = os.environ.get("REGISTRO_URL", "").strip()
CLAVE = os.environ.get("REGISTRO_CLAVE", "").strip()


class ErrorRegistro(RuntimeError):
    """El registro respondió con un error, o no respondió."""


def disponible():
    return bool(URL and CLAVE)


def _llamar(accion, **datos):
    if not disponible():
        raise ErrorRegistro("Faltan REGISTRO_URL / REGISTRO_CLAVE")
    cuerpo = dict(datos, action=accion, token=CLAVE)
    try:
        # Apps Script contesta un POST con una redirección a
        # script.googleusercontent.com; requests la sigue con GET, que es lo
        # que espera Google (el script ya corrió con el POST).
        r = requests.post(URL, json=cuerpo, timeout=90, allow_redirects=True)
    except Exception as e:
        raise ErrorRegistro(f"El registro no respondió ({type(e).__name__})")
    try:
        data = r.json()
    except Exception:
        # Una página HTML en vez de JSON: casi siempre la URL equivocada o el
        # script sin publicar. Nunca se imprime el cuerpo: podría traer datos.
        raise ErrorRegistro(f"El registro no devolvió JSON (HTTP {r.status_code})")
    if not data.get("ok"):
        raise ErrorRegistro(str(data.get("error") or "error sin detalle")[:200])
    return data.get("data") or {}


def envios(fecha):
    """Lista de envíos por Shalom de `fecha` ('yyyy-mm-dd'). Trae datos personales."""
    return _llamar("shalomEnvios", fecha=fecha).get("envios") or []


def anotar(id_envio, estado, **extra):
    """Anota cómo le fue a un envío. Devuelve {'permitido': bool, 'registro': {...}}.

    estado: 'creando' (pide permiso; solo uno lo obtiene), 'ok', 'error',
    'incierto' o 'cancelado'. Ver accionShalomAnotar en el Apps Script.
    """
    return _llamar("shalomAnotar", id=id_envio, estado=estado, **extra)
