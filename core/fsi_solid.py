"""Solver estructural 2D para el acoplamiento FSI de OpenBlade con preCICE.

Cubre el hueco que el plan dejaba abierto: `solidDisplacementFoam` existe en la
imagen pero no tiene adaptador preCICE, así que no puede hablar con el fluido.
Aquí el sólido se resuelve con FEM propio (elementos triangulares CST, tensión
plana) y se comunica con preCICE mediante pyprecice.

Modelo
------
- Placa rectangular 2D, espesor constante, material isótropo lineal elástico.
- Elementos triangulares de deformación constante (CST), hipótesis de tensión
  plana (`planeStress`).
- Borde izquierdo empotrado; el borde de interfaz recibe la tracción del fluido.

Acoplamiento
------------
El fluido envía `Stress` (tracción, Pa) sobre la malla del fluido; preCICE la
interpola a la malla del sólido. El sólido devuelve `Displacement` (m).

Limitaciones conocidas (documentadas, no ocultas)
-------------------------------------------------
- CST es rígido en flexión: converge, pero subestima la flecha con mallas
  gruesas. El test de viga en voladizo mide ese error y fija la tolerancia.
- La tracción se reparte por longitud tributaria del borde, sin integración
  de Gauss sobre la cara. Para el espesor y las cargas de este caso el error
  es de segundo orden en el tamaño de elemento.
- No hay no-linealidad geométrica ni plasticidad.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np


# --------------------------------------------------------------------------
# Material
# --------------------------------------------------------------------------
@dataclass
class SolidMaterial:
    """Propiedades elásticas lineales."""

    young: float = 70.0e9      # Pa (aluminio)
    poisson: float = 0.33
    thickness: float = 0.01    # m
    density: float = 2700.0    # kg/m3

    def plane_stress_matrix(self) -> np.ndarray:
        """Matriz constitutiva D (3x3) en tensión plana."""
        e, nu = self.young, self.poisson
        k = e / (1.0 - nu * nu)
        return k * np.array(
            [
                [1.0, nu, 0.0],
                [nu, 1.0, 0.0],
                [0.0, 0.0, (1.0 - nu) / 2.0],
            ]
        )


# --------------------------------------------------------------------------
# Malla estructurada
# --------------------------------------------------------------------------
@dataclass
class SolidMesh:
    """Malla rectangular structured de triángulos."""

    nodes: np.ndarray        # (n_nodes, 2)
    triangles: np.ndarray    # (n_tri, 3)
    fixed_nodes: np.ndarray  # índices empotrados
    interface_nodes: np.ndarray  # índices del borde de interfaz (ordenados)

    @property
    def n_nodes(self) -> int:
        return int(self.nodes.shape[0])

    @property
    def n_dof(self) -> int:
        return 2 * self.n_nodes


def build_rect_mesh(
    length: float,
    height: float,
    nx: int,
    ny: int,
    interface_edge: str = "top",
) -> SolidMesh:
    """Genera una malla rectangular de triángulos.

    El origen está en la esquina inferior izquierda. El borde ``x=0`` queda
    empotrado; ``interface_edge`` indica qué borde recibe la tracción.
    """
    if nx < 1 or ny < 1:
        raise ValueError("nx y ny deben ser >= 1")

    xs = np.linspace(0.0, length, nx + 1)
    ys = np.linspace(0.0, height, ny + 1)
    nodes = np.array([(x, y) for y in ys for x in xs], dtype=float)

    def nid(i: int, j: int) -> int:
        return j * (nx + 1) + i

    tris: List[Tuple[int, int, int]] = []
    for j in range(ny):
        for i in range(nx):
            n0, n1 = nid(i, j), nid(i + 1, j)
            n2, n3 = nid(i, j + 1), nid(i + 1, j + 1)
            tris.append((n0, n1, n2))
            tris.append((n1, n3, n2))

    fixed = np.array([nid(0, j) for j in range(ny + 1)], dtype=int)

    if interface_edge == "top":
        iface = np.array([nid(i, ny) for i in range(nx + 1)], dtype=int)
    elif interface_edge == "bottom":
        iface = np.array([nid(i, 0) for i in range(nx + 1)], dtype=int)
    elif interface_edge == "right":
        iface = np.array([nid(nx, j) for j in range(ny + 1)], dtype=int)
    else:
        raise ValueError(f"borde de interfaz desconocido: {interface_edge}")

    return SolidMesh(
        nodes=nodes,
        triangles=np.array(tris, dtype=int),
        fixed_nodes=fixed,
        interface_nodes=iface,
    )


# --------------------------------------------------------------------------
# FEM
# --------------------------------------------------------------------------
def cst_stiffness(nodes: np.ndarray, tri: np.ndarray, mat: SolidMaterial) -> np.ndarray:
    """Matriz de rigidez 6x6 de un triángulo CST en tensión plana."""
    p = nodes[tri]  # (3,2)
    x1, y1 = p[0]
    x2, y2 = p[1]
    x3, y3 = p[2]

    # Área con signo; se reordena si el triángulo está invertido.
    area2 = (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)
    if area2 < 0:
        tri = np.array([tri[0], tri[2], tri[1]], dtype=int)
        p = nodes[tri]
        x1, y1 = p[0]
        x2, y2 = p[1]
        x3, y3 = p[2]
        area2 = -area2
    area = 0.5 * area2

    b1, b2, b3 = (y2 - y3), (y3 - y1), (y1 - y2)
    c1, c2, c3 = (x3 - x2), (x1 - x3), (x2 - x1)

    B = np.array(
        [
            [b1, 0.0, b2, 0.0, b3, 0.0],
            [0.0, c1, 0.0, c2, 0.0, c3],
            [c1, b1, c2, b2, c3, b3],
        ]
    ) / (2.0 * area)

    D = mat.plane_stress_matrix()
    return mat.thickness * area * (B.T @ D @ B)


def assemble_stiffness(mesh: SolidMesh, mat: SolidMaterial) -> np.ndarray:
    """Ensambla la matriz de rigidez global."""
    K = np.zeros((mesh.n_dof, mesh.n_dof))
    for tri in mesh.triangles:
        ke = cst_stiffness(mesh.nodes, tri, mat)
        idx = np.empty(6, dtype=int)
        idx[0::2] = 2 * tri
        idx[1::2] = 2 * tri + 1
        K[np.ix_(idx, idx)] += ke
    return K


def apply_fixed(K: np.ndarray, f: np.ndarray, fixed: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Impone desplazamiento nulo en los nodos empotrados (eliminación)."""
    dofs = np.concatenate([2 * fixed, 2 * fixed + 1])
    Kred = np.delete(np.delete(K, dofs, axis=0), dofs, axis=1)
    fred = np.delete(f, dofs)
    return Kred, fred


