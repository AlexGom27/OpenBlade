#!/usr/bin/env python3
"""Genera las figuras del informe de validación de OpenBlade 2D.

Lee los casos de validation/cases/lu_fine_a{0,2,4,6} y produce:
  - malla (dominio completo y detalle del perfil)
  - Cp sobre el perfil
  - contornos de velocidad (campo lejano y detalle)
  - contornos de presión
  - campo de turbulencia (k, nut)
  - curvas de rendimiento Cl/Cd/LD vs alpha
  - convergencia (residuos y coeficientes)

Uso: python3 validation/make_figures.py
"""

from __future__ import annotations

import json
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize

import pyvista as pv

CASES = os.path.join(HERE, "cases")
OUT = os.path.join(HERE, "figures")
os.makedirs(OUT, exist_ok=True)

ALPHAS = [0, 2, 4, 6]
RE_LABEL = "Re = 2.0×10⁶, M = 0.15"
DPI = 200


# --------------------------------------------------------------------------
def load_case(aoa: int):
    """Devuelve (internal, boundary_blocks, reader) del último tiempo."""
    case = os.path.join(CASES, f"lu_fine_a{aoa}")
    foam = os.path.join(case, "case.foam")
    if not os.path.exists(foam):
        open(foam, "w").close()
    r = pv.OpenFOAMReader(foam)
    r.set_active_time_value(r.time_values[-1])
    multi = r.read()
    internal = multi["internalMesh"]
    boundary = multi["boundary"]
    return internal, boundary, r


def airfoil_patch(boundary):
    for i in range(boundary.n_blocks):
        if "airfoil" in (boundary.get_block_name(i) or "").lower():
            return boundary.get_block(i)
    return None


def slice_z0(mesh):
    """El caso es 2D extrudido (z de 0 a depth): corta en el plano medio.

    Cortar en z=0 devuelve 0 puntos porque coincide con la cara de contorno.
    """
    z0, z1 = mesh.bounds[4], mesh.bounds[5]
    if z1 - z0 < 1e-9:
        return mesh
    return mesh.slice(normal="z", origin=(0, 0, (z0 + z1) / 2.0))


def add_airfoil_outline(ax, boundary, color="k", lw=1.0):
    af = airfoil_patch(boundary)
    if af is None:
        return
    pts = af.points
    ax.plot(pts[:, 0], pts[:, 1], color=color, linewidth=lw, zorder=5)


def save(fig, name):
    path = os.path.join(OUT, name)
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  ->", name)
    return path


# --------------------------------------------------------------------------
# 1. Malla
# --------------------------------------------------------------------------
def fig_mesh():
    internal, boundary, _ = load_case(4)
    s = slice_z0(internal)

    # Dominio completo: aristas de todas las celdas del plano
    fig, ax = plt.subplots(figsize=(9, 6.5))
    from matplotlib.collections import LineCollection
    e = s.extract_all_edges()
    segs = []
    if e.n_lines:
        conn = e.lines.reshape(-1, 3)[:, 1:]
        pts = e.points
        segs = [pts[[a, b]][:, :2] for a, b in conn]
    if segs:
        ax.add_collection(LineCollection(segs, linewidths=0.12, colors="#6b6b6b"))
    add_airfoil_outline(ax, boundary, color="#c62828", lw=1.2)
    ax.set_xlim(s.bounds[0], s.bounds[1])
    ax.set_ylim(s.bounds[2], s.bounds[3])
    ax.set_aspect("equal")
    ax.set_xlabel("x/c")
    ax.set_ylabel("y/c")
    ax.set_title(f"Malla CFD — dominio completo (50c)\n{internal.n_cells} celdas, "
                 f"{internal.n_points} nodos, α = 4°", fontsize=11)
    ax.grid(True, alpha=0.15)
    save(fig, "fig01_malla_dominio.png")

    # Detalle del perfil
    fig, ax = plt.subplots(figsize=(9, 5))
    x0, x1 = -0.35, 1.45
    y0, y1 = -0.45, 0.45
    near = []
    for seg in segs:
        if (seg[:, 0].min() > x0 and seg[:, 0].max() < x1
                and seg[:, 1].min() > y0 and seg[:, 1].max() < y1):
            near.append(seg)
    if near:
        ax.add_collection(LineCollection(near, linewidths=0.35, colors="#6b6b6b"))
    add_airfoil_outline(ax, boundary, color="#c62828", lw=1.4)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.set_xlabel("x/c")
    ax.set_ylabel("y/c")
    ax.set_title("Detalle de malla en el perfil — capa límite de 30 capas, y⁺ ≈ 0.04", fontsize=11)
    ax.grid(True, alpha=0.15)
    save(fig, "fig02_malla_detalle.png")


