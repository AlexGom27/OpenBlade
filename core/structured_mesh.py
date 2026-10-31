"""Mallas C estructuradas: de una rejilla x(i,j), y(i,j) a un archivo .msh de hexaedros.

La malla se escribe directamente, sin pasar por el mallador de gmsh: es lo que
permite importar las mallas oficiales de NASA TMR tal cual y generar familias con
un factor de refinamiento exacto (core/cgrid.py), que es lo que pide un GCI.

Convencion de la rejilla (la de TMR): i recorre la C desde la salida inferior,
por la estela inferior, el intrados, el extrados y la estela superior hasta la
salida superior; j va de la pared al contorno exterior. La estela inferior y la
superior coinciden en j=0: esos nodos se funden y las caras quedan interiores.
"""

from __future__ import annotations

import gzip
import json
from typing import List, Tuple

import numpy as np

PROFUNDIDAD = 0.1


def read_plot3d_2d(ruta: str) -> Tuple[np.ndarray, np.ndarray]:
    """Lee un PLOT3D 2D con formato y un bloque. Devuelve x e y con forma (ni, nj)."""
    abrir = gzip.open if ruta.endswith(".gz") else open
    with abrir(ruta, "rt") as f:
        valores = f.read().split()
    n_bloques, ni, nj = int(valores[0]), int(valores[1]), int(valores[2])
    if n_bloques != 1:
        raise ValueError(f"{ruta}: se esperaba un bloque y hay {n_bloques}")
    datos = np.array(valores[3:], dtype=float)
    if datos.size != 2 * ni * nj:
        raise ValueError(f"{ruta}: {datos.size} valores para {ni}x{nj}")
    x = datos[:ni * nj].reshape((ni, nj), order="F")
    y = datos[ni * nj:].reshape((ni, nj), order="F")
    return x, y


def wake_points(x: np.ndarray, y: np.ndarray) -> int:
    """Cuantos puntos de j=0 coinciden con su opuesto: la estela, borde de salida incluido."""
    ni = x.shape[0]
    distancia = np.hypot(x[:, 0] - x[::-1, 0], y[:, 0] - y[::-1, 0])
    tolerancia = 1e-9
    n = 0
    while n < ni // 2 and distancia[n] <= tolerancia:
        n += 1
    return n


