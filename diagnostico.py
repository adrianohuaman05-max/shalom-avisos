# -*- coding: utf-8 -*-
"""
Revisión de salud del bot. Se corre A MANO (workflow "Diagnóstico del bot").

Responde en un vistazo lo que antes había que sacar leyendo el traceback de una
corrida caída: qué secrets faltan, si la sesión guardada sigue viva, y —si el
portal no deja entrar— cuál de los motivos posibles es.

No toca orders.json, no escribe estado y no manda nada a Telegram salvo que se
le pase --telegram.

Los logs de Actions de este repo son PÚBLICOS: aquí no se imprime ningún valor
de secret, ninguna cookie y ningún dato de cliente. Solo si están o no están.
"""
import json
import os
import sys
import time

SECRETS = [
    ("TELEGRAM_BOT_TOKEN", True, "sin esto el bot no puede escribirte"),
    ("TELEGRAM_CHAT_ID", True, "sin esto no sabe a quién escribirte"),
    ("SHALOM_EMAIL", True, "usuario del portal"),
    ("SHALOM_PASSWORD", True, "clave del portal"),
    ("SHALOM_STORAGE_STATE", False,
     "sesión ya iniciada; es el ÚNICO camino fiable, porque reCAPTCHA rechaza "
     "el login automático desde los runners"),
    ("GH_SECRETS_TOKEN", False,
     "deja que el bot renueve solo SHALOM_STORAGE_STATE y no caduque nunca"),
]

problemas = []
avisos = []


def titulo(texto):
    print("\n" + "=" * 62)
    print(texto)
    print("=" * 62)


def revisar_secrets():
    titulo("1/3 — Secrets")
    for nombre, obligatorio, para_que in SECRETS:
        valor = os.environ.get(nombre, "").strip()
        if valor:
            print(f"  OK     {nombre} ({len(valor)} caracteres)")
        elif obligatorio:
            print(f"  FALTA  {nombre} — {para_que}")
            problemas.append(f"falta el secret {nombre}")
        else:
            print(f"  VACÍO  {nombre} — {para_que}")
            avisos.append(f"{nombre} sin configurar")


def revisar_sesion():
    """Mira la sesión guardada sin abrir el navegador: nombres y caducidades."""
    titulo("2/3 — Sesión guardada (SHALOM_STORAGE_STATE)")
    crudo = os.environ.get("SHALOM_STORAGE_STATE", "").strip()
    if not crudo:
        print("  No hay sesión guardada.")
        print("  Sin ella el bot tiene que iniciar sesión en cada corrida, y")
        print("  eso es justo lo que reCAPTCHA v3 rechaza desde GitHub.")
        print("  Arreglo: python guardar_sesion.py  →  pegar en el secret.")
        problemas.append("no hay sesión guardada (SHALOM_STORAGE_STATE vacío)")
        return

    try:
        estado = json.loads(crudo)
    except Exception as e:
        print(f"  NO es JSON válido ({type(e).__name__}).")
        print("  ¿Se pegó el archivo entero, sin cortar y sin comillas de más?")
        problemas.append("SHALOM_STORAGE_STATE no es JSON válido")
        return

    cookies = [c for c in (estado.get("cookies") or [])
               if "shalom" in (c.get("domain") or "")]
    if not cookies:
        print("  Es JSON, pero no trae ninguna cookie de shalom.pe.")
        problemas.append("SHALOM_STORAGE_STATE sin cookies de shalom.pe")
        return

    ahora = time.time()
    print(f"  {len(cookies)} cookie(s) de shalom.pe:")
    for c in sorted(cookies, key=lambda x: x.get("name", "")):
        exp = c.get("expires") or 0
        if exp <= 0:
            cuando = "de sesión (muere al cerrar el navegador)"
        elif exp <= ahora:
            cuando = "CADUCADA"
        else:
            dias = (exp - ahora) / 86400.0
            cuando = f"caduca en {dias:.1f} días"
        print(f"    · {c.get('name', '?')} — {cuando}")

    if all((c.get("expires") or 0) <= ahora for c in cookies
           if (c.get("expires") or 0) > 0):
        problemas.append("todas las cookies guardadas están caducadas")
    if not any(str(c.get("name", "")).startswith("remember_") for c in cookies):
        print("  Aviso: no hay cookie de 'Recuérdame'. Durará poco.")
        avisos.append("la sesión guardada no marcó 'Recuérdame'")


def revisar_portal():
    titulo("3/3 — Entrada al portal")
    try:
        from shalompro import ShalomPro
    except Exception as e:
        print(f"  No se pudo importar shalompro ({type(e).__name__}: {e}).")
        problemas.append("shalompro no importa (¿falta instalar playwright?)")
        return

    try:
        with ShalomPro(headless=True) as pro:
            print("  OK: se entró al portal.")
            envios = pro.listar()
            print(f"  Envíos activos en seguimiento: {len(envios)}")
            for e in envios:
                # Solo logística: nada del destinatario.
                print(f"    · {e['orden']} · {e['codigo']} · {e['estado']}")
            if not envios:
                print("  (Ninguno activo. No es un fallo: los entregados salen "
                      "de esta vista.)")
    except Exception as e:
        motivo = getattr(e, "motivo", "")
        print(f"  FALLO: {e}")
        if motivo:
            print(f"  Motivo identificado: {motivo}")
        problemas.append(f"no se pudo entrar al portal ({motivo or 'desconocido'})")


def main():
    revisar_secrets()
    revisar_sesion()
    revisar_portal()

    titulo("Resumen")
    if not problemas:
        print("  Todo en orden." + (
            f" Avisos menores: {'; '.join(avisos)}." if avisos else ""))
    else:
        print("  Hay que arreglar:")
        for p in problemas:
            print(f"    · {p}")
        if avisos:
            print("  Además, conviene mirar:")
            for a in avisos:
                print(f"    · {a}")

    if "--telegram" in sys.argv:
        import telegram_bot as tg
        if problemas:
            cuerpo = "\n".join(f"• {p}" for p in problemas)
            tg.send_message(f"🩺 <b>Diagnóstico del bot</b>\n\n"
                            f"Hay que arreglar:\n{cuerpo}")
        else:
            tg.send_message("🩺 <b>Diagnóstico del bot</b>\n\nTodo en orden. ✅")

    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