# --------------------------------------------------------------------------
# 2. Cp
# --------------------------------------------------------------------------
def fig_cp():
    from core.postprocessing import PostProcessor

    fig, ax = plt.subplots(figsize=(8, 5.5))
    colors = {0: "#1f77b4", 2: "#2ca02c", 4: "#d62728", 6: "#9467bd"}
    for a in ALPHAS:
        pp = PostProcessor(os.path.join(CASES, f"lu_fine_a{a}"))
        d = pp.get_cp_on_surface(u_inf=15.0)
        if not d:
            continue
        xu, cpu, xl, cpl = d
        ax.plot(xu, -cpu, "-", color=colors[a], lw=1.6, label=f"α={a}° extradós")
        ax.plot(xl, -cpl, "--", color=colors[a], lw=1.3, alpha=0.75,
                label=f"α={a}° intradós")
    ax.invert_yaxis()
    ax.set_xlabel("x/c")
    ax.set_ylabel("−Cp  (succión hacia arriba)")
    ax.set_title(f"Distribución de presión sobre el perfil NACA 0012\n{RE_LABEL}", fontsize=11)
    ax.grid(True, ls="--", alpha=0.35)
    ax.legend(fontsize=7.5, ncol=2, loc="lower left")
    save(fig, "fig03_cp.png")


# --------------------------------------------------------------------------
# 3/4/5. Campos (velocidad, presión, turbulencia)
# --------------------------------------------------------------------------
def _field_plot(mesh_2d, ax, field, title, cmap, label, vmin=None, vmax=None,
                levels=40, logscale=False, clip_floor=None):
    data = mesh_2d.point_data.get(field)
    if data is None:
        data = mesh_2d.cell_data.get(field)
        if data is not None:
            mesh_2d = mesh_2d.cell_data_to_point_data()
            data = mesh_2d.point_data.get(field)
    if data is None:
        ax.text(0.5, 0.5, f"campo '{field}' no disponible", ha="center", transform=ax.transAxes)
        return
    # Triangulación construida desde las CARAS REALES de la malla.
    #
    # Dos requisitos a la vez:
    #   1. No triangular la nube de puntos: Delaunay no sabe que el perfil es
    #      un hueco y lo rellenaría con triángulos espurios, pintando contornos
    #      DENTRO del alabe.
    #   2. Interpolar entre nodos: un color plano por celda (PolyCollection)
    #      hace visible el reticulado de la malla.
    #
    # Abanicar cada polígono en triángulos cumple ambos.
    import matplotlib.tri as mtri
    from core.field_render import mesh_triangulation

    nodal = np.asarray(data).ravel()
    pts, tris = mesh_triangulation(mesh_2d)

    if clip_floor is not None:
        nodal = np.maximum(nodal, clip_floor)
        vmin = clip_floor
    if vmin is None:
        vmin = float(np.nanmin(nodal))
    if vmax is None:
        vmax = float(np.nanpercentile(nodal, 99.5))

    # Escala logarítmica opcional: k y nut abarcan 6 órdenes de magnitud y en
    # escala lineal todo lo que no está en la estela se ve negro.
    if logscale:
        # k y nut abarcan 6 órdenes: niveles logarítmicos y norm=LogNorm.
        # Sin el norm explícito, tricontourf aplica una escala lineal a los
        # niveles logarítmicos y el resultado queda casi todo negro.
        from matplotlib.colors import LogNorm
        floor = clip_floor if clip_floor else max(float(np.nanmin(nodal[nodal > 0])), 1e-12)
        nodal = np.maximum(nodal, floor)
        vmin = floor
        levels_ = np.logspace(np.log10(floor), np.log10(vmax), levels)
        cb_label = label + "  (escala log)"
        pc = ax.tricontourf(
            mtri.Triangulation(pts[:, 0], pts[:, 1], triangles=tris),
            nodal, levels=levels_, cmap=cmap,
            norm=LogNorm(vmin=floor, vmax=vmax), extend="both")
    else:
        levels_ = np.linspace(vmin, vmax, levels)
        cb_label = label
        pc = ax.tricontourf(mtri.Triangulation(pts[:, 0], pts[:, 1], triangles=tris),
                            nodal, levels=levels_, cmap=cmap,
                            vmin=vmin, vmax=vmax, extend="both")
    cb = plt.colorbar(pc, ax=ax, shrink=0.85, pad=0.02)
    if logscale:
        from matplotlib.ticker import LogFormatterMathtext
        cb.formatter = LogFormatterMathtext(base=10)
        cb.update_ticks()
    cb.set_label(cb_label)
    ax.set_aspect("equal")
    ax.set_xlabel("x/c")
    ax.set_ylabel("y/c")
    ax.set_title(title, fontsize=11)
    return vmin, vmax


