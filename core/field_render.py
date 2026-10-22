#!/usr/bin/env python3
"""Renderizado de campos CFD y estructurales respetando la topología de la malla.

El problema que resuelve este módulo
------------------------------------
La versión anterior dibujaba los campos con ``matplotlib.tri.Triangulation``
sobre la nube de puntos del corte. Delaunay no sabe que el perfil es un hueco:
cierra la estela y rellena el INTERIOR del alabe con triángulos espurios
(se midieron 127 de 9559, un 1.3%). El resultado son contornos de presión y
velocidad pintados dentro del sólido, que es físicamente imposible.

Aquí se usan las **caras reales** de la malla de OpenFOAM:

  * ``PolyCollection`` con los polígonos del corte → el hueco del alabe queda
    vacío por construcción, no por recorte.
  * El color se interpola desde los valores nodales, así que no hay
    extrapolación fuera del dominio.

API
---
    render_field_frames(case_dir, field, out_dir, limits=None, fps=...)
    mask_inside_airfoil(points, contour)   # utilidad de comprobación
"""

from __future__ import annotations

import os
import sys

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.colors import Normalize


# --------------------------------------------------------------------------
def slice_polydata(case_dir: str, time_value: float | None = None,
                   foam_name: str = "case.foam"):
    """Corte en z medio del caso, como PolyData con sus caras reales."""
    import pyvista as pv

    foam = os.path.join(case_dir, foam_name)
    if not os.path.exists(foam):
        open(foam, "w").close()

    r = pv.OpenFOAMReader(foam)
    if time_value is None:
        time_value = r.time_values[-1]
    r.set_active_time_value(time_value)
    m = r.read()["internalMesh"]
    z0, z1 = m.bounds[4], m.bounds[5]
    return m.slice(normal="z", origin=(0, 0, (z0 + z1) / 2))


def cell_polygons(mesh):
    """Extrae las caras del PolyData como arrays (n_i, 2) de coordenadas.

    Devuelve una lista de polígonos listos para ``PolyCollection``. Al usar las
    caras reales, el hueco del alabe no se rellena.
    """
    pts = mesh.points[:, :2]
    # El recorte por caja devuelve UnstructuredGrid, que no tiene .faces pero
    # sí expone las celdas como VTK. Se normaliza a PolyData extrayendo la
    # superficie.
    if not hasattr(mesh, "faces"):
        mesh = mesh.extract_surface()
    faces = mesh.faces
    polys = []
    i = 0
    while i < len(faces):
        n = int(faces[i])
        idx = faces[i + 1:i + 1 + n]
        polys.append(pts[idx])
        i += 1 + n
    return polys


def nodal_values(mesh, field: str) -> np.ndarray:
    """Valores nodales del campo, convirtiendo vectores a magnitud."""
    data = mesh.point_data.get(field)
    if data is None:
        data = mesh.cell_data.get(field)
        if data is not None:
            mesh = mesh.cell_data_to_point_data()
            data = mesh.point_data.get(field)
    if data is None:
        raise RuntimeError(f"campo {field!r} no disponible")

    arr = np.asarray(data)
    if arr.ndim == 2 and arr.shape[1] == 3:
        return np.linalg.norm(arr, axis=1)
    return arr.ravel()


def cell_values_from_nodal(mesh, nodal: np.ndarray) -> np.ndarray:
    """Valor medio por celda a partir de los valores nodales.

    PolyCollection colorea por celda; promediar los nodos de cada cara es la
    forma consistente de asignar un color sin inventar valores.
    """
    if not hasattr(mesh, "faces"):
        mesh = mesh.extract_surface()
    faces = mesh.faces
    vals = []
    i = 0
    while i < len(faces):
        n = int(faces[i])
        idx = faces[i + 1:i + 1 + n]
        vals.append(float(np.mean(nodal[idx])))
        i += 1 + n
    return np.asarray(vals)


def mask_inside_airfoil(points, contour, tol=1e-9):
    """Puntos que caen dentro del contorno cerrado del perfil.

    Sólo para comprobación: si el renderizado es correcto, ningún punto de la
    malla fluida debería estar dentro.
    """
    from matplotlib.path import Path

    if contour is None:
        return np.zeros(len(points), dtype=bool)
    path = Path(contour)
    return path.contains_points(points)


