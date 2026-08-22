# -*- coding: utf-8 -*-
"""
Genera la sesión de ShalomPRO para que el bot no tenga que iniciar sesión.

Por qué hace falta: el portal usa reCAPTCHA v3, que no pone ningún puzzle —
califica al navegador de 0 a 1 según lo humano que parezca y deja pasar solo a
partir de cierta nota. Un navegador automatizado, encima desde una IP de centro
de datos como las de GitHub, saca nota baja, y el portal contesta "Verificación
de seguridad fallida". Eso NO se arregla con la contraseña.

Por eso este script NO inicia sesión: abre un Chrome de verdad para que entres
tú a mano, y solo después le lee las cookies conectándose por el puerto de
depuración. Mientras inicias sesión no hay ninguna automatización conectada, así
que reCAPTCHA ve un navegador corriente — el tuyo.

Cómo se usa (Windows, macOS o Linux):

    pip install playwright
    python guardar_sesion.py

Se abre Chrome con un perfil aparte, así que no toca tu Chrome de siempre ni tus
otras sesiones. Inicia sesión y, cuando veas la pantalla principal, vuelve aquí
y pulsa Enter.

La casilla "Recuérdame" da igual: Shalom no emite la cookie correspondiente
aunque se marque. La sesión dura un par de horas y quien la mantiene viva es la
renovación automática del bot (secret GH_SECRETS_TOKEN, paso 6 del README).

La contraseña se escribe en el navegador: este script no la pide, no la lee y no
la guarda.

OJO: sesion.json vale como tu sesión iniciada. No lo subas al repo (.gitignore
ya lo cubre) ni lo compartas. Cuando lo pegues en el secret, bórralo.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright

BASE = "https://pro.shalom.pe"
PUERTO = 9222
SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sesion.json")

# Dónde vive Chrome en cada sistema. Sirve cualquier navegador de la familia
# Chrome (Chrome, Edge, Brave, Chromium): todos hablan el mismo protocolo de
# depuración, que es lo único que este script necesita.
CANDIDATOS = {
    "win32": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     r"Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
    "darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ],
    "linux": [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge",
        "/usr/bin/brave-browser",
        "/snap/bin/chromium",
    ],
}

EJECUTABLES = ["google-chrome", "google-chrome-stable", "chrome", "chrome.exe",
               "chromium", "chromium-browser", "msedge", "brave-browser"]


def buscar_chrome():
    """Ruta al navegador, mirando primero las rutas típicas y luego el PATH."""
    if os.environ.get("SHALOM_CHROME"):     # escotilla si está en otro sitio
        return os.environ["SHALOM_CHROME"]

    sistema = "win32" if sys.platform.startswith("win") else (
        "darwin" if sys.platform == "darwin" else "linux")
    for ruta in CANDIDATOS[sistema]:
        if ruta and os.path.isfile(ruta):
            return ruta
    for nombre in EJECUTABLES:
        ruta = shutil.which(nombre)
        if ruta:
            return ruta
    return None


def main():
    chrome = buscar_chrome()
    if not chrome:
        print("No encuentro Chrome (ni Edge, ni Brave, ni Chromium).")
        print("Instala Google Chrome, o dime dónde está:")
        print("  Windows : set SHALOM_CHROME=C:\\ruta\\a\\chrome.exe")
        print("  macOS/Linux: export SHALOM_CHROME=/ruta/a/chrome")
        return 1

    perfil = tempfile.mkdtemp(prefix="shalom-sesion-")
    print(f"Abriendo {os.path.basename(chrome)} (perfil temporal, no toca el tuyo)...")

    proceso = subprocess.Popen([
        chrome,
        "--remote-debugging-port=%d" % PUERTO,
        "--user-data-dir=%s" % perfil,
        "--no-first-run",
        "--no-default-browser-check",
        BASE + "/login",
    ])

    print()
    print("=" * 68)
    print("  1. Inicia sesión en la ventana que se abrió")
    print("  2. Espera a ver la pantalla principal de ShalomPRO")
    print("  3. Vuelve aquí y pulsa Enter (NO cierres el navegador)")
    print()
    print("  Es un navegador normal: reCAPTCHA no deberia rechazarte.")
    print("=" * 68)
    print()
    input("Pulsa Enter cuando ya estés dentro... ")

    codigo = 1
    try:
        with sync_playwright() as p:
            navegador = p.chromium.connect_over_cdp("http://localhost:%d" % PUERTO)
            contexto = navegador.contexts[0]

            urls = [pg.url for pg in contexto.pages]
            dentro = [u for u in urls if "shalom" in u and "/login" not in u]
            if not dentro:
                print("\nNo veo ninguna pestaña dentro del portal.")
                print("URLs abiertas:", urls)
                print("No se guardó nada. Vuelve a intentarlo.")
                return 1

            estado = contexto.storage_state()
            cookies = [c for c in estado.get("cookies", [])
                       if "shalom" in c.get("domain", "")]
            estado["cookies"] = cookies
            # Ojo: Shalom no emite cookie de "Recuerdame" aunque se marque la
            # casilla, asi que la sesion dura lo que dure la de Laravel — un par
            # de horas. Quien la mantiene viva de verdad es GH_SECRETS_TOKEN,
            # que deja al bot reguardarse las cookies frescas antes de que
            # venzan. Sin ese token esto hay que repetirlo cada dos por tres.

            # Una sola línea: el cuadro de secrets de GitHub acepta saltos, pero
            # copiar de una línea evita cortar el JSON por accidente.
            with io.open(SALIDA, "w", encoding="utf-8") as f:
                json.dump(estado, f, ensure_ascii=False, separators=(",", ":"))

            print()
            print("=" * 68)
            print("Sesión guardada en: %s" % SALIDA)
            print("Cookies de shalom: %d" % len(cookies))
            print()
            print("OJO: esta sesión caduca en un par de horas por sí sola.")
            print("Para que no haya que repetir esto, el repo necesita el")
            print("secret GH_SECRETS_TOKEN: con él el bot se reguarda las")
            print("cookies frescas antes de que venzan. Ver el README, paso 6.")
            print()
            print("Ahora, en el repo de GitHub:")
            print("  Settings -> Secrets and variables -> Actions")
            print("  New repository secret (o 'Update' si ya existe)")
            print("  Nombre: SHALOM_STORAGE_STATE")
            print("  Valor : TODO el contenido de sesion.json (una sola línea)")
            print()
            print("Cuando lo hayas pegado, borra sesion.json.")
            print("=" * 68)
            codigo = 0
    except Exception as e:
        print("\nNo se pudo leer la sesión: %s: %s" % (type(e).__name__, e))
        print("¿Cerraste la ventana del navegador antes de pulsar Enter?")
    finally:
        try:
            proceso.terminate()
            time.sleep(1)
        except Exception:
            pass
        shutil.rmtree(perfil, ignore_errors=True)

    return codigo


if __name__ == "__main__":
    sys.exit(main())
