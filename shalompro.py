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
import json
import os
import random
import re
import time
import unicodedata

from playwright.sync_api import sync_playwright

EMAIL = os.environ.get("SHALOM_EMAIL", "")
PASSWORD = os.environ.get("SHALOM_PASSWORD", "")

# Sesión ya iniciada (cookies), en JSON. Si está, el navegador arranca logueado
# y no se toca el formulario: reCAPTCHA v3 puntúa por reputación de IP y desde
# los runners de GitHub rechaza el login con "Verificación de seguridad
# fallida". Se genera con guardar_sesion.py desde una máquina normal.
STORAGE_STATE = os.environ.get("SHALOM_STORAGE_STATE", "")

BASE = "https://pro.shalom.pe"
LOGIN_URL = f"{BASE}/login"
SEGUIMIENTO_URL = f"{BASE}/seguimientoenvios"

# Chrome de verdad (canal "chrome") en vez del Chromium de Playwright: la nota
# de reCAPTCHA v3 depende de la huella del navegador, y la compilacion de marca
# es la que tienen los usuarios reales. Si no esta instalado se cae solo al
# Chromium de siempre. Con SHALOM_CHROME_CHANNEL="" se fuerza Chromium.
CANAL = os.environ.get("SHALOM_CHROME_CHANNEL", "chrome").strip()


def _bool_env(nombre):
    """None si la variable no esta puesta; True/False segun su valor."""
    v = os.environ.get(nombre, "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    if v in ("1", "true", "si", "s\u00ed", "yes", "on"):
        return True
    return None


class ErrorLogin(RuntimeError):
    """Fallo de login con el motivo ya identificado.

    Guardar el motivo aparte permite que revisar.py mande a Telegram la
    instruccion concreta ("renueva la sesion", "cambio la clave") en lugar del
    volcado tecnico que nadie sabe interpretar desde el movil.
    """

    def __init__(self, mensaje, motivo, pista=""):
        super().__init__(mensaje)
        self.motivo = motivo
        self.pista = pista


def _sin_tildes(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto or "")
                   if unicodedata.category(c) != "Mn")


# Lo que dice la pantalla cuando el login no pasa, y como se traduce.
_SENALES = (
    ("verificacion de seguridad", "recaptcha"),
    ("recaptcha", "recaptcha"),
    ("captcha", "recaptcha"),
    ("credenciales", "credenciales"),
    ("contrasena incorrecta", "credenciales"),
    ("usuario o contrasena", "credenciales"),
    ("correo o contrasena", "credenciales"),
    ("bloquead", "bloqueada"),
    ("suspendid", "bloqueada"),
    ("inhabilitad", "bloqueada"),
)


def clasificar_fallo_login(texto):
    """Motivo del rechazo a partir del texto que quedo en pantalla."""
    t = _sin_tildes(texto).lower()
    for aguja, motivo in _SENALES:
        if aguja in t:
            return motivo
    return "desconocido"


# Google puntua el login con reCAPTCHA v3: no hay puzzle que resolver, solo una
# nota de 0 a 1 segun lo humano que parezca el navegador. Un Chromium headless
# con el user-agent falseado saca nota baja y el portal contesta "Verificacion
# de seguridad fallida". Este script tapa los delatores mas conocidos; el resto
# lo hacen el canal "chrome", la ventana real (Xvfb) y no mentir en el
# user-agent (ver _user_agent).
_ESCUDO_JS = r"""
// navigator.webdriver: el delator mas famoso.
try { delete Object.getPrototypeOf(navigator).webdriver; } catch (e) {}
try {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
} catch (e) {}

// Chrome de verdad expone window.chrome; los headless viejos no.
window.chrome = window.chrome || {
  runtime: {}, app: {}, csi: function () {}, loadTimes: function () {}
};

try {
  Object.defineProperty(navigator, 'languages',
    { get: () => ['es-PE', 'es', 'en-US', 'en'] });
} catch (e) {}

// Cero plugins = navegador de laboratorio.
try {
  if (!navigator.plugins || navigator.plugins.length === 0) {
    Object.defineProperty(navigator, 'plugins',
      { get: () => [1, 2, 3].map(() => ({ name: 'PDF Viewer' })) });
  }
} catch (e) {}

// permissions.query diciendo 'prompt' mientras Notification.permission dice
// 'denied' es otra contradiccion clasica de headless.
try {
  const query = navigator.permissions.query.bind(navigator.permissions);
  navigator.permissions.query = (p) =>
    (p && p.name === 'notifications')
      ? Promise.resolve({ state: Notification.permission })
      : query(p);
} catch (e) {}

// Sin GPU el renderer sale 'SwiftShader' o 'llvmpipe', que no tiene ningun
// equipo de usuario.
try {
  const original = WebGLRenderingContext.prototype.getParameter;
  const parche = function (p) {
    if (p === 37445) { return 'Intel Inc.'; }
    if (p === 37446) { return 'Intel Iris OpenGL Engine'; }
    return original.apply(this, arguments);
  };
  WebGLRenderingContext.prototype.getParameter = parche;
  if (window.WebGL2RenderingContext) {
    WebGL2RenderingContext.prototype.getParameter = parche;
  }
} catch (e) {}

// El iframe del ticket llama print() al cargar: abre el dialogo nativo del
// sistema y congela el navegador. Se anula en todos los frames.
window.print = function () {};
"""


