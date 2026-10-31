"""y+ del perfil calculado por el programa, con la friccion real.

    y+ = y_P * u_tau / nu,   u_tau = sqrt(|tau_w|)

El campo yPlus de OpenFOAM no sirve para comparar: su definicion depende de la
condicion de pared. nutkWallFunction usa k en la celda (Cmu^0.25 y sqrt(k)/nu) y
nutLowReWallFunction la friccion real, y sobre la misma corrida dan 0.205 y 2.46
de media. Aqui se lee wallShearStress y la malla, sin depender de la condicion.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

PARCHE = "airfoil"
YP_RESUELTO = 1.0       # subcapa viscosa bien resuelta
YP_VISCOSA = 5.0        # limite de la subcapa
YP_LOG_MIN = 30.0       # desde aqui vale la ley logaritmica
YP_LOG_MAX = 300.0
PARED_LOG = ("nutkWallFunction", "nutUWallFunction", "nutUSpaldingWallFunction")
# Primera celda para y+ medio = 1: la friccion se estima como en placa plana.
CF_COEF = 0.026


class YPlusError(ValueError):
    """Faltan datos para calcular y+."""


@dataclass
class YPlusResult:
    mean: float
    min: float
    max: float
    n_faces: int
    time: str
    nu: float
    first_cell_mean: float
    wall_condition: str
    u_tau_mean: float
    model: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _leer(ruta: str) -> str:
    try:
        with open(ruta, errors="replace") as f:
            return f.read()
    except OSError as e:
        raise YPlusError(f"No se puede leer {os.path.basename(ruta)}: {e}") from None


def _cuerpo_lista(texto: str) -> str:
    """Lo que hay entre los parentesis de la lista principal de un polyMesh."""
    sin_cabecera = re.sub(r"FoamFile\s*\{.*?\}", "", texto, count=1, flags=re.S)
    m = re.search(r"\n\s*(\d+)\s*\n?\s*\(", sin_cabecera)
    if not m:
        raise YPlusError("Lista de malla no reconocida")
    return sin_cabecera[m.end():sin_cabecera.rindex(")")]


def _rango_parche(polymesh: str, parche: str) -> Tuple[int, int]:
    texto = _leer(os.path.join(polymesh, "boundary"))
    m = re.search(rf"\b{parche}\s*\{{([^}}]*)\}}", texto)
    if not m:
        raise YPlusError(f"La malla no tiene el parche {parche}")
    n = re.search(r"nFaces\s+(\d+)", m.group(1))
    s = re.search(r"startFace\s+(\d+)", m.group(1))
    if not n or not s:
        raise YPlusError(f"El parche {parche} no indica sus caras")
    return int(s.group(1)), int(n.group(1))


def _enteros(ruta: str) -> np.ndarray:
    return np.array(_cuerpo_lista(_leer(ruta)).split(), dtype=np.int64)


def _puntos(ruta: str) -> np.ndarray:
    plano = _cuerpo_lista(_leer(ruta)).replace("(", " ").replace(")", " ")
    return np.array(plano.split(), dtype=float).reshape(-1, 3)


def _caras(ruta: str) -> List[str]:
    return re.findall(r"\d+\(([^)]*)\)", _cuerpo_lista(_leer(ruta)))


def _geometria_cara(puntos: np.ndarray, nodos: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Centro y vector area de una cara, por triangulos como hace OpenFOAM."""
    p = puntos[nodos]
    if len(nodos) == 3:
        return p.mean(axis=0), 0.5 * np.cross(p[1] - p[0], p[2] - p[0])
    estimado = p.mean(axis=0)
    siguiente = np.roll(p, -1, axis=0)
    vectores = 0.5 * np.cross(siguiente - p, estimado - p)
    magnitudes = np.linalg.norm(vectores, axis=1)
    area = vectores.sum(axis=0)
    centros = (p + siguiente + estimado) / 3.0
    total = magnitudes.sum()
    if total <= 0:
        return estimado, area
    return (centros * magnitudes[:, None]).sum(axis=0) / total, area


