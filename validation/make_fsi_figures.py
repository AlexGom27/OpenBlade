#!/usr/bin/env python3
"""Figuras para la sección FSI del informe.

Genera:
  - esquema de la arquitectura fluido-estructura
  - caso del perfil (interfaz = cáscara)
  - caso del benchmark Turek & Hron (geometría)
  - convergencia del acoplamiento y fuerza medida
"""

from __future__ import annotations

import json
import os
import re
import sys

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
OUT = os.path.join(HERE, "figures")
os.makedirs(OUT, exist_ok=True)


def save(fig, name):
    path = os.path.join(OUT, name)
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  ->", name)


# --------------------------------------------------------------------------
def fig_architecture():
    """Esquema de los dos participantes y el acoplamiento."""
    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.set_xlim(0, 10)
    ax.set_ylim(-0.2, 6.6)
    ax.axis("off")

    def box(x, y, w, h, title, lines, color):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.12",
                                    facecolor=color, edgecolor="#333", lw=1.2))
        ax.text(x + w / 2, y + h - 0.42, title, ha="center", va="top",
                fontsize=10.5, fontweight="bold", color="#1a1a1a")
        for i, ln in enumerate(lines):
            ax.text(x + w / 2, y + h - 0.95 - i * 0.38, ln, ha="center",
                    va="top", fontsize=8.0, color="#333")

    box(0.4, 3.2, 3.5, 2.2, "Fluido (OpenFOAM)",
        ["pimpleFoam", "malla dinámica", "preciceDict + adapter"],
        "#dbe9f7")
    box(6.1, 3.2, 3.5, 2.2, "Sólido (Python)",
        ["elasticidad 2D", "elementos Q4", "pyprecice"],
        "#f7e8db")

    box(3.0, 1.2, 4.0, 2.0, "preCICE 3.4.1",
        ["m2n:sockets", "mapeo nearest-neighbor", "Aitken + serial-implicit"],
        "#e8e8e8")

    ax.annotate("", xy=(6.0, 4.9), xytext=(4.0, 4.9),
                arrowprops=dict(arrowstyle="->", lw=1.6, color="#1565c0"))
    ax.text(5.0, 5.12, "Stress (N/m²)", ha="center", fontsize=8.6, color="#1565c0")

    ax.annotate("", xy=(4.0, 3.9), xytext=(6.0, 3.9),
                arrowprops=dict(arrowstyle="->", lw=1.6, color="#c62828"))
    ax.text(5.0, 4.12, "Displacement (m)", ha="center", fontsize=8.6, color="#c62828")

    for x in (2.15, 7.85):
        ax.annotate("", xy=(x, 3.1), xytext=(x, 3.25),
                    arrowprops=dict(arrowstyle="-", lw=1.3, color="#555"))
        ax.annotate("", xy=(x, 3.25), xytext=(x, 3.1),
                    arrowprops=dict(arrowstyle="<->", lw=1.3, color="#555"))

    ax.text(5.0, 0.55, "acoplamiento iterativo hasta convergencia por ventana de tiempo",
            ha="center", fontsize=8.4, style="italic", color="#555")

    ax.set_title("Arquitectura del acoplamiento fluido-estructura", fontsize=12)
    save(fig, "fig13_arquitectura_fsi.png")


def fig_profile_interface():
    """Cáscara del perfil: interfaz exterior = contorno del airfoil."""
    from core.structural_solver import build_shell_mesh, naca0012_contour

    c = naca0012_contour(120)
    nodes, elems, n_iface = build_shell_mesh(c, 0.01, 3)

    fig, ax = plt.subplots(figsize=(9, 3.2))
    for el in elems:
        q = nodes[el]
        ax.add_patch(plt.Polygon(q, closed=True, fill=False,
                                 edgecolor="#9bb8d3", lw=0.35))
    ax.plot(c[:, 0], c[:, 1], "-", color="#c62828", lw=1.6,
            label=f"interfaz = contorno del perfil ({n_iface} nodos)")
    ax.set_aspect("equal")
    ax.set_xlabel("x/c")
    ax.set_ylabel("y/c")
    ax.set_title("Sólido como cáscara del perfil: la frontera exterior es el patch «airfoil»",
                 fontsize=10.5)
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(True, ls="--", alpha=0.25)
    save(fig, "fig14_cascara_perfil.png")


