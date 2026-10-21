#!/usr/bin/env python3
"""Solver estructural 2D acoplado a preCICE.

Resuelve una viga/placa bidimensional en elasticidad lineal con elementos
finitos Q4 (bilineales), bajo carga distribuida que llega del fluido.

Formulación
-----------
Problema de elasticidad 2D en estado plano de tensiones:

    -div(σ) = 0,      σ = D : ε,      ε = ½(∇u + ∇uᵀ)

con

    D = E/(1-ν²) · [[1, ν, 0],
                    [ν, 1, 0],
                    [0, 0, (1-ν)/2]]

que es la matriz constitutiva de tensión plana. El sólido se discretiza con
elementos Q4 isoparamétricos de 4 nodos e integración 2×2 de Gauss.

Acoplamiento
------------
El participante se llama ``Solid`` y habla con preCICE por sockets:

  - LEE  ``Stress``       en la malla ``Solid-Mesh``  (fuerza del fluido)
  - ESCRIBE ``Displacement`` en la malla ``Solid-Mesh``

La malla de interfaz son los nodos del borde cargado. El resto del sólido está
empotrado.

Uso
---
    python3 core/structural_solver.py --config precice-config.xml \\
            --participant Solid --E 2e6 --nu 0.3 --thickness 0.1

En modo ``--dry-run`` resuelve un caso de validación sin preCICE (placa
empotrada con carga puntual) y compara con la solución analítica.
"""

from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np


# --------------------------------------------------------------------------
# Elemento Q4
# --------------------------------------------------------------------------
def q4_shape(xi: float, eta: float):
    """Funciones de forma del elemento bilineal y sus derivadas."""
    N = 0.25 * np.array([
        (1 - xi) * (1 - eta),
        (1 + xi) * (1 - eta),
        (1 + xi) * (1 + eta),
        (1 - xi) * (1 + eta),
    ])
    dN_dxi = 0.25 * np.array([
        -(1 - eta), (1 - eta), (1 + eta), -(1 + eta),
    ])
    dN_deta = 0.25 * np.array([
        -(1 - xi), -(1 + xi), (1 + xi), (1 - xi),
    ])
    return N, dN_dxi, dN_deta


def q4_stiffness(coords: np.ndarray, D: np.ndarray, thickness: float) -> np.ndarray:
    """Matriz de rigidez de un Q4 (8×8) por integración 2×2 de Gauss.

    coords: (4, 2) coordenadas nodales en sentido antihorario.
    """
    Ke = np.zeros((8, 8))
    g = 1.0 / math.sqrt(3.0)
    gauss = [(-g, -g), (g, -g), (g, g), (-g, g)]

    for xi, eta in gauss:
        N, dN_dxi, dN_deta = q4_shape(xi, eta)

        # Jacobiano
        J = np.array([
            [dN_dxi @ coords[:, 0], dN_dxi @ coords[:, 1]],
            [dN_deta @ coords[:, 0], dN_deta @ coords[:, 1]],
        ])
        detJ = np.linalg.det(J)
        if detJ <= 0:
            raise ValueError(f"Elemento con Jacobiano no positivo (detJ={detJ:.3e})")
        invJ = np.linalg.inv(J)

        # Derivadas globales
        dN = np.zeros((4, 2))
        for i in range(4):
            dN[i, :] = invJ @ np.array([dN_dxi[i], dN_deta[i]])

        # Matriz B (3×8)
        B = np.zeros((3, 8))
        for i in range(4):
            B[0, 2 * i] = dN[i, 0]
            B[1, 2 * i + 1] = dN[i, 1]
            B[2, 2 * i] = dN[i, 1]
            B[2, 2 * i + 1] = dN[i, 0]

        Ke += thickness * detJ * (B.T @ D @ B)

    return Ke


def plane_stress_D(E: float, nu: float) -> np.ndarray:
    c = E / (1.0 - nu * nu)
    return c * np.array([
        [1.0, nu, 0.0],
        [nu, 1.0, 0.0],
        [0.0, 0.0, (1.0 - nu) / 2.0],
    ])