def first_cell_distance(case_dir: str, parche: str = PARCHE) -> np.ndarray:
    """Distancia normal del centro de cada celda de pared a su cara."""
    polymesh = os.path.join(case_dir, "constant", "polyMesh")
    inicio, n = _rango_parche(polymesh, parche)
    if n == 0:
        raise YPlusError(f"El parche {parche} no tiene caras")
    puntos = _puntos(os.path.join(polymesh, "points"))
    caras = _caras(os.path.join(polymesh, "faces"))
    owner = _enteros(os.path.join(polymesh, "owner"))
    vecino = _enteros(os.path.join(polymesh, "neighbour"))

    pared = owner[inicio:inicio + n]
    interesa = np.isin(owner, pared)
    interesa[:len(vecino)] |= np.isin(vecino, pared)

    # Centro de celda por piramides sobre sus caras, como OpenFOAM.
    caras_de_celda: Dict[int, List[Tuple[np.ndarray, np.ndarray]]] = {}
    for f in np.flatnonzero(interesa):
        geo = _geometria_cara(puntos, np.array(caras[f].split(), dtype=np.int64))
        caras_de_celda.setdefault(int(owner[f]), []).append(geo)
        if f < len(vecino):
            caras_de_celda.setdefault(int(vecino[f]), []).append(geo)

    distancias = np.empty(n)
    for i in range(n):
        centro_cara, area = _geometria_cara(
            puntos, np.array(caras[inicio + i].split(), dtype=np.int64))
        normal = area / np.linalg.norm(area)
        lista = caras_de_celda[int(pared[i])]
        estimado = np.mean([c for c, _ in lista], axis=0)
        volumen, momento = 0.0, np.zeros(3)
        for c, a in lista:
            v = abs(np.dot(a, c - estimado)) / 3.0
            volumen += v
            momento += v * (0.75 * c + 0.25 * estimado)
        centro = momento / volumen if volumen > 0 else estimado
        distancias[i] = abs(np.dot(centro_cara - centro, normal))
    return distancias


def _nu(case_dir: str) -> float:
    for nombre in ("transportProperties", "physicalProperties"):
        ruta = os.path.join(case_dir, "constant", nombre)
        if os.path.exists(ruta):
            m = re.search(r"^\s*nu\s+(?:\[[^\]]*\]\s*)?([0-9.eE+\-]+)\s*;", _leer(ruta), re.M)
            if m:
                return float(m.group(1))
    raise YPlusError("El caso no indica la viscosidad nu")


def _ultimo_tiempo_con(case_dir: str, campo: str) -> str:
    tiempos = []
    for d in os.listdir(case_dir):
        try:
            valor = float(d)
        except ValueError:
            continue
        if os.path.exists(os.path.join(case_dir, d, campo)):
            tiempos.append((valor, d))
    if not tiempos:
        raise YPlusError(f"Ningún tiempo tiene el campo {campo}")
    return max(tiempos)[1]


def _vectores_de_parche(ruta: str, parche: str, n: int) -> np.ndarray:
    texto = _leer(ruta)
    resto = texto[texto.index("boundaryField"):]
    m = re.search(rf"\b{parche}\s*\{{", resto)
    if not m:
        raise YPlusError(f"{os.path.basename(ruta)} no tiene el parche {parche}")
    bloque = resto[m.end():]
    no_uniforme = re.match(
        r"[^;{}]*?type\s+\w+\s*;\s*value\s+nonuniform\s+List<vector>\s*(\d+)\s*\(", bloque)
    if no_uniforme:
        cuerpo = bloque[no_uniforme.end():]
        fin = cuerpo.index(";")
        plano = cuerpo[:fin].replace("(", " ").replace(")", " ")
        datos = np.array(plano.split(), dtype=float).reshape(-1, 3)
    else:
        uniforme = re.match(r"[^;{}]*?type\s+\w+\s*;\s*value\s+uniform\s*\(([^)]*)\)", bloque)
        if not uniforme:
            raise YPlusError(f"{os.path.basename(ruta)}: valor de {parche} no reconocido")
        datos = np.tile(np.array(uniforme.group(1).split(), dtype=float), (n, 1))
    if len(datos) != n:
        raise YPlusError(f"{os.path.basename(ruta)}: {len(datos)} valores para {n} caras")
    return datos


def wall_condition(case_dir: str, parche: str = PARCHE) -> str:
    """Condicion de pared de nut que uso el caso; '' si no tiene nut."""
    ruta = os.path.join(case_dir, "0", "nut")
    if not os.path.exists(ruta):
        return ""
    m = re.search(rf"\b{parche}\s*\{{[^}}]*?type\s+(\w+)", _leer(ruta))
    return m.group(1) if m else ""


