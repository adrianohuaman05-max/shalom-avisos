# -*- coding: utf-8 -*-
"""
Genera la sesión de ShalomPRO para que el bot no tenga que iniciar sesión.

Por qué hace falta: el portal usa reCAPTCHA v3 y rechaza el login con
"Verificación de seguridad fallida" cuando lo intenta un navegador automatizado.
No es cosa de la IP — comprobado que falla igual desde una conexión doméstica.
Playwright deja `navigator.webdriver = true` y otras huellas que Google
reconoce; un Chrome normal las tiene limpias.

Por eso este script NO inicia sesión: abre un Chrome de verdad para que entres
tú a mano, y solo después le lee las cookies conectándose por el puerto de
depuración. Mientras inicias sesión no hay ninguna automatización conectada, así
que reCAPTCHA ve un navegador corriente.

Cómo se usa:

    python guardar_sesion.py

Se abre Chrome con un perfil aparte, así que no toca tu Chrome de siempre ni tus
otras sesiones. Inicia sesión **marcando "Recuérdame"**, y cuando veas la
pantalla principal vuelve aquí y pulsa Enter.

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

# En esta máquina Chromium se instaló en D: para no llenar C:. Sin esta variable
# Playwright lo busca en C: y falla con "Executable doesn't exist".
_NAVEGADORES = r"D:\Python\playwright-browsers"
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH") and os.path.isdir(_NAVEGADORES):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _NAVEGADORES

from playwright.sync_api import sync_playwright

BASE = "https://pro.shalom.pe"
PUERTO = 9222
SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sesion.json")

CANDIDATOS_CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""),
                 r"Google\Chrome\Application\chrome.exe"),
]


def buscar_chrome():
    for ruta in CANDIDATOS_CHROME:
        if ruta and os.path.isfile(ruta):
            return ruta
    return shutil.which("chrome") or shutil.which("chrome.exe")


def main():
    chrome = buscar_chrome()
    if not chrome:
        print("No encuentro chrome.exe. Instala Google Chrome o edita "
              "CANDIDATOS_CHROME en este script.")
        return 1

    perfil = tempfile.mkdtemp(prefix="shalom-sesion-")
    print("Abriendo Chrome (perfil temporal, no toca el tuyo)...")

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
    print("  1. Inicia sesión en la ventana de Chrome que se abrió")
    print("  2. MARCA la casilla 'Recuérdame' (si no, la sesión dura poco)")
    print("  3. Espera a ver la pantalla principal de ShalomPRO")
    print("  4. Vuelve aquí y pulsa Enter (NO cierres Chrome)")
    print()
    print("  Es un Chrome normal: reCAPTCHA no deberia rechazarte.")
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
            recuerdame = [c for c in cookies if c["name"].startswith("remember_")]

            with io.open(SALIDA, "w", encoding="utf-8") as f:
                json.dump(estado, f, ensure_ascii=False)

            print()
            print("=" * 68)
            print("Sesión guardada en: %s" % SALIDA)
            print("Cookies de shalom: %d" % len(cookies))
            if recuerdame:
                print("Incluye la cookie de 'Recuérdame': la sesión durará mucho.")
            else:
                print("AVISO: no hay cookie de 'Recuérdame'. ¿Marcaste la casilla?")
                print("Sin ella caduca antes; la renovación automática del bot")
                print("deberia mantenerla viva igual, pero es mejor tenerla.")
            print()
            print("Ahora, en el repo de GitHub:")
            print("  Settings -> Secrets and variables -> Actions -> New secret")
            print("  Nombre: SHALOM_STORAGE_STATE")
            print("  Valor : todo el contenido de sesion.json")
            print()
            print("Cuando lo hayas pegado, borra sesion.json.")
            print("=" * 68)
            codigo = 0
    except Exception as e:
        print("\nNo se pudo leer la sesión: %s: %s" % (type(e).__name__, e))
        print("¿Cerraste la ventana de Chrome antes de pulsar Enter?")
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
