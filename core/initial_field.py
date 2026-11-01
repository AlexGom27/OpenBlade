"""Arrancar un caso desde el resultado de otro con la misma malla.

Solo se copia el interior de los campos: las condiciones de contorno son las que escribio
el programa para este caso. El flujo no se copia: OpenFOAM lo interpola de U.

No arregla un transitorio inestable: a 18 grados y Re = 6e6, desde el campo estacionario
las fuerzas salen mas ruidosas que desde el flujo potencial, con Courant 10 y tambien
copiando el flujo.
"""

from __future__ import annotations

import os
import re
from typing import Optional

from core.package import read_ficha, sha256_file

_INTERIOR = re.compile(r"^internalField\s.*?;", re.S | re.M)


def latest_fields(case_dir: str) -> Optional[str]:
    """Carpeta del ultimo tiempo con campos, sin contar el inicial."""
    tiempos = []
    for nombre in os.listdir(case_dir):
        try:
            t = float(nombre)
        except ValueError:
            continue
        if t > 0 and os.path.exists(os.path.join(case_dir, nombre, "U")):
            tiempos.append((t, nombre))
    return os.path.join(case_dir, max(tiempos)[1]) if tiempos else None


def _expand(interior: str, nivel: int) -> str:
    """El interior de un campo de la malla inmediatamente mas gruesa, en la de este nivel.

    Las mallas son anidadas y sus celdas van por la rejilla, con i como indice rapido: cada
    celda fina (i, j) cae dentro de la gruesa (i // 2, j // 2).
    """
    from core.cgrid import cells_of_level

    if "nonuniform" not in interior:
        return interior
    lineas = interior.split("\n")
    inicio = lineas.index("(")
    fin = len(lineas) - 1 - lineas[::-1].index(")")
    valores = lineas[inicio + 1:fin]
    ni, nj = cells_of_level(nivel)
    ni_g, nj_g = ni // 2, nj // 2
    if len(valores) != ni_g * nj_g:
        raise ValueError(f"El campo tiene {len(valores)} celdas y la malla gruesa {ni_g * nj_g}")
    finos = [valores[(i // 2) + (j // 2) * ni_g] for j in range(nj) for i in range(ni)]
    cabecera = lineas[:inicio]
    cabecera[-1] = str(len(finos))
    return "\n".join(cabecera + ["("] + finos + lineas[fin:])


def start_from(origen: str, case_dir: str, msh_file: str, params: Optional[dict] = None) -> str:
    """Pasa a 0/ el interior de los campos de otra corrida. Devuelve de que tiempo salieron.

    La otra corrida tiene la misma malla, o la del nivel inmediatamente mas grueso de la
    misma familia.
    """
    ficha = read_ficha(origen) or {}
    nivel = None
    if ficha.get("archivos", {}).get("mesh.msh") != sha256_file(msh_file):
        from core.jobs import mesh_key
        previos = ficha.get("parametros") or {}
        n = int((params or {}).get("grid_level", 0))
        if not params or int(previos.get("grid_level", -9)) != n - 1 or (
                mesh_key(dict(previos, grid_level=n)) != mesh_key(params)):
            raise ValueError(f"El campo inicial de {origen} es de otra malla")
        nivel = n
    tiempo = latest_fields(origen)
    if tiempo is None:
        raise ValueError(f"{origen} no tiene campos de los que arrancar")
    destino = os.path.join(case_dir, "0")
    for campo in sorted(os.listdir(destino)):
        ruta = os.path.join(destino, campo)
        fuente = os.path.join(tiempo, campo)
        if not os.path.isfile(ruta):
            continue
        if not os.path.exists(fuente):
            raise ValueError(f"{origen} no tiene el campo {campo}: ¿es otro modelo de turbulencia?")
        with open(fuente, errors="replace") as f:
            hallado = _INTERIOR.search(f.read())
        with open(ruta) as f:
            texto = f.read()
        if hallado is None or _INTERIOR.search(texto) is None:
            raise ValueError(f"No se encontró internalField en {campo}")
        with open(ruta, "w") as f:
            interior = hallado.group(0) if nivel is None else _expand(hallado.group(0), nivel)
            f.write(_INTERIOR.sub(lambda _: interior, texto, count=1))
    return os.path.basename(tiempo)
