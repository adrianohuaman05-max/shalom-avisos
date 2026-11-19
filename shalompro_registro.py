# -*- coding: utf-8 -*-
"""
Registrar un envío en pro.shalom.pe (lo usa envios_shalom.py tras el ✅).

El formulario es /registroindividual, un asistente por pasos. Lo de abajo
salió de recorrerlo en vivo (2026-11-07, sin crear nada) y de su código
público (js/app.js):

  1. Tipo de producto   carrusel; se avanza con la flecha ›. Caja Paquete M
                        = 0.30 x 0.20 x 0.24.
  2. Origen y destino   buscadores (vue-multiselect) "Origen" / "Destino".
                        Cada opción dice "DEP / PROV / DIST / NOMBRE" y su id
                        es el mismo de la lista de shalom.com.pe (PARCONA =
                        565). Ojo: existe "NOMBRE - AEREO" aparte.
  3. Adicionales        Envío Sobreprotegido viene en "No deseo" y así se
                        queda; la documentación (GRR) es opcional.
  4. Destinatario       al escribir el DNI, Shalom lo busca solo. Si no lo
                        conoce, pide nombre, dos apellidos y celular: sin
                        celular no deja seguir.
  5. Cobro Seguro       viene en "No deseo el servicio" y así se queda.
  6. Clave              teclado con los números DESORDENADOS (se busca cada
                        dígito por su rótulo). La declaración jurada no
                        aparece sin documentación; es opcional y se deja sin
                        marcar (marcada, exige guía de remisión).
  Recorrido completo hasta el paso 6 el 2026-11-09 con Aldahir: caja L,
  PARCONA (565) → CRUZ DE MOTUPE (144), S/18, sin crear nada.
  →  "Continuar" con el asistente en el paso 6 es el que crea la orden
     (POST /envia_ya/service_order/save). Antes de ese toque no existe nada.
  7. Resultado          "ENVÍO PENDIENTE DE CONFIRMACIÓN" con orden y código.
  8. Detalle            (desde 2026-11-19) solo muestra la orden ya creada.

El 2026-11-19 Shalom paso su portal de Vue 2 a Vue 3 + Vite (bundle
/assets/index-*.js, el formulario en /assets/FormEnvio-*.js). Leido su
codigo nuevo: mismos pasos 1-6, mismos campos del estado y mismos
selectores; la orden se sigue creando al pulsar Continuar en el paso 6
(V(): `t.status!==6||await F()`, y F() hace el POST y llena `guide` antes
de pasar al 7). Lo unico que se rompio fue la forma de leer el estado
(ver _ESTADO_JS). Si Shalom no conoce el DNI, el destinatario se registra
al pulsar Continuar en el paso 4 (eso no crea ninguna orden).

No hay paso de quién paga: Shalom asume el flete en destino (Aldahir).

Cómo se trabaja: cada acción es en la pantalla, como una persona (clics y
teclas; la API de detrás exige cabeceras firmadas y cifra el cuerpo). Y
después de cada una se COMPRUEBA en el estado del propio formulario
(el `store` de Vue, solo lectura): qué caja quedó, qué id de agencia, si
el destinatario quedó registrado. Así un clic que "parece" bueno pero no
cuajó se detecta antes de crear nada.

Errores: todo lo que falle ANTES del toque final lanza NoSeEnvio
(antes_de_enviar = True): seguro que no se creó nada. Lo que falle DESPUÉS
lanza otro error: no se sabe si quedó creada (envios_shalom.py lo trata como
incierto y nunca reintenta solo).

PRIVACIDAD: aquí pasan DNI, nombre y celular. El estado que se lee del
formulario devuelve solo números de paso, ids y sí/no; ningún dato de la
persona vuelve a Python ni a los logs, y no se toman capturas de pantalla
(los artifacts del repo son públicos).
"""
import os
import re

