"""Lector unico de coeficientes de fuerza de OpenFOAM.

GUI, ejecucion en servidor, informe y validation/ leen las fuerzas de aqui.
Las columnas se buscan por el nombre que da la cabecera del archivo, porque su
orden cambia entre versiones:

    OpenFOAM 12 (Foundation):  Time Cm Cd Cl Cl(f) Cl(r)
    OpenFOAM v2xxx (ESI):      Time Cd Cd(f) Cd(r) Cl Cl(f) Cl(r) CmPitch ...

Leer por posicion ya dio resultados falsos: Cl(f) se tomo por Cl y el Cm por Cd.
Si falta una columna o no hay cabecera se lanza ForceDataError; nunca se adivina.
Solo usa la biblioteca estandar.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

NOMBRES = ("forceCoeffs.dat", "coefficient.dat")
# Mismo significado con distinto nombre segun la version de OpenFOAM.
ALIAS = {"Cm": ("Cm", "CmPitch")}
OBLIGATORIAS = ("Time", "Cl", "Cd", "Cm")


class ForceDataError(ValueError):
    """Los datos de fuerzas no existen o no se pueden interpretar."""


@dataclass
class ForceHistory:
    columns: Dict[str, List[float]]
    sources: List[str]

    def __len__(self) -> int:
        return len(self.columns["Time"])

    def column(self, name: str) -> List[float]:
        if name not in self.columns:
            raise ForceDataError(f"Falta la columna {name}; hay "
                                 f"{sorted(self.columns)}")
        return self.columns[name]

    @property
    def time(self) -> List[float]:
        return self.column("Time")

    @property
    def cl(self) -> List[float]:
        return self.column("Cl")

    @property
    def cd(self) -> List[float]:
        return self.column("Cd")

    @property
    def cm(self) -> List[float]:
        return self.column("Cm")

    def final(self) -> Tuple[float, float, float]:
        """(Cl, Cd, Cm) de la ultima fila."""
        if not len(self):
            raise ForceDataError("El archivo de fuerzas no tiene filas")
        return self.cl[-1], self.cd[-1], self.cm[-1]


def _hora_de_inicio(ruta: str) -> float:
    try:
        return float(os.path.basename(os.path.dirname(ruta)))
    except ValueError:
        raise ForceDataError(f"Carpeta de tiempo no valida: {ruta}") from None


def find_force_files(case_dir: str) -> List[str]:
    """Archivos de fuerzas del caso, en orden de tiempo de arranque."""
    raiz = os.path.join(case_dir, "postProcessing", "forceCoeffs")
    archivos = [f for f in glob.glob(os.path.join(raiz, "*", "*"))
                if os.path.basename(f) in NOMBRES]
    return sorted(archivos, key=_hora_de_inicio)


def _indices(nombres: List[str], requeridas: Iterable[str], ruta: str) -> Dict[str, int]:
    indices = {}
    for columna in requeridas:
        for candidato in ALIAS.get(columna, (columna,)):
            if candidato in nombres:
                indices[columna] = nombres.index(candidato)
                break
        else:
            raise ForceDataError(f"{ruta}: falta la columna {columna}; "
                                 f"la cabecera tiene {nombres}")
    return indices


def remote_tail_command(lineas: int = 8000) -> str:
    """Shell que trae la cabecera y la cola del archivo, para leerlas aqui."""
    return ('f=$(ls postProcessing/forceCoeffs/*/*.dat 2>/dev/null | tail -1); '
            f'[ -n "$f" ] && {{ grep -m1 "^# Time" "$f"; tail -n {lineas} "$f"; }}')


def parse_force_lines(lineas: Iterable[str], requeridas: Iterable[str] = OBLIGATORIAS,
                      origen: str = "fuerzas") -> Dict[str, List[float]]:
    """Convierte las lineas de un archivo de fuerzas en columnas por nombre.

    Una ultima fila incompleta se ignora: el solver puede estar escribiendola.
    Cualquier otra fila mal formada es un error.
    """
    requeridas = list(requeridas)
    indices = None
    columnas = {c: [] for c in requeridas}
    filas = [l for l in lineas if l.strip()]
    for n, linea in enumerate(filas):
        if linea.lstrip().startswith("#"):
            nombres = linea.lstrip()[1:].split()
            if nombres[:1] == ["Time"]:
                indices = _indices(nombres, requeridas, origen)
                ancho = len(nombres)
            continue
        if indices is None:
            raise ForceDataError(f"{origen}: datos sin cabecera de columnas")
        valores = linea.split()
        try:
            if len(valores) != ancho:
                raise ValueError(f"{len(valores)} columnas, se esperaban {ancho}")
            fila = {c: float(valores[i]) for c, i in indices.items()}
        except ValueError as e:
            if n == len(filas) - 1:
                break
            raise ForceDataError(f"{origen}: fila {n + 1} no valida: {e}") from None
        for c, v in fila.items():
            columnas[c].append(v)
    if indices is None:
        raise ForceDataError(f"{origen}: no tiene cabecera de columnas")
    return columnas


def read_force_file(ruta: str, requeridas: Iterable[str] = OBLIGATORIAS) -> Dict[str, List[float]]:
    with open(ruta, errors="replace") as f:
        return parse_force_lines(f, requeridas, origen=ruta)


def read_forces(case_dir: str, requeridas: Iterable[str] = OBLIGATORIAS) -> ForceHistory:
    """Historia completa del caso, uniendo los tramos de cada arranque.

    Si un tramo se solapa con el anterior, cuenta el mas reciente.
    """
    archivos = find_force_files(case_dir)
    if not archivos:
        raise ForceDataError(f"No hay archivo de fuerzas en {case_dir}")
    requeridas = list(requeridas)
    if "Time" not in requeridas:
        requeridas.insert(0, "Time")
    total = {c: [] for c in requeridas}
    for ruta in archivos:
        tramo = read_force_file(ruta, requeridas)
        if tramo["Time"]:
            inicio = tramo["Time"][0]
            conservar = sum(1 for t in total["Time"] if t < inicio)
            for c in requeridas:
                total[c] = total[c][:conservar] + tramo[c]
    return ForceHistory(total, archivos)


def final_coefficients(case_dir: str) -> Tuple[float, float, float]:
    """(Cl, Cd, Cm) de la ultima fila del caso."""
    return read_forces(case_dir).final()


def tail_statistics(case_dir: str, fraccion: float = 0.8,
                    minimo: int = 30) -> Optional[Dict[str, float]]:
    """Media y desviacion de Cl y Cd desde esa fraccion de la historia.

    None si el caso aun no tiene datos suficientes.
    """
    if not find_force_files(case_dir):
        return None
    h = read_forces(case_dir, ("Time", "Cl", "Cd"))
    if len(h) < minimo:
        return None
    inicio = int(fraccion * len(h))
    cl, cd = h.cl[inicio:], h.cd[inicio:]
    m_cl, m_cd = sum(cl) / len(cl), sum(cd) / len(cd)
    return {"cl": m_cl, "cd": m_cd, "n": len(cl),
            "cl_std": (sum((x - m_cl) ** 2 for x in cl) / len(cl)) ** 0.5,
            "cd_std": (sum((x - m_cd) ** 2 for x in cd) / len(cd)) ** 0.5}
