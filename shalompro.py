# -*- coding: utf-8 -*-
"""
Lector del portal ShalomPRO (pro.shalom.pe).

Reemplaza la búsqueda pedido-por-pedido de shalom_tracker.py: una sola carga de
/seguimientoenvios trae TODOS los envíos activos con su estado ya resuelto.

Por qué Playwright y no requests: la API interna del portal
(/service-orders/shipments/tracking) exige cabeceras firmadas con HMAC
(X-API-KEY / X-NONCE / X-TIMESTAMP / X-SIGNATURE) y encima devuelve el cuerpo
encriptado. Sin ellas responde 401 "Missing headers". La página descifra en el
navegador, así que la vía honesta y estable es leer el DOM ya renderizado.

Estados del portal: "En origen", "En transito", "En reparto", "En destino".
Los entregados salen de esta vista (se van a /historialenvios), así que la lista
se mantiene corta sola.

PRIVACIDAD: los datos del destinatario (nombre, DNI, celular) NO deben acabar en
disco ni en los logs — el repo es público. Se leen en memoria y solo viajan al
chat privado de Telegram. Por eso `listar()` no trae datos personales y hay que
pedir el detalle explícitamente con `detalle()`.
"""
import os
import re

from playwright.sync_api import sync_playwright

EMAIL = os.environ.get("SHALOM_EMAIL", "")
PASSWORD = os.environ.get("SHALOM_PASSWORD", "")

BASE = "https://pro.shalom.pe"
LOGIN_URL = f"{BASE}/login"
SEGUIMIENTO_URL = f"{BASE}/seguimientoenvios"

# Etiquetas que separan las secciones del panel de detalle.
_SECCIONES = ("Destinatario", "Forma de entrega", "Origen", "Destino",
              "Detalle del paquete", "Ver servicios adicionales")

# Lee las filas de la tabla. Ojo: la página renderiza el layout de escritorio
# (.shipment-row) y el de móvil (.shipment-card__*) a la vez; nos quedamos con
# el primero para no duplicar.
_LEER_FILAS_JS = """
() => [...document.querySelectorAll('.shipment-row')].map(r => {
  const txt = sel => (r.querySelector(sel)?.innerText || '').trim();
  const hijos = sel => {
    const el = r.querySelector(sel);
    return el ? [...el.children].map(e => (e.innerText || '').trim()) : [];
  };
  const contenido = hijos('.content-info');
  return {
    estado: txt('.col-status'),
    orden: txt('.order-number'),
    codigo: txt('.code-value'),
    contenido: contenido[0] || '',
    fecha: contenido[1] || '',
    monto: txt('.amount-info'),
  };
})
"""

_LEER_DRAWER_JS = """
() => {
  const el = document.querySelector('.drawer__content');
  return el ? el.innerText : null;
}
"""


def _limpiar(valor):
    return re.sub(r"\s+", " ", (valor or "")).strip()


def normalizar_estado(estado):
    """El portal escribe 'En transito' sin tilde; unificamos para comparar."""
    e = _limpiar(estado).lower().replace("á", "a")
    if "transito" in e:
        return "En tránsito"
    if "origen" in e:
        return "En origen"
    if "reparto" in e:
        return "En reparto"
    if "destino" in e:
        return "En destino"
    if "entregado" in e:
        return "Entregado"
    return _limpiar(estado)


