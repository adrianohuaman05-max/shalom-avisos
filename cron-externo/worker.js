/**
 * Disparador externo para el bot de avisos Shalom.
 *
 * Por que existe: GitHub Actions se salta la mayoria de los disparos
 * programados en repos gratuitos — de ~237 esperados solo llegaron 58. Los
 * disparos manuales (workflow_dispatch), en cambio, no se descartan nunca.
 * Este Worker hace de despertador fiable: llama a la API de GitHub cada media
 * hora y GitHub ejecuta la revision si o si.
 *
 * De paso compensa el otro problema: el portal rechaza el login automatizado
 * mas o menos 2 de cada 3 veces, y como el rechazo depende de la IP que le
 * toque al runner, mas intentos = mas entradas buenas.
 *
 * Necesita un secret llamado GH_TOKEN: un token de GitHub de alcance fino,
 * solo sobre el repo shalom-avisos y solo con permiso "Actions: write".
 *
 * Plan gratuito de Cloudflare: 5 cron triggers y 100.000 peticiones al dia.
 * Esto usa 1 trigger y ~48 peticiones diarias.
 */

const REPO = "adrianohuaman05-max/shalom-avisos";
const WORKFLOW = "revisar.yml";

async function dispararRevision(env) {
  const url =
    `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`;

  const respuesta = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      // GitHub rechaza las peticiones sin User-Agent.
      "User-Agent": "shalom-avisos-cron",
    },
    body: JSON.stringify({ ref: "main" }),
  });

  // 204 = aceptado. Cualquier otra cosa se registra para poder mirarlo luego
  // en los logs del Worker.
  if (respuesta.status !== 204) {
    const detalle = await respuesta.text();
    console.log(`Fallo al disparar (${respuesta.status}): ${detalle}`);
  } else {
    console.log("Revision disparada.");
  }
  return respuesta.status;
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispararRevision(env));
  },
};