def solve_displacement(K: np.ndarray, f: np.ndarray, fixed: np.ndarray) -> np.ndarray:
    """Resuelve K u = f con el borde empotrado. Devuelve u global (2n,)."""
    Kred, fred = apply_fixed(K, f, fixed)
    ured = np.linalg.solve(Kred, fred)
    u = np.zeros(K.shape[0])
    dofs = np.concatenate([2 * fixed, 2 * fixed + 1])
    mask = np.ones(K.shape[0], dtype=bool)
    mask[dofs] = False
    u[mask] = ured
    return u


def traction_to_nodal_forces(
    mesh: SolidMesh,
    traction: np.ndarray,
    mat: SolidMaterial,
) -> np.ndarray:
    """Reparte una tracción (Pa) sobre los nodos del borde de interfaz.

    Cada nodo recibe la mitad de la longitud de los segmentos adyacentes
    (regla trapezoidal sobre el borde), multiplicada por el espesor.
    """
    f = np.zeros(mesh.n_dof)
    iface = mesh.interface_nodes
    if traction.shape != (len(iface), 2):
        raise ValueError(
            f"traction debe ser ({len(iface)}, 2), es {traction.shape}"
        )

    coords = mesh.nodes[iface]
    for k in range(len(iface) - 1):
        seg = np.linalg.norm(coords[k + 1] - coords[k])
        contrib = 0.5 * seg * mat.thickness
        for local, node in ((k, iface[k]), (k + 1, iface[k + 1])):
            f[2 * node] += traction[local][0] * contrib
            f[2 * node + 1] += traction[local][1] * contrib
    return f


