# -*- coding: utf-8 -*-
"""
Mantiene viva sola la sesión de ShalomPRO.

El problema que resuelve: el login desde GitHub lo rechaza reCAPTCHA v3 por
reputación de IP, así que el bot trabaja con una sesión ya iniciada guardada en
el secret SHALOM_STORAGE_STATE. Pero esa sesión caducaría algún día, y renovarla
a mano obliga a sacar la laptop — justo lo que este proyecto intenta evitar.

La salida: cada vez que el bot entra bien, el portal le refresca las cookies. Si
se guardan de vuelta en el secret, la sesión se renueva sola y no caduca nunca.

Hace falta el secret GH_SECRETS_TOKEN: un token de GitHub de alcance fino, solo
sobre este repo y solo con permiso "Secrets: write". Si no está, esto no hace
nada y el bot sigue funcionando igual — solo que sin renovarse.

Los secrets de Actions se escriben cifrados con la clave pública del repo
(sealed box de libsodium): ni GitHub ni nadie puede volver a leer el valor.
"""
import base64
import json
import os

import requests

GH_TOKEN = os.environ.get("GH_SECRETS_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
NOMBRE_SECRET = "SHALOM_STORAGE_STATE"

API = "https://api.github.com"


def disponible():
    return bool(GH_TOKEN and REPO)


def guardar_sesion(estado):
    """Sube el storage_state al secret. True si se guardó.

    Nunca imprime ni el token ni las cookies: los logs de este repo son públicos.
    """
    if not disponible():
        return False

    try:
        from nacl import encoding, public
    except ImportError:
        print("Falta pynacl: no se puede renovar la sesión.")
        return False

    cabeceras = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        r = requests.get(f"{API}/repos/{REPO}/actions/secrets/public-key",
                         headers=cabeceras, timeout=30)
        if not r.ok:
            print(f"No se pudo pedir la clave pública del repo ({r.status_code}). "
                  f"¿Tiene el token permiso de Secrets: write?")
            return False
        clave = r.json()

        caja = public.SealedBox(
            public.PublicKey(clave["key"].encode(), encoding.Base64Encoder))
        cifrado = base64.b64encode(
            caja.encrypt(json.dumps(estado).encode("utf-8"))).decode("utf-8")

        r2 = requests.put(
            f"{API}/repos/{REPO}/actions/secrets/{NOMBRE_SECRET}",
            headers=cabeceras,
            json={"encrypted_value": cifrado, "key_id": clave["key_id"]},
            timeout=30,
        )
        if r2.status_code in (201, 204):
            print("Sesión renovada: el secret queda actualizado.")
            return True
        print(f"No se pudo guardar la sesión ({r2.status_code}).")
        return False
    except Exception as e:
        print("Fallo al renovar la sesión:", type(e).__name__)
        return False