REGISTRO_URL = "https://pro.shalom.pe/registroindividual"
# La agencia donde Aldahir deja las cajas. Configurable por si cambia.
ORIGEN = os.environ.get("SHALOM_ORIGEN", "PARCONA").strip()
ORIGEN_ID = int(os.environ.get("SHALOM_ORIGEN_ID", "565") or 0)

NOMBRE_PRODUCTO = {"sobre": "Sobre", "xxs": "Caja Paquete XXS", "xs": "Caja Paquete XS",
                   "s": "Caja Paquete S", "m": "Caja Paquete M", "l": "Caja Paquete L"}

PASO_QUE_CREA = 6       # "Continuar" con el asistente aquí crea la orden
ESPERA = 30000

# Lo que se lee del formulario. Nunca devuelve nombres, DNI ni teléfonos:
# solo el paso, ids y banderas.
#
# Donde esta el estado. Vue 3 (desde 2026-11-19): FormEnvio lo guarda en un
# reactive() y se lo pasa a cada paso como prop `store` (los pasos van con
# v-show, asi que siempre estan montados). En produccion no hay
# __vueParentComponent, pero #app._vnode si: se baja por el arbol (vnode ->
# component.subTree, children en lista, suspense.activeBranch) hasta el
# primer componente cuyo props.store tenga typeProduct y status. Vue 2 (hasta
# el 2026-11-18): #app.__vue__ y un componente con storeModule; se deja de
# respaldo. Sin #app o sin estado devuelve null (y _esperar sigue esperando)
# en vez de reventar como el 2026-11-19 ("Cannot read properties of
# undefined").
_ESTADO_JS = r"""
(clave) => {
  const app = document.querySelector('#app');
  if (!app) return null;
  const esEstado = (x) => !!x && typeof x === 'object' && 'typeProduct' in x && 'status' in x;
  let s = null;
  const pila = [app._vnode];
  let vueltas = 0;
  while (pila.length && vueltas++ < 50000) {
    const v = pila.pop();
    if (!v || typeof v !== 'object') continue;
    const c = v.component;
    if (c) {
      if (c.props && esEstado(c.props.store)) { s = c.props.store; break; }
      pila.push(c.subTree);
    }
    if (v.suspense) pila.push(v.suspense.activeBranch);
    if (Array.isArray(v.children)) {
      for (let i = v.children.length - 1; i >= 0; i--) pila.push(v.children[i]);
    }
  }
  if (!s && app.__vue__) {
    (function rec(vm){
      if (s || !vm) return;
      if (vm.storeModule) { s = vm.storeModule; return; }
      (vm.$children || []).forEach(rec);
    })(app.__vue__);
  }
  if (!s) return null;
  return {
    paso: s.status,
    producto: (s.typeProduct && s.typeProduct.title) || '',
    origen: (s.origin && s.origin.id) || 0,
    destino: (s.destiny && s.destiny.id) || 0,
    precio: Number(s.price) || 0,
    sobreprotegido: Number(s.warranty) || 0,
    cobro_seguro: Number(s.collection_service) || 0,
    declaracion: !!(s.declaracion_jurada && s.declaracion_jurada.tipo),
    destinatario: !!s.receiver_uuid,
    destinatario_tiene_celular: !!(s.receiver && (s.receiver.phone || s.receiver.phone_masked)),
    clave_puesta: (s.code || '').length,
    clave_ok: clave ? s.code === clave : null,
    guia: s.guide ? String(s.guide) : '',
    codigo: s.code_guide ? String(s.code_guide) : '',
  };
}
"""


class NoSeEnvio(RuntimeError):
    """Falló antes de enviar el formulario: en Shalom no se creó nada."""
    antes_de_enviar = True


def _norm(t):
    t = (t or "").lower().replace("\xa0", " ")
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def nombre_de_opcion(texto):
    """'LIMA / LIMA / SJM / AV LOS PRECURSORES / LAS AMERICAS' -> el nombre.

    Las opciones son "DEP / PROV / DIST / NOMBRE", y hay nombres que llevan
    " / " adentro (comprobado el 2026-11-09): el nombre es todo lo que va
    después de los tres primeros tramos, no solo el último.
    """
    return " / ".join((texto or "").strip().split(" / ")[3:])