def _parsear_drawer(texto):
    """Convierte el innerText del panel de detalle en un dict.

    El panel se ve así (una línea por elemento):
        N° Orden: 12345678
        Cód: 3TNH
        30-07-2026 09:38h
        Destinatario
        Luis Ramirez
        DNI:
        00000000
        CEL:
        9XXXXXXXX
        Forma de entrega
        En agencia - Terrestre
        Origen
        Parcona
        Ica / Ica / Parcona
        Destino
        Tingo Maria Co Buenos Aires
        Huanuco / Leoncio Prado / Rupa Rupa

    El label y su valor a veces vienen en la misma línea ("DNI: 00000000") y a
    veces separados, así que se contemplan ambos casos.
    """
    lineas = [_limpiar(l) for l in (texto or "").split("\n")]
    lineas = [l for l in lineas if l]

    datos = {"orden": "", "codigo": "", "fecha": "", "destinatario": "",
             "dni": "", "telefono": "", "forma_entrega": "",
             "origen": "", "destino": "", "destino_ubigeo": ""}

    # Campos sueltos de la cabecera.
    for i, linea in enumerate(lineas):
        m = re.match(r"^N[°ºo]?\s*Orden:\s*(\S+)", linea, re.I)
        if m:
            datos["orden"] = m.group(1)
        m = re.match(r"^C[óo]d(?:igo)?:\s*(\S+)", linea, re.I)
        if m:
            datos["codigo"] = m.group(1)
        if re.match(r"^\d{2}-\d{2}-\d{4}", linea):
            datos["fecha"] = linea

        # "DNI: 123" o "DNI:" seguido del número en la línea siguiente.
        for etiqueta, clave in (("DNI", "dni"), ("CEL", "telefono")):
            m = re.match(rf"^{etiqueta}:\s*(\S+)?$", linea, re.I)
            if m:
                datos[clave] = m.group(1) or (
                    lineas[i + 1] if i + 1 < len(lineas) else "")

    # Secciones: todo lo que va entre una etiqueta conocida y la siguiente.
    def seccion(nombre):
        try:
            ini = lineas.index(nombre)
        except ValueError:
            return []
        out = []
        for linea in lineas[ini + 1:]:
            if linea in _SECCIONES:
                break
            out.append(linea)
        return out

    dest = seccion("Destinatario")
    if dest:
        datos["destinatario"] = dest[0]

    entrega = seccion("Forma de entrega")
    if entrega:
        datos["forma_entrega"] = entrega[0]

    origen = seccion("Origen")
    if origen:
        datos["origen"] = origen[0]

    destino = seccion("Destino")
    if destino:
        datos["destino"] = destino[0]
        if len(destino) > 1:
            datos["destino_ubigeo"] = destino[1]

    return datos


