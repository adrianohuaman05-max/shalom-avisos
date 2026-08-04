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
Crea estos cuatro:

| Nombre                | Valor                                   |
|-----------------------|-----------------------------------------|
| `TELEGRAM_BOT_TOKEN`  | el token del paso 1                     |
| `TELEGRAM_CHAT_ID`    | tu id del paso 2                        |
| `SHALOM_EMAIL`        | tu correo de Shalom Pro                 |
| `SHALOM_PASSWORD`     | tu contraseña de Shalom Pro             |

> ⚠️ Nunca pongas estas claves dentro del código ni las compartas en el chat.
> Solo van aquí, en Secrets.

### 5) Encender y probar
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
- El login del portal usa **reCAPTCHA v3** (por score, sin puzzle). Comprobado
  que un Chromium headless lo pasa desde una IP de GitHub.
- La vista de seguimiento solo muestra envíos **activos**; los entregados pasan
  al historial. Por eso la lista se mantiene corta sola.
- Ojo al tocar los selectores: la página renderiza el layout de escritorio
  (`.shipment-row`) y el de móvil (`.shipment-card__*`) a la vez. Y el panel de
  detalle **no se cierra con Escape**, hay que pulsar `.drawer__close-btn`.
- `shalom_tracker.py` (rastreo público, pedido por pedido) queda como plan B por
  si el portal cambia; ya no se usa.
- Ajustes en `revisar.py`: `DEMORA_DIAS`, `AVISAR_EN`.
