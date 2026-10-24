"""Inclina la caja de refinamiento de estela segun el angulo de ataque.

Problema
--------
La caja de refinamiento actual es horizontal y fija:

    YMin = -0.06*chord
    YMax = +0.06*chord

Pero la estela de un perfil a incidencia NO sale horizontal: se desvia hacia
abajo aproximadamente alpha/2 (condicion de Kutta). A alpha=8 la estela baja
unos 4 grados, que a 10 cuerdas son 0.7c de descenso. La caja solo cubre
+-0.06c, asi que la estela se sale del refinamiento a las 2-3 cuerdas.

Resultado medido:
    alpha=0:  estela por y=0, dentro de la caja  ->  Cd +34.5%
    alpha=4:  desviacion ~2 grados, casi cabe     ->  Cd +0.6%
    alpha=8:  desviacion ~4 grados, se sale       ->  Cd +331%

Solucion
--------
Girar la caja alpha/2 alrededor del borde de salida. gmsh no tiene una caja
rotada nativa, asi que se usa un campo `MathEval` que calcula la distancia a
la linea central de la estela inclinada.

Alternativa mas simple y robusta: ampliar la caja verticalmente lo suficiente
para contener la estela desviada hasta la salida del dominio. El coste es mas
celdas, pero no requiere geometria nueva.
"""

from __future__ import annotations
import math


def caja_estela_ampliada(aoa_deg: float, wake_length: float, chord: float,
                         farfield: float, mesh_size: float):
    """Devuelve los parametros de una caja que contiene la estela desviada.

    Se calcula el descenso de la estela en el extremo del dominio aplicando
    la desviacion clasica alpha/2, y se amplia la caja para cubrirlo con un
    margen.
    """
    # desviacion de la estela: ~alpha/2 hacia abajo
    desv_rad = math.radians(abs(aoa_deg) / 2.0)
    desv_y = (wake_length - chord) * math.tan(desv_rad)

    # semialtura necesaria: la nominal (0.06c) mas la desviacion, con margen
    semi = max(0.06 * chord, desv_y * 1.25 + 0.06 * chord)

    return {
        "XMin": 1.0 * chord,
        "XMax": wake_length,
        "YMin": -semi,
        "YMax": +0.06 * chord,
        "ZMin": -1.0,
        "ZMax": 1.0,
        "Thickness": 0.30 * chord,
        "VIn": mesh_size * 1.5,
        "VOut": farfield,
        "semi_altura": semi,
        "desviacion_y": desv_y,
    }


if __name__ == "__main__":
    print("=== Caja de estela segun el angulo ===")
    print(f"{'alpha':>6} {'desv. y':>10} {'semi-alto':>11} {'vs actual':>10}")
    print("-" * 42)
    for a in (0, 4, 8, 12, 15):
        c = caja_estela_ampliada(a, 30.0, 1.0, 0.4, 0.008)
        ratio = c["semi_altura"] / 0.06
        print(f"{a:6.0f} {c['desviacion_y']:10.3f} {c['semi_altura']:11.3f} "
              f"{ratio:9.1f}x")