class ShalomPro:
    def __init__(self, headless=True, debug_dir="."):
        self.headless = headless
        self.debug_dir = debug_dir
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
            timezone_id="America/Lima",
            viewport={"width": 1440, "height": 900},  # forzar layout de escritorio
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
        )
        self.page = self.context.new_page()
        self.login()
        return self

    def __exit__(self, *exc):
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self._p:
                self._p.stop()

    def captura(self, nombre):
        """Screenshot de diagnóstico. SOLO para páginas sin datos de clientes.

        Los artifacts de un repo público los puede descargar cualquiera, así que
        una foto del seguimiento filtraría nombres, DNIs y celulares. Para esas
        páginas usar `estructura()`, que no incluye texto.
        """
        try:
            ruta = os.path.join(self.debug_dir, f"debug_{nombre}.png")
            self.page.screenshot(path=ruta, full_page=True)
            return ruta
        except Exception:
            return None

    def estructura(self, limite=60):
        """Esqueleto del DOM (etiquetas y clases, sin texto).

        Sirve para depurar selectores rotos cuando Shalom cambie su web, sin
        exponer un solo dato de cliente en el log.
        """
        try:
            return self.page.evaluate(
                """(limite) => [...document.querySelectorAll('div,table,section,main')]
                     .map(e => e.tagName.toLowerCase() +
                          (e.className && typeof e.className === 'string'
                             ? '.' + e.className.trim().split(/\\s+/).join('.')
                             : ''))
                     .filter(s => s.includes('.'))
                     .slice(0, limite)""",
                limite,
            )
        except Exception:
            return []

    def login(self):
        if not EMAIL or not PASSWORD:
            raise RuntimeError(
                "Faltan SHALOM_EMAIL / SHALOM_PASSWORD en el entorno.")

        page = self.page
        page.goto(LOGIN_URL, wait_until="networkidle", timeout=60000)

        # Ya podríamos venir logueados (sesión reutilizada): el portal redirige.
        if "/login" not in page.url:
            return

        correo = page.locator(
            'input[type="email"], input[placeholder*="orreo" i]').first
        clave = page.locator('input[type="password"]').first
        correo.wait_for(state="visible", timeout=30000)
        correo.fill(EMAIL)
        clave.fill(PASSWORD)

        # reCAPTCHA v3 (invisible, por score): el token lo genera el JS de la
        # página sola. No hay nada que resolver, pero el servidor puede rechazar
        # el intento si el score es bajo — por eso el chequeo de abajo.
        page.get_by_role("button", name=re.compile("Iniciar sesión", re.I)).first.click()

        try:
            page.wait_for_url(re.compile(r"/home"), timeout=45000)
        except Exception:
            self.captura("login")
            texto = ""
            try:
                texto = _limpiar(page.inner_text("body"))[:300]
            except Exception:
                pass
            raise RuntimeError(
                f"El login no llegó a /home (url actual: {page.url}). "
                f"Puede ser credenciales o que reCAPTCHA v3 haya dado score bajo "
                f"desde esta IP. Texto en pantalla: {texto}")

    def listar(self):
        """Envíos activos, SIN datos personales (seguro para logs y disco)."""
        page = self.page
        page.goto(SEGUIMIENTO_URL, wait_until="networkidle", timeout=60000)
        try:
            page.wait_for_selector(".shipment-row", timeout=30000)
        except Exception:
            # Puede ser que no haya envíos activos; distinguirlo de un fallo.
            cuerpo = ""
            try:
                cuerpo = _limpiar(page.inner_text("body"))
            except Exception:
                pass
            if "Seguimiento de envios" in cuerpo or "Seguimiento de envíos" in cuerpo:
                return []
            raise RuntimeError(
                "No cargó la tabla de seguimiento de envíos. "
                f"Estructura del DOM: {self.estructura()}")

        filas = page.evaluate(_LEER_FILAS_JS)
        for f in filas:
            f["estado"] = normalizar_estado(f.get("estado"))
        return filas

    def detalle(self, orden):
        """Datos completos de un envío, incluido el celular del destinatario.

        Ojo: el resultado trae datos personales. No escribirlo a disco ni a logs.
        """
        page = self.page
        if "seguimientoenvios" not in page.url:
            page.goto(SEGUIMIENTO_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_selector(".shipment-row", timeout=30000)

        fila = page.locator(".shipment-row").filter(
            has=page.locator(f".order-number:text-is('{orden}')"))
        if fila.count() == 0:
            return None

        fila.first.get_by_text("Ver detalle").click()
        try:
            page.wait_for_selector(".drawer__content", timeout=15000)
            # Esperar a que el panel muestre ESTE pedido, no el anterior: si el
            # cierre falló, el drawer sigue abierto con los datos de otro envío
            # y comprobar solo "CEL" daría por bueno un dato equivocado.
            page.wait_for_function(
                """(orden) => {
                     const t = document.querySelector('.drawer__content')?.innerText || '';
                     return t.includes(orden) && t.includes('CEL');
                   }""",
                arg=str(orden),
                timeout=15000,
            )
        except Exception:
            print(f"[{orden}] no abrió el panel de detalle. "
                  f"Estructura: {self.estructura(30)}")
            return None

        datos = _parsear_drawer(page.evaluate(_LEER_DRAWER_JS))

        # Cerrar el panel para que el siguiente detalle abra limpio.
        # (Escape no lo cierra: hay que pulsar el botón.)
        try:
            page.locator(".drawer__close-btn").first.click()
            page.wait_for_selector(".drawer__content", state="detached", timeout=5000)
        except Exception:
            pass

        return datos


if __name__ == "__main__":
    with ShalomPro(headless=True) as pro:
        for envio in pro.listar():
            print(envio["orden"], envio["codigo"], "->", envio["estado"])
