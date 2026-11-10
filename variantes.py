# -*- coding: utf-8 -*-
"""
Qué versión del aviso de llegada le toca a cada cliente.

El aviso tiene varias versiones (mensajes.LLEGADA_AGENCIA y LLEGADA_REPARTO).
Elegirlas al azar no basta: con seis textos, a un cliente que vuelve le caería
el mismo que la vez anterior una de cada seis veces. Para que eso no pase hay
que recordar cuál fue el último que recibió cada uno, y darle el siguiente.

PRIVACIDAD: esa memoria no va al repo. Aunque no lleve el celular, dejaría ver
en el historial público qué pedidos son del mismo cliente. Se guarda en el
secret AVISOS_VARIANTES, igual que la sesión: cifrado, y solo lo lee el propio
bot. Dentro tampoco hay celulares, solo un resumen de cada uno:

    {"3f9a1c0b7e": 2, "a41d6e2290": 5}

Si no hay dónde guardarla (falta GH_SECRETS_TOKEN) el bot no se queda mudo:
elige la versión según el número de orden, que al menos cambia de un pedido a
otro.
"""
import hashlib
import json
import os

import mensajes
import renovacion

NOMBRE_SECRET = "AVISOS_VARIANTES"

# Un secret admite 48 KB y cada cliente ocupa unos 16 bytes. Con este tope no
# se llega nunca: si se llenara, salen los que hace más que no compran.
MAX_CLIENTES = 2000


def id_cliente(telefono):
    """Resumen del celular: sirve para reconocer al cliente, no para llamarlo."""
    digitos = mensajes.fmt_wa(telefono or "")
    if not digitos:
        return ""
    return hashlib.sha256(digitos.encode("utf-8")).hexdigest()[:10]


def por_orden(orden, cuantas):
    """Versión que sale del número de orden: fija para un pedido, distinta
    entre pedidos. Es el punto de partida y el plan B sin memoria."""
    resumen = hashlib.sha256(str(orden).encode("utf-8")).hexdigest()
    return int(resumen, 16) % cuantas


class Memoria:
    """La última versión que recibió cada cliente."""

    def __init__(self, texto=None, persistente=None):
        if texto is None:
            texto = os.environ.get(NOMBRE_SECRET, "")
        self.persistente = (renovacion.disponible() if persistente is None
                            else persistente)
        self.cambiada = False
        try:
            datos = json.loads(texto) if texto.strip() else {}
        except ValueError:
            # Un secret estropeado no puede tumbar los avisos: se empieza de cero.
            print("La memoria de versiones del aviso no se pudo leer; "
                  "se empieza de cero.")
            datos = {}
        self.datos = datos if isinstance(datos, dict) else {}

    def elegir(self, telefono, orden, cuantas):
        """Devuelve el índice de la versión para este aviso y lo deja anotado."""
        if cuantas <= 1:
            return 0
        cliente = id_cliente(telefono)
        # Sin dónde guardar, "recordar" sería peor que no hacerlo: en cada
        # corrida el cliente parecería nuevo y le caería siempre la misma.
        if not cliente or not self.persistente:
            return por_orden(orden, cuantas)

        ultima = self.datos.pop(cliente, None)
        if isinstance(ultima, int):
            variante = (ultima + 1) % cuantas
        else:
            # Primera vez: sale del pedido Y del cliente. Solo del pedido se
            # podría recalcular desde fuera (el número de orden es público, y
            # la versión de cada pedido queda en orders.json), y comparando
            # se vería qué pedidos son de clientes que repiten.
            variante = por_orden(f"{orden}/{cliente}", cuantas)

        # Se reinserta al final: el orden del diccionario es el de la última
        # compra, y eso es lo que permite recortar por los más antiguos.
        self.datos[cliente] = variante
        while len(self.datos) > MAX_CLIENTES:
            del self.datos[next(iter(self.datos))]
        self.cambiada = True
        return variante

    def guardar(self):
        """Sube la memoria al secret si cambió. True si quedó guardada."""
        if not self.cambiada:
            return True
        if not self.persistente:
            return False
        texto = json.dumps(self.datos, separators=(",", ":"))
        if renovacion.guardar_secret(NOMBRE_SECRET, texto):
            self.cambiada = False
            # El log es público: solo la cuenta, ningún resumen.
            print(f"Versiones del aviso: memoria guardada "
                  f"({len(self.datos)} cliente(s)).")
            return True
        print("No se pudo guardar qué versión del aviso recibió cada cliente; "
              "puede repetirse alguna.")
        return False