def fig_velocity():
    internal, boundary, _ = load_case(4)
    s = slice_z0(internal)

    # Campo lejano
    u = s.point_data.get("U")
    if u is None:
        u = s.cell_data.get("U")
        s = s.cell_data_to_point_data()
        u = s.point_data["U"]
    mag = np.linalg.norm(np.asarray(u), axis=1)
    s.point_data["Umag"] = mag

    fig, ax = plt.subplots(figsize=(9, 5.5))
    _field_plot(s, ax, "Umag",
                "Campo de velocidad — |U| [m/s], dominio completo, α = 4°",
                "turbo", "|U| [m/s]")
    add_airfoil_outline(ax, boundary, color="k", lw=1.0)
    save(fig, "fig04_velocidad_dominio.png")

    # Detalle cerca del perfil. NO se recorta la malla con clip_box: eso parte
    # las celdas y deja un mosaico de triángulos sueltos. Se dibuja el dominio
    # completo y se limita la VISTA, que no toca la topología.
    fig, ax = plt.subplots(figsize=(9, 5))
    _field_plot(s, ax, "Umag",
                "Detalle de velocidad: borde de ataque, extradós y estela, α = 4°",
                "turbo", "|U| [m/s]", levels=50, vmin=0, vmax=22)
    add_airfoil_outline(ax, boundary, color="k", lw=1.2)
    ax.set_xlim(-0.32, 1.6)
    ax.set_ylim(-0.36, 0.36)
    save(fig, "fig05_velocidad_detalle.png")


def fig_pressure():
    internal, boundary, _ = load_case(4)
    s = slice_z0(internal)
    fig, ax = plt.subplots(figsize=(9, 5))
    _field_plot(s, ax, "p",
                "Campo de presión — p [m²/s²] (cinemática), α = 4°",
                "coolwarm", "p [m²/s²]")
    add_airfoil_outline(ax, boundary, color="k", lw=1.2)
    ax.set_xlim(-0.6, 2.2)
    ax.set_ylim(-0.7, 0.7)
    save(fig, "fig06_presion.png")


