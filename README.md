# 📦 Avisos Shalom → WhatsApp (versión nube)

Sistema que revisa **solo, en la nube, sin tu laptop** el estado de tus pedidos de
Shalom y te avisa por **Telegram** apenas llegan a destino, con el mensaje y el
link de WhatsApp listos para enviarle al cliente.

- ✅ Corre 24/7 en GitHub Actions (**gratis**).
- ✅ No usa tu plan de Claude.
- ✅ **No registras nada**: los envíos se leen solos de tu cuenta ShalomPRO.
- ✅ Tu laptop puede estar apagada.

---

## Cómo funciona

La fuente de verdad es el portal **ShalomPRO** (`pro.shalom.pe`), que ya tiene
todo lo que antes se copiaba a mano: número de orden, código, estado y —en el
detalle de cada envío— el **celular del destinatario**.

1. Registras el envío en Shalom como siempre y lo dejas en la agencia.
2. Cada 30 min GitHub abre el portal y lee la vista de seguimiento de una sola
   carga. Los pedidos nuevos **se descubren solos**.
3. Cuando uno llega a **"En destino"**, el bot te escribe con el mensaje corto y
   un link de WhatsApp: lo tocas → se abre el chat del cliente → envías.
   Si va a domicilio ("En reparto"), el mensaje cambia solo.
4. Si un pedido lleva +5 días en tránsito, también te avisa para reclamar.
5. Cuando el pedido desaparece del seguimiento, se da por entregado y se cierra.

---

## Instalación (una sola vez, ~10 min desde el celular o PC)

### 1) Crear el bot de Telegram
1. En Telegram, busca **@BotFather** y ábrelo.
2. Envía `/newbot`, ponle un nombre y un usuario (debe terminar en `bot`).
3. BotFather te da un **TOKEN** (algo como `123456:ABC-DEF...`). Guárdalo.

### 2) Obtener tu CHAT ID
1. Busca **@userinfobot** en Telegram y ábrelo.
2. Te muestra tu **Id** (un número). Guárdalo.
3. Abre tu bot nuevo (el del paso 1) y mándale `/start` (para que pueda escribirte).

### 3) Subir este proyecto a GitHub
1. En github.com crea un repositorio nuevo (puede ser **Público**; así los minutos
   de Actions son ilimitados y gratis. Tus contraseñas NO van en el código, van en
   "Secrets", que quedan ocultos).
2. Sube toda la carpeta `shalom-avisos` (botón **Add file → Upload files**, arrastra
   los archivos, o usa Git).

### 4) Agregar los Secrets (contraseñas ocultas)
En el repo: **Settings → Secrets and variables → Actions → New repository secret**.

| Nombre                 | Valor                                    | ¿Obligatorio? |
|------------------------|------------------------------------------|---------------|
| `TELEGRAM_BOT_TOKEN`   | el token del paso 1                      | sí            |
| `TELEGRAM_CHAT_ID`     | tu id del paso 2                         | sí            |
| `SHALOM_EMAIL`         | tu correo de Shalom Pro                  | sí            |
| `SHALOM_PASSWORD`      | tu contraseña de Shalom Pro              | sí            |
| `SHALOM_STORAGE_STATE` | tu sesión ya iniciada (ver paso 5)        | **sí, en la práctica** |
| `GH_SECRETS_TOKEN`     | token para que el bot renueve su sesión   | **sí** (ver paso 6) |

> ⚠️ Nunca pongas estas claves dentro del código ni las compartas en el chat.
> Solo van aquí, en Secrets.

### 5) Guardar tu sesión de ShalomPRO (lo que hace que todo funcione)

El portal protege el login con **reCAPTCHA v3**: no pone ningún puzzle, le pone
nota al navegador de 0 a 1 según lo humano que parezca y deja pasar solo a
partir de cierto punto. Un navegador automático, encima desde una IP de centro
de datos como las de GitHub, saca nota baja y el portal responde
**"Verificación de seguridad fallida"**. Eso no se arregla con la contraseña:
la contraseña ni llega a mirarse.