# --------------------------------------------------------------------------
# Participante preCICE
# --------------------------------------------------------------------------
class SolidParticipant:
    """Sólido elástico 2D acoplado por preCICE."""

    def __init__(
        self,
        config_file: str,
        participant: str = "Solid",
        mesh_name: str = "Solid-Mesh",
        read_data: str = "Stress",
        write_data: str = "Displacement",
        length: float = 0.1,
        height: float = 0.01,
        nx: int = 40,
        ny: int = 4,
        material: Optional[SolidMaterial] = None,
        interface_edge: str = "top",
        offset_y: float = 0.0,
    ) -> None:
        import precice  # import local: el módulo no exige preCICE para los tests FEM

        self.material = material or SolidMaterial()
        self.mesh = build_rect_mesh(length, height, nx, ny, interface_edge)
        if offset_y:
            # Desplaza la placa para que su borde de interfaz coincida con el
            # parche del fluido (p. ej. la pared superior de un canal).
            self.mesh.nodes = self.mesh.nodes + np.array([0.0, offset_y])
        self.K = assemble_stiffness(self.mesh, self.material)

        self.read_data = read_data
        self.write_data = write_data
        self.mesh_name = mesh_name

        self.participant = precice.Participant(participant, config_file, 0, 1)

        dim = self.participant.get_mesh_dimensions(mesh_name)
        if dim != 2:
            raise RuntimeError(f"se esperaba malla 2D, preCICE reporta {dim}")

        vertex_ids = self.participant.set_mesh_vertices(
            mesh_name, self.mesh.nodes
        )
        self.vertex_ids = np.asarray(vertex_ids, dtype=int)

        # pyprecice >= 3.4 ya no expone get_data_id: los datos se referencian
        # por nombre en cada llamada a read_data/write_data.

    # -- helpers ---------------------------------------------------------
    def _interface_vertices(self) -> np.ndarray:
        return self.vertex_ids[self.mesh.interface_nodes]

    def _read_traction(self) -> np.ndarray:
        """Lee la tracción en el borde de interfaz, interpolada por preCICE."""
        values = self.participant.read_data(
            self.mesh_name, self.read_data, self._interface_vertices(), 0.0
        )
        arr = np.asarray(values, dtype=float).reshape(-1, 2)
        if not np.all(np.isfinite(arr)):
            raise RuntimeError("preCICE devolvió tracciones no finitas")
        return arr

    def _write_displacement(self, u: np.ndarray) -> None:
        disp = np.column_stack([u[0::2], u[1::2]])
        self.participant.write_data(
            self.mesh_name, self.write_data, self.vertex_ids, disp
        )

    # -- bucle -----------------------------------------------------------
    def run(self, max_windows: Optional[int] = None) -> dict:
        """Bucle de acoplamiento. Devuelve un resumen de la corrida."""
        p = self.participant

        # pyprecice 3.4 exige consultar requires_initial_data() y escribir SÓLO
        # si lo pide, antes de initialize(). Escribir siempre aborta con
        # "Initial data has to be written to preCICE before calling
        # initialize()" cuando el participante no tiene datos iniciales.
        if p.requires_initial_data():
            self._write_displacement(np.zeros(self.mesh.n_dof))

        p.initialize()

        dt = p.get_max_time_step_size()
        history = []
        window = 0
        t = 0.0
        u = np.zeros(self.mesh.n_dof)
        checkpoint = None

        while p.is_coupling_ongoing():
            if max_windows is not None and window >= max_windows:
                break

            # Protocolo de checkpoint de preCICE (orden documentado):
            #   escribir al inicio de la ventana, leer tras advance().
            # Omitir la lectura aborta con
            # "The iteration checkpoint wasn't read".
            if p.requires_writing_checkpoint():
                checkpoint = u.copy()

            traction = self._read_traction()
            f = traction_to_nodal_forces(self.mesh, traction, self.material)
            u = solve_displacement(self.K, f, self.mesh.fixed_nodes)
            self._write_displacement(u)

            dt = p.get_max_time_step_size()
            p.advance(dt)

            if p.requires_reading_checkpoint():
                u = checkpoint.copy() if checkpoint is not None else np.zeros(
                    self.mesh.n_dof
                )

            t += dt

            tip = int(self.mesh.interface_nodes[-1])
            history.append(
                {
                    "window": window,
                    # pyprecice 3.4 no expone get_current_time(): el tiempo se
                    # acumula aquí con el dt que devuelve get_max_time_step_size.
                    "time": t,
                    "u_tip": [float(u[2 * tip]), float(u[2 * tip + 1])],
                    "max_u": float(np.max(np.abs(u))),
                }
            )
            window += 1

        p.finalize()
        return {"windows": window, "history": history}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Sólido elástico 2D acoplado por preCICE")
    ap.add_argument("config", help="precice-config.xml")
    ap.add_argument("--participant", default="Solid")
    ap.add_argument("--mesh", default="Solid-Mesh")
    ap.add_argument("--read", dest="read_data", default="Stress")
    ap.add_argument("--write", dest="write_data", default="Displacement")
    ap.add_argument("--length", type=float, default=0.1)
    ap.add_argument("--height", type=float, default=0.01)
    ap.add_argument("--nx", type=int, default=40)
    ap.add_argument("--ny", type=int, default=4)
    ap.add_argument("--young", type=float, default=70.0e9)
    ap.add_argument("--poisson", type=float, default=0.33)
    ap.add_argument("--thickness", type=float, default=0.01)
    ap.add_argument("--interface-edge", default="top",
                    choices=["top", "bottom", "right"])
    ap.add_argument("--offset-y", type=float, default=0.0,
                    help="desplaza la placa en y para alinear la interfaz")
    ap.add_argument("--max-windows", type=int, default=None)
    args = ap.parse_args(argv)

    mat = SolidMaterial(
        young=args.young, poisson=args.poisson, thickness=args.thickness
    )
    solver = SolidParticipant(
        config_file=args.config,
        participant=args.participant,
        mesh_name=args.mesh,
        read_data=args.read_data,
        write_data=args.write_data,
        length=args.length,
        height=args.height,
        nx=args.nx,
        ny=args.ny,
        material=mat,
        interface_edge=args.interface_edge,
        offset_y=args.offset_y,
    )
    result = solver.run(max_windows=args.max_windows)
    print(f"ventanas completadas: {result['windows']}")
    for row in result["history"][-3:]:
        print(
            f"  w={row['window']} t={row['time']:.6g} "
            f"u_tip=({row['u_tip'][0]:.3e}, {row['u_tip'][1]:.3e}) "
            f"max|u|={row['max_u']:.3e}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
