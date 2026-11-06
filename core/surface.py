"""Cp y Cf sobre el perfil, leidos del ultimo tiempo escrito del caso.

Se leen el campo p y wallShearStress en las caras del parche y su geometria de
polyMesh, sin depender de un visor. x/c e y/c se dan en el sistema del perfil.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

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
    tau: np.ndarray = None    # wallShearStress (x, y), fuerza de la pared sobre el fluido / rho
    area: np.ndarray = None   # area de cada cara / (cuerda * envergadura)


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
    z = puntos[:, 2]
    envergadura = float(z.max() - z.min()) or 1.0
    area = np.linalg.norm(0.5 * np.cross(  # normales ya normalizadas: se recalcula el area
        *[np.array([puntos[np.array(caras[inicio + i].split(), dtype=np.int64)][k]
                    - puntos[np.array(caras[inicio + i].split(), dtype=np.int64)][k - 2]
                    for i in range(n)]) for k in (2, 3)]), axis=1) / (chord * envergadura)

    x, y = centros[:, 0] / chord, centros[:, 1] / chord
    upper = normales[:, 1] > 0
    # Tangente hacia el borde de salida.
    tangente = np.column_stack([np.where(upper, normales[:, 1], -normales[:, 1]),
                                np.where(upper, -normales[:, 0], normales[:, 0])])
    # wallShearStress es la fuerza de la pared sobre el fluido: se opone a la corriente.
    signo = -np.sum(tau[:, :2] * tangente, axis=1)
    cf = np.sign(signo) * np.linalg.norm(tau, axis=1) / q
    return SurfaceData(x, y, p_pared / q, cf, upper, tau[:, :2] / q, area)


def integrated_coefficients(s: SurfaceData) -> Tuple[float, float]:
    """Sustentacion de presion por integracion en x de Cp, comprobacion de orden de magnitud."""
    orden_sup, orden_inf = np.argsort(s.x[s.upper]), np.argsort(s.x[~s.upper])
    xs, cps = s.x[s.upper][orden_sup], s.cp[s.upper][orden_sup]
    xi, cpi = s.x[~s.upper][orden_inf], s.cp[~s.upper][orden_inf]
    malla = np.linspace(0.0, 1.0, 2001)
    dif = np.interp(malla, xi, cpi) - np.interp(malla, xs, cps)
    return float(np.trapezoid(dif, malla)), float(np.trapezoid(dif * (0.25 - malla), malla))


def friction_drag(s: SurfaceData, aoa: float) -> float:
    """Parte de Cd debida a la friccion; el resto del Cd total es de presion."""
    e = np.array([np.cos(np.radians(aoa)), np.sin(np.radians(aoa))])
    # Sobre el perfil actua -tau por unidad de area.
    return float(-np.sum((s.tau @ e) * s.area))


def transition_location(s: SurfaceData, upper: bool = True,
                        x_min: float = 0.02, x_max: float = 0.95) -> Optional[Dict[str, float]]:
    """Transicion de una cara a partir de Cf: "subida" es donde Cf crece mas rapido con x,
    "inicio" el minimo de Cf antes de ella. None si Cf no sube de forma clara (turbulenta desde
    el borde de ataque, o sin transicion antes de x_max)."""
    cara = s.upper if upper else ~s.upper
    x, cf = s.x[cara], s.cf[cara]
    orden = np.argsort(x)
    x, cf = x[orden], cf[orden]
    dentro = (x > x_min) & (x < x_max)
    x, cf = x[dentro], cf[dentro]
    if len(x) < 10:
        return None
    pendiente = np.gradient(cf, x)
    k = int(np.argmax(pendiente))
    i = int(np.argmin(cf[:k + 1]))
    pico = float(cf[k:].max())
    # Un salto real de laminar a turbulenta multiplica Cf; el ruido de una capa turbulenta no.
    # En el borde del tramo (junto al punto de remanso) Cf sube sin que haya transicion.
    if i == 0 or pico - cf[i] < 0.5 * pico or pico <= 0:
        return None
    return {"inicio": float(x[i]), "subida": float(x[k])}


def surface_summary(case_dir: str) -> Optional[Dict]:
    """Cd de friccion y, con SST-LM, transicion en cada cara, con los parametros de la ficha."""
    import json
    with open(os.path.join(case_dir, "ficha.json")) as f:
        p = json.load(f).get("parametros", {})
    aoa = float(p.get("aoa", 0.0))
    s = read_surface(case_dir, float(p.get("u_inlet", 15.0)), float(p.get("chord", 1.0)))
    resumen: Dict = {"cd_friccion": friction_drag(s, aoa)}
    if os.path.exists(os.path.join(case_dir, "0", "ReThetat")):
        resumen["transicion"] = {"extrados": transition_location(s, True),
                                 "intrados": transition_location(s, False)}
    return resumen


def surface_text(resumen: Optional[Dict], cd_total: Optional[float]) -> str:
    """Una linea para la ventana y el informe; vacia si no hay datos."""
    if not resumen:
        return ""
    partes = []
    cdf = resumen.get("cd_friccion")
    if cdf is not None and cd_total:
        partes.append(f"Cd de fricción {cdf:.5f} ({100 * cdf / cd_total:.0f} % del total), "
                      f"de presión {cd_total - cdf:.5f}")
    tr = resumen.get("transicion")
    if tr is not None:
        for cara, nombre in (("extrados", "extradós"), ("intrados", "intradós")):
            t = tr.get(cara)
            partes.append(f"transición en el {nombre}: x/c {t['inicio']:.3f} (inicio) a {t['subida']:.3f}"
                          if t else f"sin transición clara en el {nombre}")
    return "; ".join(partes)
