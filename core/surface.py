"""Cp y Cf sobre el perfil, leidos del ultimo tiempo escrito del caso.

Se leen el campo p y wallShearStress en las caras del parche y su geometria de
polyMesh, sin depender de un visor. x/c e y/c se dan en el sistema del perfil.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Tuple

import numpy as np

from core.yplus import (PARCHE, YPlusError, _caras, _leer, _puntos, _rango_parche,
                        _ultimo_tiempo_con, _vectores_de_parche)


@dataclass
class SurfaceData:
    x: np.ndarray       # centro de cara
    y: np.ndarray
    cp: np.ndarray
    cf: np.ndarray      # con signo: positivo si la friccion va hacia el borde de salida
    upper: np.ndarray   # mascara del extrados


def _escalares_de_parche(ruta: str, parche: str, n: int) -> np.ndarray:
    texto = _leer(ruta)
    resto = texto[texto.index("boundaryField"):]
    m = re.search(rf"\b{parche}\s*\{{", resto)
    if not m:
        raise YPlusError(f"{os.path.basename(ruta)} no tiene el parche {parche}")
    bloque = resto[m.end():]
    no_uniforme = re.search(r"value\s+nonuniform\s+List<scalar>\s*\d+\s*\(", bloque[:400])
    if no_uniforme:
        cuerpo = bloque[no_uniforme.end():]
        datos = np.array(cuerpo[:cuerpo.index(")")].split(), dtype=float)
    else:
        # zeroGradient no escribe value: el valor en la pared es el de la celda
        raise YPlusError(f"{os.path.basename(ruta)}: el parche {parche} no trae valores")
    if len(datos) != n:
        raise YPlusError(f"{os.path.basename(ruta)}: {len(datos)} valores para {n} caras")
    return datos


def _campo_interno(ruta: str) -> np.ndarray:
    texto = _leer(ruta)
    m = re.search(r"internalField\s+nonuniform\s+List<scalar>\s*\d+\s*\(", texto)
    if not m:
        raise YPlusError(f"{os.path.basename(ruta)} no trae un campo no uniforme")
    cuerpo = texto[m.end():]
    return np.array(cuerpo[:cuerpo.index(")")].split(), dtype=float)


def read_surface(case_dir: str, u_inf: float, chord: float = 1.0,
                 parche: str = PARCHE) -> SurfaceData:
    """Cp y Cf en cada cara del perfil para una velocidad de referencia."""
    polymesh = os.path.join(case_dir, "constant", "polyMesh")
    inicio, n = _rango_parche(polymesh, parche)
    puntos = _puntos(os.path.join(polymesh, "points"))
    caras = _caras(os.path.join(polymesh, "faces"))
    from core.yplus import _enteros
    owner = _enteros(os.path.join(polymesh, "owner"))

    tiempo = _ultimo_tiempo_con(case_dir, "wallShearStress")
    centros = np.empty((n, 3))
    normales = np.empty((n, 3))
    for i in range(n):
        p = puntos[np.array(caras[inicio + i].split(), dtype=np.int64)]
        centros[i] = p.mean(axis=0)
        normales[i] = 0.5 * np.cross(p[2] - p[0], p[3] - p[1])
    # Las caras de contorno miran hacia fuera del fluido: hacia dentro del perfil.
    normales /= -np.linalg.norm(normales, axis=1)[:, None]

    tau = _vectores_de_parche(os.path.join(case_dir, tiempo, "wallShearStress"), parche, n)
    # p en la pared: zeroGradient, igual al de la celda vecina.
    campo = _campo_interno(os.path.join(case_dir, tiempo, "p"))
    p_pared = campo[owner[inicio:inicio + n]]
    q = 0.5 * u_inf ** 2

    x, y = centros[:, 0] / chord, centros[:, 1] / chord
    upper = normales[:, 1] > 0
    # Tangente hacia el borde de salida.
    tangente = np.column_stack([np.where(upper, normales[:, 1], -normales[:, 1]),
                                np.where(upper, -normales[:, 0], normales[:, 0])])
    # wallShearStress es la fuerza de la pared sobre el fluido: se opone a la corriente.
    signo = -np.sum(tau[:, :2] * tangente, axis=1)
    cf = np.sign(signo) * np.linalg.norm(tau, axis=1) / q
    return SurfaceData(x, y, p_pared / q, cf, upper)


def integrated_coefficients(s: SurfaceData) -> Tuple[float, float]:
    """Sustentacion de presion por integracion en x de Cp, comprobacion de orden de magnitud."""
    orden_sup, orden_inf = np.argsort(s.x[s.upper]), np.argsort(s.x[~s.upper])
    xs, cps = s.x[s.upper][orden_sup], s.cp[s.upper][orden_sup]
    xi, cpi = s.x[~s.upper][orden_inf], s.cp[~s.upper][orden_inf]
    malla = np.linspace(0.0, 1.0, 2001)
    dif = np.interp(malla, xi, cpi) - np.interp(malla, xs, cps)
    return float(np.trapezoid(dif, malla)), float(np.trapezoid(dif * (0.25 - malla), malla))
