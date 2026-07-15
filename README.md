# 📦 Avisos Shalom → WhatsApp (versión nube)

Sistema que revisa **solo, en la nube, sin tu laptop** el estado de tus pedidos de
Shalom y te avisa por **Telegram** apenas llegan a destino, con el mensaje y el
link de WhatsApp listos para enviarle al cliente.

- ✅ Corre 24/7 en GitHub Actions (**gratis**).
- ✅ No usa tu plan de Claude.
- ✅ Todo desde tu **celular** (registras pedidos y recibes avisos por Telegram).
- ✅ Tu laptop puede estar apagada.

---

## Cómo funciona

1. Le mandas al **bot de Telegram** los datos de un envío nuevo.
2. Cada 30 min, GitHub revisa en Shalom los pedidos pendientes (que ya tengan +24h).
3. Cuando un pedido llega a **"En destino"**, el bot te escribe con el mensaje corto
   y un link de WhatsApp: lo tocas → se abre el chat del cliente → envías.
4. Si un pedido lleva +5 días en tránsito, también te avisa para reclamar.

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

**Registrar un pedido nuevo** — mándale al bot (puedes copiar y editar):

```
Orden: 87137991
Codigo: 9DCJ
Cliente: Brenda Gonzales
Telefono: 982302017
Destino: Chala
```

**Otros comandos del bot:**
- `/listar` — ver tus pedidos pendientes.
- `/ayuda` — ver el formato para registrar.

---

## Notas técnicas
- El estado se lee de la web logueada de Shalom (su API usa reCAPTCHA + respuesta
  encriptada, por eso se usa un navegador headless con Playwright).
- Estado y pedidos se guardan en `orders.json` / `state.json` (GitHub los versiona).
- **Riesgo conocido:** si Shalom llegara a bloquear al servidor de GitHub por el
  reCAPTCHA, el plan B es usar una API de Shalom de terceros (de pago). En las
  ejecuciones fallidas se guarda una captura (`debug-screens`) para diagnosticar.
- Ajustes en `revisar.py`: `CHECK_EVERY_HOURS`, `MIN_AGE_HOURS`, `DEMORA_DIAS`.