def fig_turek_geometry():
    """Geometría del benchmark FSI 1."""
    fig, ax = plt.subplots(figsize=(9.5, 2.9))

    ax.add_patch(Rectangle((0, 0), 2.5, 0.41, fill=False, edgecolor="#333", lw=1.5))
    ax.add_patch(Circle((0.2, 0.2), 0.05, facecolor="#bdbdbd",
                        edgecolor="#333", lw=1.2))
    ax.add_patch(Rectangle((0.6, 0.19), 0.35, 0.02, facecolor="#c62828",
                           edgecolor="#7f0000", lw=1.0))
    ax.plot(0.95, 0.2, "o", color="#0d47a1", ms=7, zorder=5)
    ax.annotate("A", (0.95, 0.2), textcoords="offset points", xytext=(4, 8),
                fontsize=9, color="#0d47a1", fontweight="bold")

    ax.annotate("cilindro r = 0.05", (0.2, 0.25), textcoords="offset points",
                xytext=(0, 34), fontsize=7.8, ha="center",
                arrowprops=dict(arrowstyle="-", lw=0.7, color="#555"))
    ax.annotate("flag 0.35 × 0.02", (0.775, 0.19), textcoords="offset points",
                xytext=(0, -26), fontsize=7.8, ha="center",
                arrowprops=dict(arrowstyle="-", lw=0.7, color="#555"))
    ax.annotate("entrada", (0, 0.41), textcoords="offset points",
                xytext=(26, 14), fontsize=7.8, color="#1565c0")
    ax.annotate("salida", (2.5, 0.41), textcoords="offset points",
                xytext=(-20, 14), fontsize=7.8, color="#1565c0")

    ax.set_xlim(-0.08, 2.58)
    ax.set_ylim(-0.07, 0.56)
    ax.set_aspect("equal")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.set_title("Geometría del benchmark Turek & Hron FSI 1 (canal 2.5 × 0.41 m)",
                 fontsize=10.5)
    save(fig, "fig15_turek_geometria.png")


def fig_coupling():
    """Convergencia del acoplamiento y fuerza medida."""
    case = os.path.join(HERE, "cases", "lu_fine_a4")
    log = os.path.join(case, "solver.log")

    # Panel izquierdo: convergencia del caso del perfil (del log guardado)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))

    ax = axes[0]
    # Datos de la corrida del perfil que convergió
    iters = [1, 2, 3]
    measures = [7.33e-1, 1.32e-1, 2.06e-2]
    ax.semilogy(iters, measures, "o-", color="#c62828", lw=1.8, ms=6)
    ax.axhline(5e-2, color="k", ls="--", lw=1, label="límite 5×10⁻²")
    ax.set_xlabel("iteración de acoplamiento")
    ax.set_ylabel("residuo relativo")
    ax.set_xticks(iters)
    ax.set_title("Convergencia — caso del perfil\n(3 iteraciones, «All converged»)",
                 fontsize=9.5)
    ax.grid(True, which="both", ls="--", alpha=0.3)
    ax.legend(fontsize=8)

    # Panel derecho: fuerza medida por dos caminos
    ax = axes[1]
    labels = ["forces\nfunctionObject", "adaptador\npreCICE"]
    vals = [468.3, 363.8]
    bars = ax.bar(labels, vals, color=["#1565c0", "#c62828"], width=0.55)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 8, f"{v:.1f} N",
                ha="center", fontsize=9)
    ax.set_ylabel("fuerza vertical sobre el flag [N]")
    ax.set_ylim(0, 540)
    ax.set_title("Fuerza transmitida — verificación cruzada\n(22% de diferencia)",
                 fontsize=9.5)
    ax.grid(True, axis="y", ls="--", alpha=0.3)

    fig.suptitle("Acoplamiento fluido-estructura: convergencia y consistencia",
                 fontsize=11.5)
    fig.tight_layout()
    save(fig, "fig16_acoplamiento.png")


def fig_force_convergence():
    """Fuerza frente al refinamiento de malla."""
    fig, ax = plt.subplots(figsize=(7, 4))
    h = [0.01, 0.002]
    f = [454.8, 468.3]
    ax.plot(h, f, "o-", color="#2e7d32", lw=1.8, ms=8)
    for xi, yi in zip(h, f):
        ax.annotate(f"{yi:.1f} N", (xi, yi), textcoords="offset points",
                    xytext=(8, 6), fontsize=8.5)
    ax.set_xscale("log")
    ax.invert_xaxis()
    ax.set_xlabel("tamaño de celda en el flag [m]")
    ax.set_ylabel("fuerza vertical [N]")
    ax.set_title("Convergencia de malla de la fuerza (2.9% entre niveles)",
                 fontsize=10.5)
    ax.grid(True, which="both", ls="--", alpha=0.3)
    save(fig, "fig17_fuerza_malla.png")


if __name__ == "__main__":
    print("Figuras FSI:")
    fig_architecture()
    fig_profile_interface()
    fig_turek_geometry()
    fig_coupling()
    fig_force_convergence()
    print("Listo.")
