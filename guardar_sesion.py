# -*- coding: utf-8 -*-
"""
Genera la sesión de ShalomPRO para que el bot no tenga que iniciar sesión.

Por qué hace falta: reCAPTCHA v3 puntúa por reputación de IP, y desde los
runners de GitHub el portal empezó a rechazar el login con "Verificación de
seguridad fallida". Reintentar no sirve — los reintentos salen de la misma IP.
La salida es no iniciar sesión allí: se entra una vez desde una máquina normal
y se le pasa al bot la sesión ya hecha.

Cómo se usa:

    python guardar_sesion.py

Se abre un Chromium. Inicia sesión a mano, **marcando "Recuérdame"** para que la
sesión dure. Cuando llegues a la pantalla principal, vuelve aquí y pulsa Enter.
El script escribe sesion.json, que hay que pegar entero en el secret
SHALOM_STORAGE_STATE del repo (Settings -> Secrets and variables -> Actions).

La contraseña se escribe en el navegador, no aquí: este script no la pide, no la
lee y no la guarda.

OJO: sesion.json vale como tu sesión iniciada. No lo subas al repo (.gitignore
ya lo cubre) ni lo compartas. Cuando lo hayas pegado en el secret, bórralo.
"""
import io
import json
import os
import sys

from playwright.sync_api import sync_playwright

BASE = "https://pro.shalom.pe"
SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sesion.json")


def main():
    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=False)  # visible: entras tú
        contexto = navegador.new_context(
            locale="es-PE",
            timezone_id="America/Lima",
            viewport={"width": 1440, "height": 900},
        )
        pagina = contexto.new_page()
        pagina.goto(f"{BASE}/login", wait_until="networkidle", timeout=60000)

        print()
        print("=" * 68)
        print("  1. Inicia sesión en la ventana que se abrió")
        print("  2. MARCA la casilla 'Recuérdame' (si no, la sesión dura poco)")
        print("  3. Espera a ver la pantalla principal")
        print("  4. Vuelve aquí y pulsa Enter")
        print("=" * 68)
        print()
        input("Pulsa Enter cuando ya estés dentro... ")

        url = pagina.url
        if "/login" in url:
            print(f"\nSigues en la pantalla de login ({url}).")
            print("No se guardó nada. Vuelve a intentarlo.")
            navegador.close()
            return 1

        estado = contexto.storage_state()
        cookies = estado.get("cookies", [])
        recuerdame = [c for c in cookies if c["name"].startswith("remember_")]

        with io.open(SALIDA, "w", encoding="utf-8") as f:
            json.dump(estado, f, ensure_ascii=False)

        navegador.close()

        print()
        print("=" * 68)
        print(f"Sesión guardada en: {SALIDA}")
        print(f"Cookies: {len(cookies)}")
        if recuerdame:
            print("Incluye la cookie de 'Recuérdame': la sesión durará mucho.")
        else:
            print("AVISO: no hay cookie de 'Recuérdame'. ¿Marcaste la casilla?")
            print("Sin ella la sesión caduca en horas y habrá que repetir esto.")
        print()
        print("Ahora, en el repo de GitHub:")
        print("  Settings -> Secrets and variables -> Actions -> New secret")
        print("  Nombre: SHALOM_STORAGE_STATE")
        print("  Valor : todo el contenido de sesion.json")
        print()
        print("Cuando lo hayas pegado, borra sesion.json.")
        print("=" * 68)
        return 0


if __name__ == "__main__":
    sys.exit(main())
