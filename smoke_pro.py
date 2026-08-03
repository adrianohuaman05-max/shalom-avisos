# -*- coding: utf-8 -*-
"""
Prueba de humo del portal ShalomPRO — se corre A MANO desde Actions, no en cron.

Responde la única pregunta que decide si la automatización es viable:
¿puede un Chromium headless, desde una IP de GitHub, loguearse en
pro.shalom.pe (que usa reCAPTCHA v3 por score) y leer los envíos?

Si esto pasa, se reescribe revisar.py sobre shalompro.py.
Si falla, hay plan B (reutilizar cookies de sesión guardadas como secret).

Los logs de Actions son PÚBLICOS en este repo: todo dato personal va enmascarado.
"""
import re
import sys
import traceback

from shalompro import ShalomPro


def tapar(valor, visibles=2):
    """Deja ver lo justo para verificar que se leyó bien, sin exponer el dato."""
    v = (valor or "").strip()
    if not v:
        return "(vacío)"
    if len(v) <= visibles:
        return "*" * len(v)
    return v[:visibles] + "*" * (len(v) - visibles)


def main():
    print("=" * 60)
    print("PRUEBA 1/3 — login en pro.shalom.pe")
    print("=" * 60)
    with ShalomPro(headless=True) as pro:
        print("OK: login correcto, reCAPTCHA v3 no bloqueó.\n")

        print("=" * 60)
        print("PRUEBA 2/3 — leer /seguimientoenvios")
        print("=" * 60)
        envios = pro.listar()
        print(f"Envíos activos encontrados: {len(envios)}")
        for e in envios:
            print(f"  [{e['orden']}] cod={e['codigo']} · {e['estado']} · "
                  f"{e['fecha']} · {e['monto']}")
        if not envios:
            print("\nNo hay envíos activos. La lectura funcionó, pero para validar "
                  "el detalle hace falta al menos un envío en curso.")
            return 0

        print()
        print("=" * 60)
        print("PRUEBA 3/3 — detalle (¿trae el celular?)")
        print("=" * 60)
        orden = envios[0]["orden"]
        d = pro.detalle(orden)
        if not d:
            print(f"FALLO: no se pudo abrir el detalle de {orden}")
            return 1

        tel = re.sub(r"\D", "", d.get("telefono", ""))
        print(f"  orden          : {d['orden']}")
        print(f"  codigo         : {d['codigo']}")
        print(f"  fecha          : {d['fecha']}")
        print(f"  destinatario   : {tapar(d['destinatario'])}")
        print(f"  dni            : {tapar(d['dni'])}")
        print(f"  telefono       : {tapar(tel)}  (largo={len(tel)})")
        print(f"  forma_entrega  : {d['forma_entrega']}")
        print(f"  origen         : {d['origen']}")
        print(f"  destino        : {d['destino']}")
        print(f"  destino_ubigeo : {d['destino_ubigeo']}")

        # Lo único que importa de verdad: que el teléfono sirva para wa.me.
        if len(tel) == 9 and tel.startswith("9"):
            print("\nOK: el celular se leyó completo y con formato de móvil peruano.")
            print("=> La automatización puede ser 100%: no hace falta registrar nada a mano.")
            return 0

        print(f"\nAVISO: el teléfono no tiene el formato esperado (9 dígitos "
              f"empezando en 9). Se leyeron {len(tel)} dígitos.")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print("\nFALLÓ LA PRUEBA:\n")
        traceback.print_exc()
        print("\nRevisa el artifact 'capturas' para ver la pantalla del fallo.")
        sys.exit(1)