La salida es no iniciar sesión desde GitHub. Inicias sesión **tú, en tu PC, en
un Chrome normal**, y el bot reutiliza esa sesión:

```
pip install playwright
python guardar_sesion.py
```

Se abre un Chrome con un perfil aparte (no toca el tuyo). Inicia sesión, espera
a ver la pantalla principal y vuelve a la consola a pulsar Enter. Genera
`sesion.json`: pega **todo** su contenido en el secret `SHALOM_STORAGE_STATE` y
luego borra el archivo.

> La casilla **"Recuérdame" no sirve de nada** aquí: Shalom no emite la cookie
> correspondiente aunque se marque. Comprobado — las únicas cookies que manda
> son `enviashalom_session` y `XSRF-TOKEN`. Por eso el paso 6 no es opcional.

> Ese archivo vale como tu sesión abierta. No lo subas al repo ni lo pases por
> chat. `.gitignore` ya lo cubre.

### 6) Que la sesión no caduque (`GH_SECRETS_TOKEN`) — obligatorio

La sesión del paso 5 **dura un par de horas**, porque lo único que la sostiene
es la cookie de sesión de Laravel. El navegador la recibe fresca en cada visita,
pero en el secret sigue la copia vieja: en cuanto esa copia vence, el bot vuelve
al formulario y a los rechazos de reCAPTCHA.

Este token lo arregla: deja que el bot se reguarde las cookies frescas antes de
que venzan. Sin él, el paso 5 hay que repetirlo a mano cada dos por tres.

Foto de perfil → **Settings** → **Developer settings** → **Personal access
tokens** → **Fine-grained tokens** → **Generate new token**

| Campo | Valor |
|---|---|
| Repository access | **Only select repositories** → `shalom-avisos` |
| Permissions → Repository → **Secrets** | **Read and write** |

Guárdalo en el secret `GH_SECRETS_TOKEN`. Ojo: el permiso es **Secrets**, no
"Actions" — están juntos en la lista pero son cosas distintas.

### 7) Encender y probar
1. Ve a la pestaña **Actions** del repo y activa los workflows si te lo pide.
2. Abre **"Revisar pedidos Shalom" → Run workflow** para probarlo al instante.
3. Deberías ver la ejecución en verde. Si tienes un pedido ya en destino, te llega
   el aviso por Telegram.

¡Listo! De ahí en adelante corre solo cada 30 minutos.

---

## Uso diario

Ninguno. Registras el envío en Shalom como siempre y el bot se entera solo.

**Comandos del bot:**
- `/listar` — ver los pedidos en curso y su estado.
- `/ayuda` — recordatorio de cómo funciona.

Para forzar una revisión: **Actions → "Revisar pedidos Shalom" → Run workflow**.
Ahí hay una casilla **"sin avisos"** que sincroniza los estados sin escribirle a
nadie — útil la primera vez, para fijar el punto de partida sin disparar avisos
de pedidos que ya atendiste a mano.

---

## Cuando dejan de llegar avisos

Lo primero, siempre: **Actions → "Diagnostico del bot" → Run workflow**. En un
minuto dice qué secret falta, si la sesión guardada sigue viva y —si el portal
no deja entrar— por qué motivo. No toca nada ni escribe a ningún cliente.

| Lo que dice | Qué pasa | Arreglo |
|---|---|---|
| `no hay sesión guardada` | El secret `SHALOM_STORAGE_STATE` está vacío. El bot depende del login automático, que el portal rechaza casi siempre. | Paso 5 de la instalación. |
| `Verificación de seguridad fallida` / motivo `recaptcha` | reCAPTCHA da por robot al navegador del bot. **No es tu contraseña.** | Paso 5: renovar la sesión. |
| `la sesión ya caducó` | La sesión guardada venció. | Paso 5 otra vez; y monta el paso 6, que es lo que evita que se repita. |
| `la sesión vence en N h y nada la va a renovar` | Falta `GH_SECRETS_TOKEN`. | Paso 6, antes de que venza. |
| motivo `credenciales` | El portal dice que el correo o la clave no valen. | Entra a mano a pro.shalom.pe y actualiza `SHALOM_EMAIL` / `SHALOM_PASSWORD`. |
| motivo `bloqueada` | La cuenta está bloqueada. | Desbloquéala en el portal; el bot solo lee. |