def separar_nombre(nombre):
    """'Juan Carlos Quispe Mamani' -> ('Juan Carlos', 'Quispe', 'Mamani').

    Solo hace falta cuando Shalom no conoce el DNI. Es aproximado (los
    apellidos compuestos se cortan mal), por eso el aviso de "registrado"
    dice cómo quedó. Con menos de tres palabras no se adivina: None.
    """
    p = (nombre or "").split()
    if len(p) < 3:
        return None
    return " ".join(p[:-2]), p[-2], p[-1]


def motivo(e, largo=120):
    """El porqué de una excepción, corto y sin datos personales.

    Hasta el 2026-11-19 el aviso solo decía el tipo ("Error") y costó saber
    que era el cambio a Vue 3. Ahora va la primera línea del mensaje (la de
    Playwright dice qué falló; las de abajo son el call log), cortada, y con
    toda cifra de 4 o más dígitos tapada: DNI, celular o clave nunca salen.
    """
    texto = (str(e) or "").strip()
    linea = texto.splitlines()[0].strip() if texto else ""
    linea = re.sub(r"\d{4,}", "••••", linea)
    if len(linea) > largo:
        linea = linea[:largo - 1].rstrip() + "…"
    return linea


def _paso(nombre):
    """Un fallo dice en qué paso fue y por qué, sin datos personales."""
    def envolver(fn):
        def interno(*a, **k):
            try:
                return fn(*a, **k)
            except NoSeEnvio:
                raise
            except Exception as e:
                por = motivo(e)
                tipo = type(e).__name__
                raise NoSeEnvio(f"Me quedé en el paso «{nombre}» ({tipo}: {por})." if por
                                else f"Me quedé en el paso «{nombre}» ({tipo}).") from e
        return interno
    return envolver


def estado(page, clave=None):
    return page.evaluate(_ESTADO_JS, clave) or {}


def _esperar(page, condicion, que, segundos=20, clave=None):
    """Espera a que el formulario cumpla `condicion(estado)`."""
    for _ in range(segundos * 2):
        e = estado(page, clave)
        if e and condicion(e):
            return e
        page.wait_for_timeout(500)
    raise NoSeEnvio(f"El formulario no llegó a: {que}.")


# Copiado tal cual de k() en FormEnvio (portal Vue 3, 2026-11-19). Shalom
# revisa la clave recien en el paso 7, cuando la orden YA se creo en el 6:
# con una clave de esta lista se crearia la orden y luego Shalom la tumbaria.
# Solo esas dos listas: 0000, 0123, 7890 o 4321 Shalom si las acepta.
CLAVES_REPETIDAS = ("1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999")
CLAVES_SEGUIDAS = ("1234", "2345", "3456", "4567", "5678", "6789")


def clave_valida(clave):
    """True si Shalom acepta la clave en su paso 7 (4 numeros, ni repetida ni seguida)."""
    clave = clave or ""
    return (bool(re.fullmatch(r"\d{4}", clave))
            and clave not in CLAVES_REPETIDAS and clave not in CLAVES_SEGUIDAS)