# --------------------------------------------------------------------------
def render_frames(case_dir: str, field: str, out_dir: str,
                  times=None, xlim=(-0.4, 1.8), ylim=(-0.7, 0.7),
                  cmap: str | None = None, label: str | None = None,
                  dpi: int = 110, verbose: bool = True):
    """Renderiza un PNG por tiempo. Devuelve la lista de ficheros."""
    os.makedirs(out_dir, exist_ok=True)

    import pyvista as pv

    foam = os.path.join(case_dir, "case.foam")
    if not os.path.exists(foam):
        open(foam, "w").close()
    r = pv.OpenFOAMReader(foam)

    if times is None:
        # Sólo los tiempos que realmente contienen el campo
        times = []
        for t in r.time_values:
            if t == 0:
                continue
            d = os.path.join(case_dir, f"{t:g}")
            if os.path.isdir(d) and os.path.exists(os.path.join(d, field)):
                times.append(t)
    if not times:
        raise RuntimeError(f"ningún tiempo contiene el campo {field!r}")

    # Rango global para que la escala no cambie entre fotogramas
    vmin, vmax = np.inf, -np.inf
    cache = []
    for t in times:
        r.set_active_time_value(t)
        m = r.read()["internalMesh"]
        s = m.slice(normal="z", origin=(0, 0, (m.bounds[4] + m.bounds[5]) / 2))
        nodal = nodal_values(s, field)
        cache.append((t, s, nodal))
        vmin = min(vmin, float(np.nanpercentile(nodal, 0.5)))
        vmax = max(vmax, float(np.nanpercentile(nodal, 99.5)))

    cmap = cmap or {"p": "coolwarm", "U": "turbo", "k": "magma",
                    "nut": "viridis"}.get(field, "viridis")
    label = label or {"p": "p [m²/s²]", "U": "|U| [m/s]",
                      "k": "k [m²/s²]", "nut": "νt [m²/s]"}.get(field, field)

    files = []
    for k, (t, s, nodal) in enumerate(cache):
        polys = cell_polygons(s)
        cvals = cell_values_from_nodal(s, nodal)

        fig, ax = plt.subplots(figsize=(9, 4.0))
        pc = PolyCollection(polys, array=cvals, cmap=cmap,
                            norm=Normalize(vmin, vmax),
                            edgecolors="none", antialiased=False)
        ax.add_collection(pc)
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_aspect("equal")
        ax.set_xlabel("x/c")
        ax.set_ylabel("y/c")
        ax.set_title(f"{label} — t = {t:g} s", fontsize=11)

        cb = fig.colorbar(pc, ax=ax, shrink=0.85, pad=0.02)
        cb.set_label(label)

        path = os.path.join(out_dir, f"f_{k:04d}.png")
        fig.tight_layout()
        fig.savefig(path, dpi=dpi, facecolor="white")
        plt.close(fig)
        files.append(path)
        if verbose and ((k + 1) % 10 == 0 or k == len(cache) - 1):
            print(f"  {k + 1}/{len(cache)}")

    return files


def render_single(case_dir: str, field: str, out_png: str,
                  time_value: float | None = None,
                  xlim=(-0.4, 1.8), ylim=(-0.7, 0.7),
                  cmap: str | None = None, label: str | None = None,
                  dpi: int = 200):
    """Figura estática de un campo, con las caras reales de la malla."""
    import pyvista as pv

    foam = os.path.join(case_dir, "case.foam")
    if not os.path.exists(foam):
        open(foam, "w").close()
    r = pv.OpenFOAMReader(foam)
    if time_value is None:
        time_value = r.time_values[-1]
    r.set_active_time_value(time_value)
    m = r.read()["internalMesh"]
    s = m.slice(normal="z", origin=(0, 0, (m.bounds[4] + m.bounds[5]) / 2))

    nodal = nodal_values(s, field)
    polys = cell_polygons(s)
    cvals = cell_values_from_nodal(s, nodal)

    cmap = cmap or {"p": "coolwarm", "U": "turbo", "k": "magma",
                    "nut": "viridis"}.get(field, "viridis")
    label = label or {"p": "p [m²/s²]", "U": "|U| [m/s]",
                      "k": "k [m²/s²]", "nut": "νt [m²/s]"}.get(field, field)

    vmin = float(np.nanpercentile(cvals, 1))
    vmax = float(np.nanpercentile(cvals, 99))

    fig, ax = plt.subplots(figsize=(9, 4.0))
    pc = PolyCollection(polys, array=cvals, cmap=cmap,
                        norm=Normalize(vmin, vmax), edgecolors="none")
    ax.add_collection(pc)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_aspect("equal")
    ax.set_xlabel("x/c")
    ax.set_ylabel("y/c")
    ax.set_title(f"{label}  (t = {time_value:g} s)", fontsize=11)
    cb = fig.colorbar(pc, ax=ax, shrink=0.85, pad=0.02)
    cb.set_label(label)

    fig.tight_layout()
    fig.savefig(out_png, dpi=dpi, facecolor="white")
    plt.close(fig)
    return out_png


# --------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--field", default="p")
    ap.add_argument("--out", required=True)
    ap.add_argument("--time", type=float, default=None)
    args = ap.parse_args()

    p = render_single(args.case, args.field, args.out, args.time)
    print(p)