El propio bot ya manda por Telegram el arreglo que toca en cada caso, sin
traceback.

---

## Privacidad

Este repo es **público**, así que `orders.json` guarda **solo** datos de
logística: número de orden, código y estado. El nombre y el celular del cliente
se leen del portal en el momento del aviso, viajan al chat privado de Telegram y
**no se escriben nunca a disco ni a los logs**.

Por lo mismo, los logs enmascaran cualquier dato personal y las capturas de
error se limitan a la pantalla de login: los artifacts de un repo público los
puede descargar cualquiera.

> ⚠️ Las versiones anteriores sí guardaban nombre y teléfono en `orders.json`.
> El código actual los borra en la primera ejecución, pero **siguen visibles en
> el historial de commits** hasta que se reescriba el historial.

---

## Notas técnicas
- El estado se lee del DOM del portal con Playwright. La API interna
  (`/service-orders/shipments/tracking`) no sirve: exige cabeceras firmadas con
  HMAC (`X-API-KEY`, `X-NONCE`, `X-TIMESTAMP`, `X-SIGNATURE`) y además devuelve
  el cuerpo encriptado. Sin ellas responde `401 Missing headers`.
- El login del portal usa **reCAPTCHA v3** (por score, sin puzzle). Al principio
  un Chromium headless lo pasaba desde GitHub, luego solo ~1 de cada 3 veces, y
  desde el 21-08-2026 ninguna. Comprobado el 22-08-2026 con Chrome de marca, con
  ventana y sin mentir en la huella: sigue rechazando. **Desde una IP de GitHub
  el formulario ya no pasa**, así que `SHALOM_STORAGE_STATE` no es el plan B, es
  el único camino; el login automático solo queda por si algún día vuelve a
  colar.
- La casilla **"Recuérdame" del portal no emite ninguna cookie**: se marque o
  no, las únicas que llegan son `enviashalom_session` y `XSRF-TOKEN`. O sea que
  no hay sesión de larga duración que valga, y la renovación automática del
  secret (paso 6) no es una comodidad sino el mecanismo que sostiene todo.
  Por eso se renueva mirando **la caducidad real de las cookies**, no cada N
  horas fijas: con un plazo fijo de 12 h la copia del secret vencía mucho antes
  de que le tocara turno.
- Por lo mismo, un rechazo de reCAPTCHA **no se reintenta dentro de la misma
  corrida**: la nota sale de la IP y de la huella, y ninguna cambia en diez
  segundos (se vio 3 de 3 con el mismo rechazo). Insistir solo sumaría logins
  fallidos contra la cuenta. La corrida siguiente cae en otro runner y esa sí
  es una oportunidad nueva.
- Lo que sube esa nota, y por qué está puesto así en el código:
  **Chrome de marca** (canal `chrome`) en vez del Chromium de Playwright;
  **con ventana** sobre Xvfb en vez de headless; **sin mentir en el user-agent**
  (antes anunciaba Windows y Chrome 126 corriendo Chromium 130 sobre Linux — esa
  contradicción sola ya delata la automatización, porque las client hints
  siguen diciendo la verdad); y escribir el formulario tecla a tecla, que es lo
  único que genera los eventos que reCAPTCHA espera de una persona.
- La vista de seguimiento solo muestra envíos **activos**; los entregados pasan
  al historial. Por eso la lista se mantiene corta sola.
- Ojo al tocar los selectores: la página renderiza el layout de escritorio
  (`.shipment-row`) y el de móvil (`.shipment-card__*`) a la vez. Y el panel de
  detalle **no se cierra con Escape**, hay que pulsar `.drawer__close-btn`.
- `shalom_tracker.py` (rastreo público, pedido por pedido) queda como plan B por
  si el portal cambia; ya no se usa.
- Ajustes en `revisar.py`: `DEMORA_DIAS`, `AVISAR_EN`.