def fig_turbulence():
    internal, boundary, _ = load_case(4)
    s = slice_z0(internal)

    fig, ax = plt.subplots(figsize=(9, 5))
    _field_plot(s, ax, "k",
                "Energía cinética de turbulencia — k [m²/s²], α = 4°",
                "magma", "k [m²/s²]", levels=45, logscale=True, clip_floor=1e-6)
    add_airfoil_outline(ax, boundary, color="w", lw=1.2)
    ax.set_xlim(-0.6, 2.2)
    ax.set_ylim(-0.7, 0.7)
    save(fig, "fig07_turbulencia_k.png")

    fig, ax = plt.subplots(figsize=(9, 5))
    _field_plot(s, ax, "nut",
                "Viscosidad turbulenta — νt [m²/s], α = 4°",
                "viridis", "νt [m²/s]", levels=45, logscale=True, clip_floor=1e-8)
    add_airfoil_outline(ax, boundary, color="r", lw=1.2)
    ax.set_xlim(-0.6, 2.2)
    ax.set_ylim(-0.7, 0.7)
    save(fig, "fig08_turbulencia_nut.png")


# --------------------------------------------------------------------------
# 6. Rendimiento
# --------------------------------------------------------------------------
def load_results():
    path = os.path.join(HERE, "results_lu_fine.json")
    with open(path) as f:
        d = json.load(f)
    by_a = {r["aoa"]: r for r in d["results"] if r.get("ok")}
    return by_a


def nasa_table():
    rows = {}
    for line in open(os.path.join(HERE, "nasa_tm4074_naca0012.csv")):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        t, a, cl, cd, cm = line.split(",")
        if t == "VII":
            rows[float(a)] = (float(cl), float(cd), float(cm))
    return rows


def interp(rows, x):
    xs = sorted(rows)
    if x <= xs[0]:
        return rows[xs[0]]
    if x >= xs[-1]:
        return rows[xs[-1]]
    for a, b in zip(xs, xs[1:]):
        if a <= x <= b:
            t = (x - a) / (b - a)
            return tuple(rows[a][i] + t * (rows[b][i] - rows[a][i]) for i in range(3))
    return rows[xs[-1]]


def fig_performance():
    res = load_results()
    nasa = nasa_table()
    alphas = sorted(res)
    cl = [res[a]["Cl"] for a in alphas]
    cd = [res[a]["Cd"] for a in alphas]
    ld = [c / d if d else 0 for c, d in zip(cl, cd)]

    nasa_cl = [interp(nasa, a)[0] for a in alphas]
    nasa_cd = [interp(nasa, a)[1] for a in alphas]

    fig, axes = plt.subplots(3, 1, figsize=(8, 10), sharex=True)

    ax = axes[0]
    ax.plot(alphas, cl, "o-", color="#c62828", lw=2, ms=7, label="OpenBlade 2D")
    ax.plot(alphas, nasa_cl, "s--", color="#1565c0", lw=1.8, ms=6,
            label="NASA TM 4074 Tabla VII")
    ax.set_ylabel("C_l")
    ax.set_title("Curva de sustentación", fontsize=10)
    ax.grid(True, ls="--", alpha=0.35)
    ax.legend(fontsize=8)

    ax = axes[1]
    ax.plot(alphas, cd, "o-", color="#c62828", lw=2, ms=7, label="OpenBlade 2D")
    ax.plot(alphas, nasa_cd, "s--", color="#1565c0", lw=1.8, ms=6, label="NASA Tabla VII")
    ax.set_ylabel("C_d")
    ax.set_title("Curva de arrastre", fontsize=10)
    ax.grid(True, ls="--", alpha=0.35)
    ax.legend(fontsize=8)

    ax = axes[2]
    ax.plot(alphas, ld, "o-", color="#2e7d32", lw=2, ms=7, label="OpenBlade 2D")
    nasa_ld = [c / d for c, d in zip(nasa_cl, nasa_cd)]
    ax.plot(alphas, nasa_ld, "s--", color="#1565c0", lw=1.8, ms=6, label="NASA Tabla VII")
    ax.set_ylabel("L/D")
    ax.set_xlabel("α [°]")
    ax.set_title("Eficiencia aerodinámica", fontsize=10)
    ax.grid(True, ls="--", alpha=0.35)
    ax.legend(fontsize=8)

    fig.suptitle(f"Curvas de rendimiento — NACA 0012\n{RE_LABEL}", fontsize=12)
    fig.tight_layout()
    save(fig, "fig09_rendimiento.png")

    # Polar Cl-Cd
    fig, ax = plt.subplots(figsize=(7, 5.5))
    ax.plot(cd, cl, "o-", color="#c62828", lw=2, ms=7, label="OpenBlade 2D")
    ax.plot(nasa_cd, nasa_cl, "s--", color="#1565c0", lw=1.8, ms=6, label="NASA Tabla VII")
    for a in alphas:
        ax.annotate(f"{a}°", (res[a]["Cd"], res[a]["Cl"]), textcoords="offset points",
                    xytext=(6, 4), fontsize=7.5, color="#c62828")
    ax.set_xlabel("C_d")
    ax.set_ylabel("C_l")
    ax.set_title("Polar de arrastre", fontsize=11)
    ax.grid(True, ls="--", alpha=0.35)
    ax.legend(fontsize=9)
    save(fig, "fig10_polar.png")


