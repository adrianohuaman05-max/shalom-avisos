# -*- coding: utf-8 -*-
"""
Consulta el estado de un pedido en shalom.com.pe usando un navegador headless.

Shalom protege su API con reCAPTCHA v3 (invisible) + respuesta encriptada, así que
la vía confiable es abrir la web logueada, buscar por N° Orden + Código y leer el
estado ya descifrado que la página muestra en pantalla.

Estados posibles que devuelve: "En origen", "En tránsito", "En destino", "Entregado".
Devuelve None si no pudo leerlo.
"""
import os
import re

from playwright.sync_api import sync_playwright

SHALOM_EMAIL = os.environ.get("SHALOM_EMAIL", "")
SHALOM_PASSWORD = os.environ.get("SHALOM_PASSWORD", "")
RASTREA_URL = "https://shalom.com.pe/rastrea"

ESTADO_RE = re.compile(r"^En (tr[aá]nsito|origen|destino)$|^Entregado$", re.IGNORECASE)

READ_STATUS_JS = """
() => {
  const el = Array.from(document.querySelectorAll('*')).find(
    e => /^En (tr[aá]nsito|origen|destino)$|^Entregado$/i.test((e.innerText||'').trim())
  );
  return el ? el.innerText.trim() : null;
}
"""


class ShalomTracker:
    def __init__(self, headless=True):
        self.headless = headless
        self._p = None
        self.browser = None
        self.context = None
        self.page = None

    def __enter__(self):
        self._p = sync_playwright().start()
        self.browser = self._p.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        self.context = self.browser.new_context(
            locale="es-PE",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
        )
        self.page = self.context.new_page()
        self._login()
        return self

    def __exit__(self, *exc):
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self._p:
                self._p.stop()

    def _login(self):
        page = self.page
        page.goto(RASTREA_URL, wait_until="networkidle", timeout=60000)
        # Si aparece el formulario de login (Correo / Contraseña), iniciar sesión.
        try:
            correo = page.locator('input[placeholder="Correo"]')
            if correo.count() > 0 and correo.first.is_visible():
                correo.first.fill(SHALOM_EMAIL)
                page.locator('input[placeholder="Contraseña"]').first.fill(SHALOM_PASSWORD)
                page.get_by_role("button", name=re.compile("Ingresar", re.I)).first.click()
                page.wait_for_load_state("networkidle", timeout=60000)
                page.wait_for_timeout(2000)
        except Exception as e:
            print("Aviso login:", e)

    def track(self, orden, codigo):
        """Devuelve el estado (str) o None."""
        page = self.page
        try:
            page.goto(RASTREA_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(1000)
            page.locator('input[placeholder="N° de Orden"]').first.fill(str(orden))
            page.locator('input[placeholder="Código de Orden"]').first.fill(str(codigo))
            page.get_by_role("button", name=re.compile("Buscar", re.I)).first.click()
            # esperar a que aparezca algún estado
            for _ in range(20):
                page.wait_for_timeout(1000)
                estado = page.evaluate(READ_STATUS_JS)
                if estado:
                    return estado.strip()
            return None
        except Exception as e:
            print(f"Error track {orden}:", e)
            try:
                page.screenshot(path=f"debug_{orden}.png")
            except Exception:
                pass
            return None


if __name__ == "__main__":
    import sys
    o, c = sys.argv[1], sys.argv[2]
    with ShalomTracker(headless=True) as t:
        print(o, c, "->", t.track(o, c))