def _teclear(campo, texto):
    """Escribe tecla a tecla, con la cadencia de una persona.

    reCAPTCHA v3 mira los eventos de teclado y raton: un campo que aparece
    relleno de golpe no genera ninguno.
    """
    pausa = random.randint(45, 110)
    try:
        campo.press_sequentially(texto, delay=pausa)
    except AttributeError:      # Playwright < 1.38
        campo.type(texto, delay=pausa)


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


# Sin --enable-automation (Playwright lo pone por su cuenta): pinta la barra de
# "controlado por software de pruebas" y marca la huella del navegador.
_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--window-size=1366,768",
    "--lang=es-PE",
]


class ShalomPro:
    def __init__(self, headless=True, debug_dir="."):
        # SHALOM_HEADLESS manda sobre el argumento: asi el workflow puede
        # abrirlo con ventana (sobre Xvfb) sin tocar el codigo.
        forzado = _bool_env("SHALOM_HEADLESS")
        self.headless = headless if forzado is None else forzado
        self.debug_dir = debug_dir
        self.sesion_guardada = False
        self.motivo_sin_sesion = ""
        # True si hubo que pasar por el formulario. Entrar asi es raro y
        # costoso (reCAPTCHA rechaza casi siempre), asi que cuando se logra
        # conviene guardar esa sesion en el acto en vez de esperar turno.
        self.uso_formulario = False
        self._p = None
        self.browser = None
        self.context = None
        self.page = None

    def _lanzar(self):
        """Chrome de marca si esta instalado; si no, el Chromium de Playwright."""
        comun = dict(headless=self.headless, args=_ARGS,
                     ignore_default_args=["--enable-automation"])
        ventana = "sin ventana" if self.headless else "con ventana"
        if CANAL:
            try:
                nav = self._p.chromium.launch(channel=CANAL, **comun)
                print(f"Navegador: Chrome (canal '{CANAL}'), {ventana}.")
                return nav
            except Exception as e:
                print(f"No se pudo abrir el canal '{CANAL}' ({type(e).__name__}); "
                      f"se usa el Chromium de Playwright.")
        nav = self._p.chromium.launch(**comun)
        print(f"Navegador: Chromium de Playwright, {ventana}.")
        return nav

    def _user_agent(self):
        """El user-agent real del navegador, solo con 'Headless' borrado.

        Inventarlo es peor que no tocarlo: el navegador manda ademas client
        hints (Sec-CH-UA, Sec-CH-UA-Platform) que no cambian con el user_agent
        de Playwright, y cualquier contradiccion entre ambos delata la
        automatizacion. La version anterior anunciaba "Windows NT 10.0" y
        "Chrome/126" mientras corria Chromium 130 sobre Linux.

        Devuelve None cuando el user-agent real ya vale y no hay que tocarlo.
        """
        try:
            temp = self.browser.new_context()
            try:
                ua = temp.new_page().evaluate("navigator.userAgent")
            finally:
                temp.close()
        except Exception:
            return None
        limpio = (ua or "").replace("HeadlessChrome", "Chrome")
        return limpio if limpio != ua else None

    @staticmethod
    def _horas_hasta_caducar(cookies):
        """Horas hasta que caduque la primera cookie, o None si ninguna tiene
        fecha. Manda la mas corta: en cuanto una muere, la sesion se rompe."""
        plazos = [c.get("expires") or 0 for c in cookies]
        plazos = [p for p in plazos if p > 0]
        return (min(plazos) - time.time()) / 3600.0 if plazos else None

    def _leer_storage_state(self):
        """Cookies de la sesion guardada, o None dejando anotado el porque.

        Solo se imprimen nombres y fechas: el valor de las cookies ES la sesion
        y los logs de este repo son publicos.
        """
        if not STORAGE_STATE.strip():
            self.motivo_sin_sesion = (
                "el secret SHALOM_STORAGE_STATE está vacío o no existe")
            return None
        try:
            estado = json.loads(STORAGE_STATE)
        except Exception as e:
            self.motivo_sin_sesion = (
                f"SHALOM_STORAGE_STATE no es JSON válido ({type(e).__name__})")
            return None
        cookies = [c for c in (estado.get("cookies") or [])
                   if "shalom" in (c.get("domain") or "")]
        if not cookies:
            self.motivo_sin_sesion = (
                "SHALOM_STORAGE_STATE no trae ninguna cookie de shalom.pe")
            return None

        nombres = sorted(c.get("name", "?") for c in cookies)
        print(f"Sesión guardada: {len(cookies)} cookie(s) de shalom.pe "
              f"({', '.join(nombres)}).")
        vencidas = [c.get("name", "?") for c in cookies
                    if 0 < (c.get("expires") or 0) <= time.time()]
        if vencidas:
            print(f"Aviso: ya caducaron {len(vencidas)} de ellas "
                  f"({', '.join(vencidas)}); puede que no sirva.")
        # Shalom NO emite cookie de "Recuerdame" aunque se marque la casilla
        # (comprobado). Asi que la sesion vive lo que viva enviashalom_session,
        # un par de horas, y quien la mantiene viva es la renovacion automatica
        # del secret. Sin GH_SECRETS_TOKEN esto caduca si o si.
        horas = self._horas_hasta_caducar(cookies)
        if horas is not None:
            print(f"Caduca en {horas:.1f} h" + (
                "." if os.environ.get("GH_SECRETS_TOKEN") else
                " y NO hay GH_SECRETS_TOKEN para renovarla: cuando venza, "
                "el bot se queda fuera."))
        return estado

    def __enter__(self):
        self._p = sync_playwright().start()
        self.browser = self._lanzar()
        opciones = dict(
            locale="es-PE",
            timezone_id="America/Lima",
            accept_downloads=True,  # el ticket va con inline=0: puede bajar como descarga
            viewport={"width": 1366, "height": 768},  # forzar layout de escritorio
            extra_http_headers={"Accept-Language": "es-PE,es;q=0.9,en;q=0.8"},
        )
        ua = self._user_agent()
        if ua:
            opciones["user_agent"] = ua
        estado = self._leer_storage_state()
        if estado:
            opciones["storage_state"] = estado
            self.sesion_guardada = True
        self.context = self.browser.new_context(**opciones)
        self.context.add_init_script(_ESCUDO_JS)
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

    def _texto_pantalla(self, limite=400):
        """Lo que se ve en pantalla, para saber por que no dejo entrar."""
        try:
            return _limpiar(self.page.inner_text("body"))[:limite]
        except Exception:
            return ""

    def login(self, intentos=3):
        """Entra al portal. Prefiere la sesion guardada; el formulario es plan B.

        El formulario pasa por reCAPTCHA v3: sin puzzle, solo una nota segun lo
        humano que parezca el navegador. Desde los runners de GitHub esa nota es
        baja y el portal contesta "Verificacion de seguridad fallida", asi que
        el camino bueno es SHALOM_STORAGE_STATE (una sesion abierta a mano) y
        este de aqui es el que se usa cuando aquel falta o ha caducado.
        """
        if self.sesion_guardada:
            try:
                self.page.goto(BASE + "/home", wait_until="networkidle",
                               timeout=60000)
            except Exception as e:
                print("No se pudo abrir /home con la sesión guardada:",
                      type(e).__name__)
            if "/login" not in self.page.url:
                print("Sesión guardada válida: no hizo falta iniciar sesión.")
                return
            self.motivo_sin_sesion = "la sesión guardada ya caducó"
            print("La sesión guardada caducó; se intenta con usuario y clave.")
        else:
            print(f"Sin sesión guardada ({self.motivo_sin_sesion}). Toca "
                  f"iniciar sesión a pelo, que es justo lo que reCAPTCHA "
                  f"rechaza casi siempre desde un runner.")

        if not EMAIL or not PASSWORD:
            raise ErrorLogin(
                "Faltan los secrets SHALOM_EMAIL / SHALOM_PASSWORD y no hay "
                "sesión guardada que valga.",
                "sin_credenciales", pista=self.motivo_sin_sesion)

        ultimo_texto = ""
        for intento in range(1, intentos + 1):
            try:
                if self._intentar_login():
                    if intento > 1:
                        print(f"Login correcto al intento {intento}.")
                    self.uso_formulario = True
                    return
                ultimo_texto = self._texto_pantalla() or ultimo_texto
                fallo = clasificar_fallo_login(ultimo_texto)
                print(f"Login intento {intento}: se quedó en /login ({fallo}).")
                # Reintentar un rechazo de reCAPTCHA en la misma corrida no
                # sirve de nada: la nota sale de la IP y de la huella del
                # navegador, y ninguna de las dos cambia en 10 segundos. Se
                # comprobo: 3 de 3 intentos, el mismo rechazo. Insistir solo
                # suma logins fallidos contra la cuenta de Shalom, que es lo
                # ultimo que interesa. La siguiente corrida cae en otro runner
                # y ahi si es un intento nuevo de verdad.
                if fallo in ("recaptcha", "credenciales", "bloqueada"):
                    print("Es un rechazo firme; no se insiste en esta corrida.")
                    break
            except Exception as e:
                print(f"Login intento {intento}: {type(e).__name__}")
            if intento < intentos:
                # Espera creciente y con ruido: reintentar al segundo exacto es
                # otra senal de bot.
                self.page.wait_for_timeout(
                    5000 * intento + random.randint(0, 2500))

        self.captura("login")
        motivo = clasificar_fallo_login(ultimo_texto)
        explicacion = {
            "recaptcha": (
                "el portal respondió «Verificación de seguridad fallida», que "
                "es reCAPTCHA puntuando bajo al navegador automático — no son "
                "las credenciales"),
            "credenciales": "el portal dice que el correo o la clave no valen",
            "bloqueada": "el portal dice que la cuenta está bloqueada",
        }.get(motivo, "el portal se quedó en /login sin decir por qué")

        raise ErrorLogin(f"No se pudo entrar a ShalomPRO: {explicacion}.",
                         motivo, pista=self.motivo_sin_sesion)

    def _intentar_login(self):
        """Un intento. True si acabo dentro, False si se quedo en /login."""
        page = self.page

        # Pasar antes por la portada: reCAPTCHA v3 tambien puntua el rastro de
        # navegacion, y aterrizar en /login sin venir de ningun sitio es lo que
        # hace un script, no una persona.
        try:
            page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(random.randint(900, 2000))
        except Exception:
            pass

        page.goto(LOGIN_URL, wait_until="networkidle", timeout=60000)

        # Ya podriamos venir logueados (sesion reutilizada): el portal redirige.
        if "/login" not in page.url:
            return True

        correo = page.locator(
            'input[type="email"], input[placeholder*="orreo" i]').first
        clave = page.locator('input[type="password"]').first
        correo.wait_for(state="visible", timeout=30000)

        # Mover el raton y escribir tecla a tecla genera los eventos que
        # reCAPTCHA v3 espera de una persona; un fill() no genera ninguno.
        try:
            page.mouse.move(random.randint(200, 1000), random.randint(150, 600))
        except Exception:
            pass
        correo.click()
        _teclear(correo, EMAIL)
        page.wait_for_timeout(random.randint(300, 900))
        clave.click()
        _teclear(clave, PASSWORD)

        # "Recuerdame" alarga muchisimo la cookie de sesion, y es la que luego
        # se guarda en el secret para no tener que volver a pasar por aqui.
        try:
            casilla = page.locator('input[type="checkbox"]').first
            if casilla.count() and not casilla.is_checked():
                casilla.check(timeout=3000)
        except Exception:
            pass

        # reCAPTCHA v3 genera su token de forma asincrona al cargar la pagina.
        # Si se pulsa antes de que este listo, el servidor rechaza el intento y
        # nos quedamos en /login sin ningun mensaje.
        try:
            page.wait_for_function(
                "() => window.grecaptcha && "
                "typeof window.grecaptcha.execute === 'function'",
                timeout=15000,
            )
        except Exception:
            pass  # si no aparece, se intenta igual: peor es no intentarlo
        page.wait_for_timeout(random.randint(1200, 2600))

        page.get_by_role(
            "button", name=re.compile("Iniciar sesion|Iniciar sesión", re.I)
        ).first.click()

        # El rechazo llega como aviso en la propia pagina, sin cambiar de URL:
        # esperar los 45 s enteros por un /home que no va a venir solo alarga la
        # corrida. Se vigila lo que pase primero.
        for _ in range(45):
            if "/login" not in page.url:
                return True
            if clasificar_fallo_login(self._texto_pantalla(600)) != "desconocido":
                return False
            page.wait_for_timeout(1000)
        return "/login" not in page.url

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
