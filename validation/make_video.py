#!/usr/bin/env python3
"""Genera vídeos MP4 de los campos de la simulación.

Dos modos:

    # Estructural: von Mises sobre el sólido, deformado
    python3 validation/make_video.py --mode solid --frames DIR -o von_mises.mp4

    # Fluido: campos del CFD cuadro a cuadro
    python3 validation/make_video.py --mode fluid --case CASE_DIR -o cfd.mp4

El modo estructural lee los .npz que escribe ``structural_solver.py`` cuando
la variable de entorno ``FSI_FRAMES_DIR`` está definida.

El modo fluido lee los tiempos guardados del caso OpenFOAM y renderiza un campo
(presión, velocidad o turbulencia) con malla deformada.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.colors import Normalize
import matplotlib.tri as mtri

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


# --------------------------------------------------------------------------
def ffmpeg_exe() -> str:
    """Ruta al ffmpeg. Se usa el de imageio-ffmpeg si no hay uno del sistema."""
    import shutil
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "No hay ffmpeg. Instala ffmpeg o `pip install imageio-ffmpeg`."
        ) from e


def encode(frames_dir: str, out_path: str, fps: int = 12) -> str:
    """Codifica los PNG de un directorio en un MP4 H.264."""
    import subprocess

    files = sorted(glob.glob(os.path.join(frames_dir, "*.png")))
    if not files:
        raise RuntimeError(f"No hay fotogramas en {frames_dir}")

    cmd = [
        ffmpeg_exe(), "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frames_dir, "f_%04d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-crf", "20",
        out_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg falló:\n" + r.stderr[-1500:])
    return out_path


# --------------------------------------------------------------------------
# Estructural
# --------------------------------------------------------------------------
def render_solid(frames_dir: str, out_dir: str, fps: int = 12,
                 out_path: str = "von_mises.mp4") -> str:
    """Vídeo de σ_vM sobre el sólido deformado, escalado a la deformación real."""
    files = sorted(glob.glob(os.path.join(frames_dir, "frame_*.npz")))
    if not files:
        raise RuntimeError(f"No hay fotogramas en {frames_dir}")

    # Rango global de von Mises para que la escala de color no cambie entre
    # fotogramas (si no, el vídeo "parpadea" y no se puede comparar).
    vmax = 0.0
    for f in files:
        d = np.load(f)
        vmax = max(vmax, float(d["vm"].max()))
    vmax = max(vmax, 1e-12)

    os.makedirs(out_dir, exist_ok=True)
    print(f"  rango von Mises: 0 … {vmax:.3e} Pa, {len(files)} fotogramas")

    for k, path in enumerate(files):
        d = np.load(path)
        nodes, elems = d["nodes"], d["elems"]
        u, vm = d["u"], d["vm"]
        t = float(d["t"])

        disp = np.column_stack([u[0::2], u[1::2]])
        # Amplificación 1: se muestra la deformación real. Si fuera
        # inapreciable se podría amplificar, pero aquí interesa que el
        # espectador vea la magnitud verdadera.
        defo = nodes + disp

        polys = [defo[e] for e in elems]

        fig, ax = plt.subplots(figsize=(9, 4.6))
        pc = PolyCollection(polys, array=vm, cmap="inferno",
                             norm=Normalize(0, vmax), edgecolors="none")
        ax.add_collection(pc)
        ax.autoscale_view()

        xs, ys = defo[:, 0], defo[:, 1]
        ax.set_xlim(xs.min() - 0.05, xs.max() + 0.05)
        # El perfil es muy delgado (y ≈ ±0.06): sin exagerar la escala vertical
        # el campo de tensiones no se distingue. Se amplía 2.5× sólo la vista,
        # no los datos, y se indica en el pie.
        ax.set_ylim((ys.min() - 0.02) * 2.0, (ys.max() + 0.02) * 2.0)
        ax.set_aspect("auto")
        ax.set_xlabel("x [m]")
        ax.set_ylabel("y [m]")
        ax.set_title(f"Tensión de von Mises — t = {t:.4f} s", fontsize=11)
        fig.text(0.01, 0.01, "escala vertical ampliada ×2 para visibilidad",
                 fontsize=6.5, color="#777777")

        cb = fig.colorbar(pc, ax=ax, shrink=0.85, pad=0.02)
        cb.set_label("σ_vm [Pa]")
        cb.formatter.set_powerlimits((-1, 3))
        cb.update_ticks()

        # Flecha de la corriente, para dar contexto
        ax.annotate("", xy=(xs.min() + 0.28, ys.max() + 0.04),
                    xytext=(xs.min() + 0.06, ys.max() + 0.04),
                    arrowprops=dict(arrowstyle="->", lw=1.8, color="#1565c0"))
        ax.text(xs.min() + 0.17, ys.max() + 0.055, "U", ha="center",
                fontsize=9, color="#1565c0")

        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, f"f_{k:04d}.png"), dpi=110,
                    facecolor="white")
        plt.close(fig)

        if (k + 1) % 10 == 0 or k == len(files) - 1:
            print(f"  {k + 1}/{len(files)}")

    return encode(out_dir, out_path, fps=fps)


# --------------------------------------------------------------------------
# Fluido
# --------------------------------------------------------------------------
def render_fluid(case_dir: str, out_dir: str, field: str = "p",
                 fps: int = 12, out_path: str = "cfd.mp4") -> str:
    """Vídeo de un campo del CFD sobre los tiempos guardados."""
    import pyvista as pv

    foam = os.path.join(case_dir, "case.foam")
    if not os.path.exists(foam):
        open(foam, "w").close()

    r = pv.OpenFOAMReader(foam)
    times = [t for t in r.time_values if t > 0]
    if not times:
        raise RuntimeError("El caso no tiene tiempos guardados con campos.")

    os.makedirs(out_dir, exist_ok=True)
    print(f"  {len(times)} tiempos en el caso")

    # No todos los tiempos tienen los campos escritos: en los casos FSI el
    # adaptador escribe sólo yPlus en los intermedios. Se descartan los que no
    # contengan el campo pedido.
    valid = []
    for t in times:
        d = os.path.join(case_dir, f"{t:g}")
        if os.path.isdir(d) and os.path.exists(os.path.join(d, field)):
            valid.append(t)
    if not valid:
        raise RuntimeError(
            f"ningún tiempo contiene el campo {field!r}; revisa qué se escribió")
    times = valid
    print(f"  {len(times)} con el campo {field!r}: {times[0]:g} … {times[-1]:g}")

    # Rango global del campo
    vmin, vmax = np.inf, -np.inf
    snaps = []
    for t in times:
        r.set_active_time_value(t)
        m = r.read()["internalMesh"]
        z0, z1 = m.bounds[4], m.bounds[5]
        s = m.slice(normal="z", origin=(0, 0, (z0 + z1) / 2))
        # Tras el corte, el campo puede quedar en point_data o en cell_data
        # según cómo lo escriba el solver. Se comprueban ambos y sólo se
        # convierte si hace falta (convertir un bloque ya nodal lo vacía).
        data = s.point_data.get(field)
        if data is None:
            data = s.cell_data.get(field)
            if data is not None:
                s = s.cell_data_to_point_data()
                data = s.point_data.get(field)
        if data is None:
            raise RuntimeError(
                f"campo {field!r} no disponible; hay: "
                f"{list(s.point_data.keys()) + list(s.cell_data.keys())}")

        arr = np.asarray(data)
        # Los campos vectoriales (U, displacement) llegan como (n, 3): para
        # pintarlos hace falta la magnitud. Sin esto el triplot falla con
        # "z array must have same length as triangulation".
        if arr.ndim == 2 and arr.shape[1] == 3:
            arr = np.linalg.norm(arr, axis=1)
        else:
            arr = arr.ravel()

        snaps.append((t, s.points[:, :2].copy(), arr))
        vmin = min(vmin, float(np.nanpercentile(data, 0.5)))
        vmax = max(vmax, float(np.nanpercentile(data, 99.5)))

    cmap = {"p": "coolwarm", "U": "turbo", "k": "magma",
            "nut": "viridis"}.get(field, "viridis")
    label = {"p": "p [m²/s²]", "U": "|U| [m/s]", "k": "k [m²/s²]",
             "nut": "νt [m²/s]"}.get(field, field)

    for k, (t, pts, vals) in enumerate(snaps):
        fig, ax = plt.subplots(figsize=(9, 4))
        tri = mtri.Triangulation(pts[:, 0], pts[:, 1])
        tp = ax.tricontourf(tri, vals, levels=45, cmap=cmap, vmin=vmin, vmax=vmax)
        # Recorte a la zona del perfil: el dominio completo (50c) deja el
        # alabe en un píxel y no se ve nada de interés.
        ax.set_xlim(-0.4, 1.8)
        ax.set_ylim(-0.7, 0.7)
        cb = fig.colorbar(tp, ax=ax, shrink=0.85, pad=0.02)
        cb.set_label(label)
        ax.set_aspect("equal")
        ax.set_xlabel("x/c")
        ax.set_ylabel("y/c")
        ax.set_title(f"{label} — t = {t:g} s", fontsize=11)
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, f"f_{k:04d}.png"), dpi=110,
                    facecolor="white")
        plt.close(fig)
        if (k + 1) % 10 == 0 or k == len(snaps) - 1:
            print(f"  {k + 1}/{len(snaps)}")

    return encode(out_dir, out_path, fps=fps)


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["solid", "fluid"], required=True)
    ap.add_argument("--frames", help="directorio con frame_*.npz (sólido)")
    ap.add_argument("--case", help="directorio del caso OpenFOAM (fluido)")
    ap.add_argument("--field", default="p", help="campo del fluido")
    ap.add_argument("--out-dir", default="/tmp/vidframes")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--fps", type=int, default=12)
    args = ap.parse_args(argv)

    if args.mode == "solid":
        if not args.frames:
            ap.error("--frames es obligatorio en modo solid")
        out = args.output or "von_mises.mp4"
        p = render_solid(args.frames, args.out_dir, args.fps, out)
    else:
        if not args.case:
            ap.error("--case es obligatorio en modo fluid")
        out = args.output or "cfd.mp4"
        p = render_fluid(args.case, args.out_dir, args.field, args.fps, out)

    print("MP4:", p, os.path.getsize(p), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