# --------------------------------------------------------------------------
# Malla estructurada
# --------------------------------------------------------------------------
def build_plate_mesh(nx: int, ny: int, length: float, height: float):
    """Malla rectangular estructurada. Devuelve nodos y conectividad.

    El origen está en el borde empotrado (x=0). El borde libre es x=length.
    """
    xs = np.linspace(0.0, length, nx + 1)
    ys = np.linspace(0.0, height, ny + 1)
    nodes = np.array([[x, y] for y in ys for x in xs], dtype=float)

    def nid(i, j):
        return j * (nx + 1) + i

    elems = []
    for j in range(ny):
        for i in range(nx):
            elems.append([nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)])
    return nodes, np.array(elems, dtype=int)


def assemble(nodes, elems, D, thickness):
    ndof = 2 * len(nodes)
    K = np.zeros((ndof, ndof))
    for e in elems:
        Ke = q4_stiffness(nodes[e], D, thickness)
        idx = np.empty(8, dtype=int)
        idx[0::2] = 2 * e
        idx[1::2] = 2 * e + 1
        K[np.ix_(idx, idx)] += Ke
    return K


def solve_dirichlet(K, F, fixed_dofs):
    """Resuelve K u = F imponiendo u=0 en fixed_dofs (eliminación)."""
    free = np.setdiff1d(np.arange(len(F)), fixed_dofs)
    u = np.zeros_like(F)
    u[free] = np.linalg.solve(K[np.ix_(free, free)], F[free])
    return u


# --------------------------------------------------------------------------
# Validación analítica: viga empotrada con carga puntual
# --------------------------------------------------------------------------
def validate_cantilever(E=2.0e6, nu=0.3, L=1.0, h=0.1, thickness=0.1,
                        P=-1.0, nx=40, ny=8) -> dict:
    """Compara la flecha en el extremo con la teoría de Euler-Bernoulli.

    δ = P·L³ / (3·E·I),  I = thickness·h³/12
    """
    nodes, elems = build_plate_mesh(nx, ny, L, h)
    D = plane_stress_D(E, nu)
    K = assemble(nodes, elems, D, thickness)

    F = np.zeros(2 * len(nodes))
    # Carga puntual repartida entre los dos nodos de la esquina libre
    tip = [i for i, p in enumerate(nodes) if abs(p[0] - L) < 1e-12]
    tip.sort(key=lambda i: nodes[i, 1])
    F[2 * tip[0] + 1] += P / 2.0
    F[2 * tip[-1] + 1] += P / 2.0

    # Empotramiento en x=0
    fixed = []
    for i, p in enumerate(nodes):
        if abs(p[0]) < 1e-12:
            fixed += [2 * i, 2 * i + 1]

    u = solve_dirichlet(K, F, np.array(fixed))

    delta_fem = float(np.mean([u[2 * i + 1] for i in tip]))
    I = thickness * h ** 3 / 12.0
    delta_theory = P * L ** 3 / (3.0 * E * I)

    return {
        "delta_fem": delta_fem,
        "delta_theory": delta_theory,
        "error_pct": (delta_fem - delta_theory) / delta_theory * 100.0,
        "n_nodes": int(len(nodes)),
        "n_elems": int(len(elems)),
    }