def crear_envio(pro, datos, enviar=True):
    """Llena el formulario y, con enviar=True, crea la orden.

    datos: agencia (nombre exacto), agencia_id, dni, nombre, celular, caja,
           clave, cantidad, flete ('destino').
    Devuelve {'orden', 'codigo', 'precio', 'nombre_separado'} o, con
    enviar=False, {'preparado': True, ...} dejando la página en el último
    paso SIN tocar el botón que crea (para probar con Aldahir mirando).
    """
    if datos.get("caja") not in NOMBRE_PRODUCTO:
        raise NoSeEnvio(f"Caja desconocida: {datos.get('caja')}")
    if not re.fullmatch(r"\d{4}", datos.get("clave") or ""):
        raise NoSeEnvio("La clave para recoger no tiene 4 números.")
    if not clave_valida(datos.get("clave")):
        raise NoSeEnvio("La clave de hoy es repetida o seguida y Shalom la rechaza: "
                        "cámbiala en el Sheets y vuelve a intentar.")
    if not re.fullmatch(r"\d{8}|\d{11}", datos.get("dni") or ""):
        raise NoSeEnvio("El DNI de quien recoge no tiene 8 números.")

    page = pro.page
    _abrir(page)
    _elegir_producto(page, NOMBRE_PRODUCTO[datos["caja"]])
    _elegir_agencia(page, "Origen", ORIGEN, ORIGEN_ID)
    _elegir_agencia(page, "Destino", datos["agencia"], int(datos.get("agencia_id") or 0))
    precio = _tarifa_y_adicionales(page)
    separado = _destinatario(page, datos)
    _hasta_la_clave(page, datos["clave"])
    _revisar_antes_de_crear(page, datos)

    if not enviar:
        return {"preparado": True, "precio": precio, "nombre_separado": separado}

    # Desde aquí, un fallo ya no es "seguro que no se creó".
    _boton_continuar(page).click()
    e = _esperar_resultado(page)
    return {"orden": e["guia"], "codigo": e["codigo"], "precio": precio,
            "nombre_separado": separado}


@_paso("abrir el formulario")
def _abrir(page):
    page.goto(REGISTRO_URL, wait_until="networkidle", timeout=60000)
    if "/login" in page.url:
        raise NoSeEnvio("La sesión de Shalom Pro no está abierta.")
    _esperar(page, lambda e: e.get("paso") == 1, "el paso 1 (tipo de producto)")


@_paso("tipo de producto")
def _elegir_producto(page, titulo):
    # El carrusel no responde a clics de JavaScript: hay que pulsar la flecha
    # de verdad. Con 7 tarjetas, 8 vueltas alcanzan para cualquiera.
    flecha = page.locator(".flicking-arrow-next").filter(visible=True).first
    for _ in range(8):
        if estado(page).get("producto") == titulo:
            break
        flecha.click()
        page.wait_for_timeout(900)      # el producto cambia al terminar la animación
    _esperar(page, lambda e: e.get("producto") == titulo, f"la {titulo}", segundos=5)
    _continuar(page)
    _esperar(page, lambda e: e.get("paso") == 2, "el paso 2 (origen y destino)")


@_paso("origen y destino")
def _elegir_agencia(page, cual, nombre, ter_id):
    """Elige la agencia cuyo nombre coincide EXACTO y comprueba su id.

    Nada de "la primera que salga": una agencia equivocada manda la caja a
    otra ciudad. Las opciones dicen "DEP / PROV / DIST / NOMBRE"; se compara
    el último tramo entero (así "MALL LAMBRAMANI - AEREO" no pasa por
    "MALL LAMBRAMANI"). Si hay dos con el mismo nombre en distintas
    ciudades, decide el id.
    """
    clave_estado = "origen" if cual == "Origen" else "destino"
    caja = page.locator(".multiselect").filter(has=page.locator(f"input[placeholder='{cual}']")).first
    palabras = [p for p in _norm(nombre).split() if len(p) > 2] or _norm(nombre).split()
    buscar = max(palabras, key=len)
    candidatas_vistas = 0
    for intento in range(4):
        caja.click()
        page.keyboard.type(buscar, delay=40)
        page.wait_for_timeout(1200)
        opciones = caja.locator(".multiselect__option").filter(visible=True)
        exactas = [i for i in range(opciones.count())
                   if _norm(nombre_de_opcion(opciones.nth(i).inner_text())) == _norm(nombre)]
        candidatas_vistas = len(exactas)
        if intento >= len(exactas):
            page.keyboard.press("Escape")
            break
        opciones.nth(exactas[intento]).click()
        page.wait_for_timeout(800)
        elegido = estado(page).get(clave_estado)
        if not ter_id or elegido == ter_id:
            return
    raise NoSeEnvio(f"No encontré en Shalom la agencia de {cual.lower()} «{nombre}»"
                    + (f" con id {ter_id}" if ter_id else "")
                    + f" (coincidencias por nombre: {candidatas_vistas}).")