# --------------------------------------------------------------------------
# 7. Convergencia
# --------------------------------------------------------------------------
def fig_convergence():
    case = os.path.join(CASES, "lu_fine_a4")
    log = os.path.join(case, "solver.log")
    if not os.path.exists(log):
        print("  (sin solver.log, se omite convergencia)")
        return

    txt = open(log, errors="replace").read()
    it = 0
    res = {}
    for line in txt.splitlines():
        m = re.match(r"^Time = (\d+)", line)
        if m:
            it = int(m.group(1))
            continue
        mm = re.search(r"Solving for (\w+), Initial residual = ([\d.eE+-]+)", line)
        if mm:
            res.setdefault(mm.group(1), []).append((it, float(mm.group(2))))

    fig, ax = plt.subplots(figsize=(8, 5))
    # 'Phi' es el flujo masico por cara: no es un residual de campo y su magnitud
    # aplasta el resto de curvas. Se excluye de la grafica.
    for name, series in res.items():
        if name == "Phi":
            continue
        xs = [p[0] for p in series]
        ys = [p[1] for p in series]
        ax.semilogy(xs, ys, lw=1.3, label=name)
    ax.axhline(1e-5, color="k", ls=":", lw=1, label="tolerancia 1e-5")
    ax.set_xlabel("Iteración")
    ax.set_ylabel("Residual inicial")
    ax.set_title("Convergencia — α = 4°, linearUpwind, malla fina", fontsize=11)
    ax.grid(True, which="both", ls="--", alpha=0.3)
    ax.legend(fontsize=8, ncol=2)
    save(fig, "fig11_convergencia.png")

    # Coeficientes vs iteración
    coef = os.path.join(case, "postProcessing", "forceCoeffs", "0", "coefficient.dat")
    if os.path.exists(coef):
        rows = []
        for line in open(coef):
            if line.strip().startswith("#") or not line.strip():
                continue
            p = line.split()
            rows.append((float(p[0]), float(p[1]), float(p[4])))
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot([r[0] for r in rows], [r[1] for r in rows], lw=1.0, color="#c62828", label="C_d")
        ax.plot([r[0] for r in rows], [r[2] for r in rows], lw=1.0, color="#1565c0", label="C_l")
        ax.set_xlabel("Iteración")
        ax.set_ylabel("Coeficiente")
        ax.set_title("Evolución de coeficientes hasta convergencia (α = 4°)", fontsize=11)
        ax.grid(True, ls="--", alpha=0.35)
        ax.legend(fontsize=9)
        save(fig, "fig12_coeficientes.png")


# --------------------------------------------------------------------------
def main():
    print("Generando figuras en", OUT)
    fig_mesh()
    fig_cp()
    fig_velocity()
    fig_pressure()
    fig_turbulence()
    fig_performance()
    fig_convergence()
    print("Listo.")


if __name__ == "__main__":
    main()