def write_cgrid_msh(ruta: str, x: np.ndarray, y: np.ndarray, profundidad: float = PROFUNDIDAD,
                    n_estela: int = 0) -> dict:
    """Escribe la rejilla C como .msh 2.2 con los grupos que espera el caso.

    Devuelve datos de la malla: celdas, caras del perfil y primera celda.
    """
    ni, nj = x.shape
    n_estela = n_estela or wake_points(x, y)
    if n_estela < 2:
        raise ValueError("La rejilla no tiene estela: j=0 no se une consigo misma")

    # Numeracion de nodos en un plano, con la estela de j=0 fundida.
    ids = np.arange(ni * nj, dtype=np.int64).reshape(ni, nj, order="F")
    for i in range(n_estela):
        ids[ni - 1 - i, 0] = ids[i, 0]
    usados = np.unique(ids)
    nuevo = -np.ones(ni * nj, dtype=np.int64)
    nuevo[usados] = np.arange(usados.size)
    ids = nuevo[ids]
    n2d = usados.size
    xplano = x.flatten(order="F")[usados]
    yplano = y.flatten(order="F")[usados]

    # Orientacion: el area de las celdas debe ser positiva en el plano xy.
    a = (ids[:-1, :-1], ids[1:, :-1], ids[1:, 1:], ids[:-1, 1:])
    area = 0.5 * ((xplano[a[2]] - xplano[a[0]]) * (yplano[a[3]] - yplano[a[1]])
                  - (xplano[a[3]] - xplano[a[1]]) * (yplano[a[2]] - yplano[a[0]]))
    if np.all(area < 0):
        a = (a[1], a[0], a[3], a[2])
    elif not np.all(area > 0):
        raise ValueError(f"La rejilla tiene {int(np.sum(area <= 0))} celdas invertidas")

    delante = [v.flatten(order="F") + 1 for v in a]
    detras = [v + n2d for v in delante]
    n_celdas = delante[0].size

    def anillo(i0, j0, i1, j1):
        """Caras de contorno entre dos indices de la rejilla, como nodos del plano."""
        return ids[i0, j0] + 1, ids[i1, j1] + 1

    bordes: List[Tuple[str, np.ndarray, np.ndarray]] = []
    # Perfil: j=0 entre el borde de salida inferior y el superior.
    i_perfil = np.arange(n_estela - 1, ni - n_estela)
    bordes.append(("airfoil", ids[i_perfil, 0] + 1, ids[i_perfil + 1, 0] + 1))
    # Exterior: j=nj-1 completo. Salida: i=0 e i=ni-1.
    i_ext = np.arange(ni - 1)
    bordes.append(("inlet", ids[i_ext, nj - 1] + 1, ids[i_ext + 1, nj - 1] + 1))
    j_sal = np.arange(nj - 1)
    salida_a = np.concatenate([ids[0, j_sal], ids[ni - 1, j_sal]]) + 1
    salida_b = np.concatenate([ids[0, j_sal + 1], ids[ni - 1, j_sal + 1]]) + 1
    bordes.append(("outlet", salida_a, salida_b))

    grupos = {"frontAndBack": 1, "inlet": 2, "outlet": 3, "airfoil": 4, "fluid": 5}
    n_elem = 2 * n_celdas + sum(b[1].size for b in bordes) + n_celdas
    with open(ruta, "w") as f:
        f.write("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n$PhysicalNames\n5\n")
        for nombre, n in grupos.items():
            f.write(f'{3 if nombre == "fluid" else 2} {n} "{nombre}"\n')
        f.write(f"$EndPhysicalNames\n$Nodes\n{2 * n2d}\n")
        for capa, z in ((0, 0.0), (n2d, profundidad)):
            for k, (xx, yy) in enumerate(zip(xplano, yplano), start=capa + 1):
                f.write(f"{k} {xx:.15g} {yy:.15g} {z:.15g}\n")
        f.write(f"$EndNodes\n$Elements\n{n_elem}\n")
        e = 0
        grupo = grupos["frontAndBack"]
        for v in zip(*delante):
            e += 1
            f.write(f"{e} 3 2 {grupo} 1 {v[3]} {v[2]} {v[1]} {v[0]}\n")
        for v in zip(*detras):
            e += 1
            f.write(f"{e} 3 2 {grupo} 1 {v[0]} {v[1]} {v[2]} {v[3]}\n")
        for nombre, n1, n2 in bordes:
            grupo = grupos[nombre]
            for p, q in zip(n1, n2):
                e += 1
                f.write(f"{e} 3 2 {grupo} 1 {p} {q} {q + n2d} {p + n2d}\n")
        grupo = grupos["fluid"]
        for v0, v1 in zip(zip(*delante), zip(*detras)):
            e += 1
            f.write(f"{e} 5 2 {grupo} 1 {v0[0]} {v0[1]} {v0[2]} {v0[3]} "
                    f"{v1[0]} {v1[1]} {v1[2]} {v1[3]}\n")
        f.write("$EndElements\n")

    # La primera celda en el perfil, para la ficha.
    dx = x[i_perfil, 1] - x[i_perfil, 0]
    dy = y[i_perfil, 1] - y[i_perfil, 0]
    info = {"celdas": int(n_celdas), "caras_perfil": int(i_perfil.size),
            "primera_celda_media": float(np.hypot(dx, dy).mean()),
            "radio_max": float(np.hypot(x[:, nj - 1] - 0.5, y[:, nj - 1]).max())}
    return info


def import_plot3d(entrada: str, salida: str, profundidad: float = PROFUNDIDAD) -> dict:
    """Convierte una malla PLOT3D 2D (p. ej. las de NASA TMR) a .msh."""
    x, y = read_plot3d_2d(entrada)
    if np.ptp(y[:, 0]) == 0 and np.ptp(y) == 0:
        raise ValueError(f"{entrada}: la rejilla es plana en y")
    info = write_cgrid_msh(salida, x, y, profundidad)
    info["mallador"] = f"importada de {entrada.rsplit('/', 1)[-1]}"
    with open(salida + ".info.json", "w") as f:
        json.dump(info, f, ensure_ascii=False)
    return info