@_paso("tarifa")
def _tarifa_y_adicionales(page):
    e = _esperar(page, lambda e: e.get("precio", 0) > 0, "la tarifa")
    _continuar(page)
    _esperar(page, lambda e: e.get("paso") == 3, "el paso 3 (adicionales)")
    # Sobreprotegido viene en "No deseo" y así se queda: cuesta más.
    if estado(page).get("sobreprotegido"):
        raise NoSeEnvio("El Envío Sobreprotegido quedó marcado y no debería.")
    _continuar(page)
    _esperar(page, lambda e: e.get("paso") == 4, "el paso 4 (destinatario)")
    return e["precio"]


@_paso("destinatario")
def _destinatario(page, datos):
    """DNI; si Shalom no lo conoce, nombre, apellidos y celular.

    Devuelve la separación de nombre usada (o None si Shalom ya lo conocía),
    para avisarle a Aldahir cómo quedó registrado.
    """
    # Comprobado en vivo (2026-11-09): en este paso los únicos campos que se
    # pueden escribir son los del destinatario (los del remitente vienen
    # bloqueados), con placeholder DNI, Nombre, Apellido paterno, Apellido
    # materno y Celular. Si Shalom reconoce el DNI, los cuatro últimos
    # desaparecen (quedan enmascarados) y no hay nada más que llenar.
    # Desde Vue 3 (2026-11-19) los campos se buscan dentro del bloque del
    # destinatario: el del remitente usa los mismos placeholders y, si a su
    # ficha le faltara algo, saldría como campo libre y primero en la página.
    campo = lambda ph: _bloque_destinatario(page).locator(
        f"input[placeholder='{ph}']").filter(visible=True).first
    doc = campo("DNI")
    doc.click()
    doc.fill("")
    # Shalom busca solo cuando el DNI llega a 8 números: se teclea, no se pega.
    doc.press_sequentially(datos["dni"], delay=60)
    page.wait_for_timeout(3000)
    e = estado(page)

    separado = None
    if not e.get("destinatario"):
        partes = separar_nombre(datos.get("nombre"))
        if not partes:
            raise NoSeEnvio("Shalom no conoce ese DNI y para registrarlo necesito nombre y dos "
                            "apellidos de quien recoge (ponlos completos en Cotizar).")
        for ph, valor in zip(("Nombre", "Apellido paterno", "Apellido materno"), partes):
            campo(ph).fill(valor)
        separado = {"nombres": partes[0], "paterno": partes[1], "materno": partes[2]}
    if not e.get("destinatario_tiene_celular") or not e.get("destinatario"):
        if not datos.get("celular"):
            raise NoSeEnvio("Shalom pide el celular de quien recoge y no está en Cotizar.")
        cel = campo("Celular")
        if cel.count() and cel.is_editable():
            cel.fill(datos["celular"])

    _continuar(page)
    _esperar(page, lambda e: e.get("destinatario") and e.get("paso", 0) >= 5,
             "el destinatario registrado")
    return separado


def _bloque_destinatario(page):
    """El FormClient del destinatario: el div.row más profundo que tiene su
    interruptor DNI (id dni_client_receiver; el del remitente es
    dni_client_sender). Los antepasados salen antes en la página: .last es
    el bloque mismo."""
    return page.locator("div.row").filter(has=page.locator("#dni_client_receiver")).last