# --------------------------------------------------------------------------
# Acoplamiento con preCICE
# --------------------------------------------------------------------------
class StructuralSolver:
    """Sólido 2D acoplado a preCICE.

    La interfaz son los nodos del borde libre (x = L). El resto está empotrado
    en x = 0; los laterales se dejan libres.
    """

    def __init__(self, config_file: str, participant: str = "Solid",
                 mesh_name: str = "Solid-Mesh",
                 read_data: str = "Stress", write_data: str = "Displacement",
                 E: float = 2.0e6, nu: float = 0.3, thickness: float = 0.1,
                 length: float = 1.0, height: float = 0.1,
                 nx: int = 40, ny: int = 8) -> None:
        import precice  # import local: sólo se necesita en modo acoplado

        self.precice = precice
        self.participant = precice.Participant(
            participant, config_file, 0, 1
        )
        self.mesh_name = mesh_name
        self.read_data = read_data
        self.write_data = write_data

        self.nodes, self.elems = build_plate_mesh(nx, ny, length, height)
        self.D = plane_stress_D(E, nu)
        self.thickness = thickness
        self.K = assemble(self.nodes, self.elems, self.D, thickness)

        # Interfaz: borde libre x = L
        self.interface = np.array(
            [i for i, p in enumerate(self.nodes) if abs(p[0] - length) < 1e-12],
            dtype=int,
        )
        # Empotramiento: x = 0
        fixed = []
        for i, p in enumerate(self.nodes):
            if abs(p[0]) < 1e-12:
                fixed += [2 * i, 2 * i + 1]
        self.fixed = np.array(fixed, dtype=int)

        # Malla declarada con dimensions="2": preCICE exige coordenadas 2D.
        # (Con dimensions="3" habría que añadir z=0; no mezclar ambas.)
        coords = self.nodes[self.interface].astype(float)

        self.vertex_ids = self.participant.set_mesh_vertices(
            mesh_name, coords
        )

    def run(self) -> dict:
        p = self.participant

        # El exchange lleva `initialize="true"`: el participante que escribe el
        # dato inicial debe hacerlo ANTES de initialize(), o preCICE aborta con
        # "Initial data has to be written to preCICE before calling initialize()".
        if p.requires_initial_data():
            disp0 = np.zeros((len(self.interface), 2))
            p.write_data(self.mesh_name, self.write_data, self.vertex_ids, disp0)

        p.initialize()

        n_blocks = 0
        max_disp = 0.0
        while p.is_coupling_ongoing():
            # En acoplamiento implícito preCICE exige gestionar checkpoints:
            # el estado es implícito (u se recalcula de la carga), así que no
            # hay nada que guardar, pero la llamada es obligatoria.
            if p.requires_writing_checkpoint():
                pass

            dt = p.get_max_time_step_size()

            # Fuerza que llega del fluido, en los nodos de interfaz
            stress = p.read_data(self.mesh_name, self.read_data,
                                 self.vertex_ids, dt)

            # Ensamblar carga: cada nodo de interfaz recibe (fx, fy)
            F = np.zeros(2 * len(self.nodes))
            for k, nid in enumerate(self.interface):
                F[2 * nid] += float(stress[k][0])
                F[2 * nid + 1] += float(stress[k][1])

            u = solve_dirichlet(self.K, F, self.fixed)

            # Desplazamiento 2D, coherente con la dimensión de la malla
            disp = np.column_stack([
                u[2 * self.interface],
                u[2 * self.interface + 1],
            ])
            p.write_data(self.mesh_name, self.write_data, self.vertex_ids, disp)

            max_disp = max(max_disp, float(np.abs(u).max()))

            p.advance(dt)

            if p.requires_reading_checkpoint():
                pass  # sin estado que restaurar

            n_blocks += 1

        p.finalize()
        return {"time_windows": n_blocks, "max_displacement": max_disp}


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Solver estructural 2D (preCICE / validación)")
    ap.add_argument("--config", help="precice-config.xml")
    ap.add_argument("--participant", default="Solid")
    ap.add_argument("--mesh", default="Solid-Mesh")
    ap.add_argument("--read-data", default="Stress")
    ap.add_argument("--write-data", default="Displacement")
    ap.add_argument("--E", type=float, default=2.0e6)
    ap.add_argument("--nu", type=float, default=0.3)
    ap.add_argument("--thickness", type=float, default=0.1)
    ap.add_argument("--length", type=float, default=1.0)
    ap.add_argument("--height", type=float, default=0.1)
    ap.add_argument("--nx", type=int, default=40)
    ap.add_argument("--ny", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true",
                    help="sólo validación analítica, sin preCICE")
    args = ap.parse_args(argv)

    if args.dry_run:
        r = validate_cantilever(E=args.E, nu=args.nu, L=args.length,
                                h=args.height, thickness=args.thickness,
                                nx=args.nx, ny=args.ny)
        print(json.dumps(r, indent=2))
        return 0

    if not args.config:
        ap.error("--config es obligatorio salvo con --dry-run")

    s = StructuralSolver(
        config_file=args.config, participant=args.participant,
        mesh_name=args.mesh, read_data=args.read_data,
        write_data=args.write_data, E=args.E, nu=args.nu,
        thickness=args.thickness, length=args.length, height=args.height,
        nx=args.nx, ny=args.ny,
    )
    out = s.run()
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
