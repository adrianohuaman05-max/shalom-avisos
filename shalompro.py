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
            accept_downloads=True,  # el ticket va con inline=0: puede bajar como descarga
            viewport={"width": 1440, "height": 900},  # forzar layout de escritorio
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
        )
        # El iframe del ticket llama print() al cargar, lo que abre el diálogo
        # nativo y congela el navegador. Se anula en todos los frames.
        self.context.add_init_script("window.print = () => {};")
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

    def login(self, intentos=3):
        """Entra al portal, reintentando: el login falla de vez en cuando.

        Visto en produccion: dos corridas seguidas murieron con "no llego a
        /home" y la pantalla capturada era el formulario limpio, sin mensaje de
        error — o sea, credenciales bien y rechazo del lado del servidor.
        """
        if not EMAIL or not PASSWORD:
            raise RuntimeError(
                "Faltan SHALOM_EMAIL / SHALOM_PASSWORD en el entorno.")

        for intento in range(1, intentos + 1):
            try:
                if self._intentar_login():
                    if intento > 1:
                        print(f"Login correcto al intento {intento}.")
                    return
            except Exception as e:
                print(f"Login intento {intento}: {type(e).__name__}")
            if intento < intentos:
                self.page.wait_for_timeout(5000 * intento)

        self.captura("login")
        texto = ""
        try:
            texto = _limpiar(self.page.inner_text("body"))[:300]
        except Exception:
            pass
        raise RuntimeError(
            f"El login no llego a /home tras {intentos} intentos (url actual: "
            f"{self.page.url}). Puede ser credenciales o que reCAPTCHA v3 haya "
            f"dado score bajo desde esta IP. Texto en pantalla: {texto}")

    def _intentar_login(self):
        """Un intento. True si acabo dentro, False si se quedo en /login."""
        page = self.page
        page.goto(LOGIN_URL, wait_until="networkidle", timeout=60000)

        # Ya podriamos venir logueados (sesion reutilizada): el portal redirige.
        if "/login" not in page.url:
            return True

        correo = page.locator(
            'input[type="email"], input[placeholder*="orreo" i]').first
        clave = page.locator('input[type="password"]').first
        correo.wait_for(state="visible", timeout=30000)
        correo.fill(EMAIL)
        clave.fill(PASSWORD)

        # reCAPTCHA v3 (invisible, por score) genera su token de forma asincrona
        # al cargar la pagina. Si se pulsa antes de que este listo, el servidor
        # rechaza el intento y nos quedamos en /login sin ningun mensaje: esa es
        # la causa mas probable de los fallos intermitentes.
        try:
            page.wait_for_function(
                "() => window.grecaptcha && "
                "typeof window.grecaptcha.execute === 'function'",
                timeout=15000,
            )
        except Exception:
            pass  # si no aparece, se intenta igual: peor es no intentarlo
        page.wait_for_timeout(1500)

        page.get_by_role(
            "button", name=re.compile("Iniciar sesion|Iniciar sesión", re.I)
        ).first.click()

        try:
            page.wait_for_url(re.compile(r"/home"), timeout=45000)
            return True
        except Exception:
            return False

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

    def _abrir_detalle(self, orden):
        """Abre el panel lateral del envío. Devuelve True si quedó abierto."""
        page = self.page
        if "seguimientoenvios" not in page.url:
            page.goto(SEGUIMIENTO_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_selector(".shipment-row", timeout=30000)

        fila = page.locator(".shipment-row").filter(
            has=page.locator(f".order-number:text-is('{orden}')"))
        if fila.count() == 0:
            return False

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
            return False
        return True

    def _cerrar_detalle(self):
        """Escape no cierra el panel: hay que pulsar el botón."""
        try:
            self.page.locator(".drawer__close-btn").first.click()
            self.page.wait_for_selector(
                ".drawer__content", state="detached", timeout=5000)
        except Exception:
            pass

    def detalle(self, orden):
        """Datos completos de un envío, incluido el celular del destinatario.

        Ojo: el resultado trae datos personales. No escribirlo a disco ni a logs.
        """
        if not self._abrir_detalle(orden):
            return None
        datos = _parsear_drawer(self.page.evaluate(_LEER_DRAWER_JS))
        self._cerrar_detalle()
        return datos

    def ticket_pdf(self, orden):
        """Bytes del ticket en PDF, o None si no se pudo.

        El portal no publica una URL fija del ticket: al pulsar "Descargar Ticket
        Shalom" pide un token (POST /ticket-pdf/token) y abre
        /ticket-pdf/<id>?token=<id>:<caducidad>:<firma>, que además va con
        `inline=0` — o sea, según el navegador puede acabar en una pestaña nueva
        o en una descarga.

        Por eso no se busca el elemento: se escucha la PETICIÓN de red, que
        ocurre igual en los dos casos. Y el `<id>` de la URL no es el número de
        orden sino un id interno de Shalom, así que la URL hay que verla, no
        deducirla.
        """
        page = self.page
        if not self._abrir_detalle(orden):
            return None

        urls = []

        def _mirar(req):
            if "/ticket-pdf/" in req.url and "token=" in req.url:
                urls.append(req.url)

        self.context.on("request", _mirar)
        try:
            boton = page.get_by_role(
                "button", name=re.compile("Descargar Ticket", re.I))
            if boton.count() == 0:
                print(f"[{orden}] no hay botón de ticket en el panel.")
                return None
            boton.first.click()

            for _ in range(30):
                page.wait_for_timeout(500)
                if urls:
                    break
            if not urls:
                print(f"[{orden}] el ticket no llegó a generarse.")
                return None

            # request del contexto = mismas cookies de sesión que la página.
            resp = self.context.request.get(urls[-1], timeout=30000)
            if not resp.ok:
                print(f"[{orden}] el ticket respondió {resp.status}.")
                return None
            datos = resp.body()
            if not datos.startswith(b"%PDF"):
                print(f"[{orden}] lo devuelto no es un PDF ({len(datos)} bytes).")
                return None
            print(f"[{orden}] ticket obtenido ({len(datos)} bytes).")
            return datos
        except Exception as e:
            print(f"[{orden}] fallo al obtener el ticket: {type(e).__name__}: {e}")
            return None
        finally:
            try:
                self.context.remove_listener("request", _mirar)
            except Exception:
                pass
            # El ticket puede haber abierto pestañas; cerrarlas o se acumulan.
            for p in list(self.context.pages):
                if p is not page and "ticket-pdf" in (p.url or ""):
                    try:
                        p.close()
                    except Exception:
                        pass
            self._cerrar_detalle()


if __name__ == "__main__":
    with ShalomPro(headless=True) as pro:
        for envio in pro.listar():
            print(envio["orden"], envio["codigo"], "->", envio["estado"])