@_paso("clave de seguridad")
def _hasta_la_clave(page, clave):
    """Avanza hasta el paso que crea, poniendo la clave donde aparezca.

    En vivo (2026-11-09): el paso 5 es Cobro Seguro, que ya viene en "No
    deseo el servicio" (se comprueba en la revisión final), y el 6 es el
    teclado de la clave. Si algún día Shalom muestra un "Continuar sin el
    servicio", también se pasa. Nunca se pulsa Continuar en el paso que crea.
    """
    for _ in range(4):
        e = estado(page, clave)
        if _teclado_visible(page) and not e.get("clave_ok"):
            _marcar_clave(page, clave)
        sin = page.get_by_text(re.compile("Continuar sin el servicio", re.I)).filter(visible=True)
        if sin.count():
            sin.first.click()
            page.wait_for_timeout(1200)
            continue
        if estado(page).get("paso") >= PASO_QUE_CREA:
            break
        _continuar(page)
    e = _esperar(page, lambda e: e.get("paso") == PASO_QUE_CREA, "el último paso")
    if not e.get("clave_ok"):
        if _teclado_visible(page):
            _marcar_clave(page, clave)
        _esperar(page, lambda e: e.get("clave_ok"), "la clave puesta", segundos=5, clave=clave)


def _teclado_visible(page):
    return page.locator("button.btn-outline-default").filter(
        has_text=re.compile(r"^\s*\d\s*$")).filter(visible=True).count() >= 10


def _marcar_clave(page, clave):
    """El teclado viene barajado (cambia al cargar, no entre toques): cada
    dígito se busca por su rótulo."""
    teclas = page.locator("button.btn-outline-default").filter(visible=True)
    papelera = teclas.filter(has=page.locator(".fa-trash"))
    if papelera.count():
        papelera.first.click()          # por si quedó algo a medias
    for d in clave:
        teclas.filter(has_text=re.compile(rf"^\s*{d}\s*$")).first.click()
        page.wait_for_timeout(250)


@_paso("revisión final")
def _revisar_antes_de_crear(page, datos):
    """Lo último antes de crear: todo tiene que ser lo que se pidió."""
    e = estado(page, datos["clave"])
    problemas = []
    if e.get("paso") != PASO_QUE_CREA:
        problemas.append(f"paso {e.get('paso')}")
    if e.get("producto") != NOMBRE_PRODUCTO[datos["caja"]]:
        problemas.append("caja distinta")
    if ORIGEN_ID and e.get("origen") != ORIGEN_ID:
        problemas.append("origen distinto")
    if datos.get("agencia_id") and e.get("destino") != int(datos["agencia_id"]):
        problemas.append("destino distinto")
    if not e.get("destinatario"):
        problemas.append("sin destinatario")
    if not e.get("clave_ok"):
        problemas.append("clave distinta")
    if e.get("sobreprotegido") or e.get("cobro_seguro") or e.get("declaracion"):
        problemas.append("un servicio adicional quedó marcado")
    if problemas:
        raise NoSeEnvio("Antes de crear, el formulario no cuadra: " + ", ".join(problemas) + ".")


def _esperar_resultado(page):
    """Tras el toque final: el número de orden sale en el propio formulario."""
    for _ in range(120):
        e = estado(page)
        if e.get("guia"):
            return e
        page.wait_for_timeout(500)
    # Se pulsó y no apareció: puede que sí se haya creado. Incierto.
    raise RuntimeError("Pulsé crear y no apareció el número de orden.")


def _boton_continuar(page):
    return page.get_by_role("button", name=re.compile(r"^\s*Continuar\s*$", re.I)).filter(visible=True).last


def _continuar(page):
    """Continuar en cualquier paso MENOS el que crea. Es el candado de este archivo."""
    if estado(page).get("paso") == PASO_QUE_CREA:
        raise NoSeEnvio("Iba a pulsar Continuar en el paso que crea la orden sin querer.")
    _boton_continuar(page).click()
    page.wait_for_timeout(1200)