def turbulence_model(case_dir: str) -> str:
    """Modelo de turbulencia del caso; '' si es laminar o no se sabe."""
    ruta = os.path.join(case_dir, "constant", "turbulenceProperties")
    if not os.path.exists(ruta):
        return ""
    m = re.search(r"RASModel\s+(\w+)\s*;", _leer(ruta))
    return m.group(1) if m and "laminar" not in _leer(ruta) else ""


def compute_yplus(case_dir: str, nu: Optional[float] = None,
                  parche: str = PARCHE) -> YPlusResult:
    """y+ medio, minimo y maximo sobre el perfil en el ultimo tiempo escrito."""
    nu = nu if nu is not None else _nu(case_dir)
    if not os.path.isdir(os.path.join(case_dir, "constant", "polyMesh")):
        raise YPlusError("El caso no tiene malla")
    tiempo = _ultimo_tiempo_con(case_dir, "wallShearStress")
    y = first_cell_distance(case_dir, parche)
    tau = _vectores_de_parche(os.path.join(case_dir, tiempo, "wallShearStress"),
                              parche, len(y))
    u_tau = np.sqrt(np.linalg.norm(tau, axis=1))
    yp = y * u_tau / nu
    return YPlusResult(float(yp.mean()), float(yp.min()), float(yp.max()), len(yp),
                       tiempo, nu, float(y.mean()), wall_condition(case_dir, parche),
                       float(u_tau.mean()), turbulence_model(case_dir))


def first_cell_for_yplus(yplus: float, reynolds: float) -> float:
    """Altura de la primera celda, en cuerdas, para ese y+ medio.

    OpenFOAM evalua y+ en el centro de la celda, a media altura: la primera
    celda mide el doble de y_P. Antes se tomaba y_P como altura y una malla
    pensada para y+ = 2 salia con y+ = 1.
    """
    cf = CF_COEF / reynolds ** (1.0 / 7.0)
    return 2.0 * yplus / (reynolds * math.sqrt(cf / 2.0))


def estimate_yplus(first_cell: float, reynolds: float) -> float:
    """y+ medio esperado con esa primera celda (en cuerdas) a ese Reynolds."""
    return first_cell / first_cell_for_yplus(1.0, reynolds)


def regime_notice(yp: YPlusResult) -> Tuple[str, str]:
    """(nivel, texto): 'ok', 'aviso' o 'mal' segun la malla y la condicion de pared."""
    datos = f"y+ medio {yp.mean:.2f}, máximo {yp.max:.2f}"
    if yp.model == "kEpsilon" and yp.mean < YP_LOG_MIN:
        # Medido a alfa=4 con y+ = 2: Cd = 0.119, quince veces el real.
        return "mal", (f"{datos}: k-ε necesita ley de pared, con y+ entre {YP_LOG_MIN:.0f} y "
                       f"{YP_LOG_MAX:.0f}. Estos coeficientes no valen: sube el y+ objetivo o usa SST.")
    if yp.mean >= YP_LOG_MIN:
        if yp.wall_condition not in PARED_LOG:
            return "mal", (f"{datos}: la primera celda cae en la zona logarítmica, pero "
                           f"la pared usa {yp.wall_condition or 'una condición sin ley de pared'}. "
                           "Refina la capa límite o usa una ley de pared.")
        if yp.mean > YP_LOG_MAX:
            return "aviso", f"{datos}: por encima de {YP_LOG_MAX:.0f} la ley logarítmica deja de valer."
        return "ok", f"{datos}: zona logarítmica, con ley de pared ({yp.wall_condition})."
    if yp.mean > YP_VISCOSA:
        return "mal", (f"{datos}: la primera celda cae en la zona de transición "
                       f"({YP_VISCOSA:.0f} < y+ < {YP_LOG_MIN:.0f}), donde ni la subcapa "
                       "ni la ley logarítmica valen. Cambia la altura de la primera celda.")
    if yp.mean > YP_RESUELTO:
        return "aviso", (f"{datos}: dentro de la subcapa viscosa, pero lejos de y+ ≈ 1. "
                         "Para fricción de referencia refina la primera celda.")
    return "ok", f"{datos}: subcapa viscosa resuelta."
