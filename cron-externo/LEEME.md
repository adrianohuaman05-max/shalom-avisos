# Disparador externo (Cloudflare Workers)

## Para qué es

GitHub Actions **se salta la mayoría de los disparos programados** en repos
gratuitos: de ~237 esperados en un periodo, solo se ejecutaron 58. Los disparos
manuales, en cambio, no se descartan nunca.

Este Worker llama a GitHub cada 30 minutos, y GitHub ejecuta la revisión sí o sí.

De paso compensa el otro problema: el portal rechaza el login automatizado unas
2 de cada 3 veces, y como el rechazo depende de la IP que le toque al runner,
más intentos significan más entradas buenas.

| | Antes | Después |
|---|---|---|
| Intentos al día | ~12 | ~48 |
| Entradas buenas | ~4 | ~17 |
| Retraso del aviso | ~6 h | ~1,5 h |

## Coste

Cero. El plan gratuito de Cloudflare Workers incluye 5 cron triggers y 100.000
peticiones al día. Esto usa 1 trigger y ~48 peticiones diarias.

## Montaje

### 1. Crear el token de GitHub

Foto de perfil → **Settings** → **Developer settings** → **Personal access
tokens** → **Fine-grained tokens** → **Generate new token**

| Campo | Valor |
|---|---|
| Token name | `cron-shalom` |
| Expiration | lo más largo que permita |
| Repository access | **Only select repositories** → `shalom-avisos` |
| Permissions → Repository → **Actions** | **Read and write** |

Nada más. Copia el token: solo se muestra una vez.

### 2. Crear el Worker

1. Entra en [dash.cloudflare.com](https://dash.cloudflare.com) (cuenta gratis)
2. **Compute (Workers)** → **Create** → **Start with Hello World** → **Deploy**
3. Ponle de nombre `shalom-cron`
4. **Edit code**, borra todo y pega el contenido de `worker.js`
5. **Deploy**

### 3. Guardar el token en el Worker

En el Worker → **Settings** → **Variables and Secrets** → **Add**

- Type: **Secret**
- Name: `GH_TOKEN`
- Value: el token del paso 1

**Deploy** otra vez para que lo tome.

### 4. Programar el disparo

En el Worker → **Settings** → **Trigger Events** → **Add** → **Cron Trigger**

```
*/30 * * * *
```

(cada 30 minutos)

### 5. Comprobar

En el Worker, pestaña **Logs** → **Begin log stream**. En el próximo disparo
debe aparecer `Revision disparada.`

Y en GitHub → **Actions**, las corridas nuevas saldrán como
**workflow_dispatch** en vez de **schedule**.

## Si algo falla

Los logs del Worker dicen el código de error:

| Código | Qué pasa |
|---|---|
| `401` | El token no vale o caducó |
| `403` | Al token le falta el permiso **Actions: write** |
| `404` | El nombre del repo o del workflow no coincide |
| `422` | La rama `main` no existe |

## Seguridad

El token solo puede lanzar workflows en **este repo**. No puede leer tus
secrets (GitHub no permite leerlos a nadie), ni tocar tu código, ni acceder a
otros repos.

Se revoca en la misma pantalla donde se creó, y el bot seguiría funcionando
igual — solo volvería a depender del cron de GitHub, como antes.
