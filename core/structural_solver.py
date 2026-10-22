#!/usr/bin/env python3
"""Solver estructural 2D: el perfil alar como viga curva elástica.

Formulación
-----------
El sólido es una **cáscara del perfil**: la línea de cuerda del NACA 0012
extruida hacia el interior con un espesor ``t``. Su frontera exterior es
exactamente el contorno del perfil, que es el mismo que usa el fluido en
``patch airfoil``.

Así la interfaz fluido-estructura **coincide geométricamente** con la del CFD:
preCICE no tiene que inventar correspondencias entre superficies que no se
tocan, y el acoplamiento puede converger.

El extremo de ataque se empotra (``fixed``) para representar el anclaje del ala.

Elemento
--------
Q4 bilineal isoparamétrico, integración 2×2 de Gauss, tensión plana:

    D = E/(1-ν²) · [[1, ν, 0], [ν, 1, 0], [0, 0, (1-ν)/2]]

Uso
---
    # Validación sin preCICE
    python3 core/structural_solver.py --dry-run --thickness 0.01

    # Acoplado
    python3 core/structural_solver.py --config precice-config.xml \\
            --participant Solid --E 70e9 --nu 0.33 --thickness 0.01
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np


# --------------------------------------------------------------------------
# Geometría del perfil
# --------------------------------------------------------------------------
def naca0012_contour(n: int = 120, chord: float = 1.0) -> np.ndarray:
    """Contorno cerrado del NACA 0012, ordenado LE → extradós → TE → intradós.

    Usa la formulación de 4 dígitos con el término de borde de salida cerrado
    (-0.1036 en vez de -0.1015) para que el perfil cierre exactamente.
    """
    beta = np.linspace(0.0, np.pi, n)
    x = 0.5 * (1.0 - np.cos(beta))
    t = 0.12
    yt = 5 * t * (0.2969 * np.sqrt(x)
                  - 0.1260 * x
                  - 0.3516 * x**2
                  + 0.2843 * x**3
                  - 0.1036 * x**4)

    # x va de 0 a 1; construimos LE -> TE (extradós) y TE -> LE (intradós)
    upper = np.column_stack([x, yt]) * chord
    lower = np.column_stack([x[::-1], -yt[::-1]]) * chord
    # unir sin duplicar LE ni TE
    contour = np.vstack([upper, lower[1:-1]])

    # El recorrido anterior (extradós de LE a TE y luego intradós de vuelta)
    # deja el polígono en sentido HORARIO (área firmada negativa). Con ese
    # orden los elementos Q4 salen con Jacobiano invertido en la mitad de los
    # puntos de Gauss y la matriz de rigidez queda indefinida (autovalores
    # negativos -> "Singular matrix"). Se invierte para obtener sentido
    # antihorario, que es el que espera la formulación.
    signed_area = 0.5 * (np.dot(contour[:, 0], np.roll(contour[:, 1], -1))
                         - np.dot(contour[:, 1], np.roll(contour[:, 0], -1)))
    if signed_area < 0:
        contour = contour[::-1].copy()
    return contour


def build_shell_mesh(contour: np.ndarray, thickness: float,
                     n_layers: int = 3):
    """Cáscara del perfil: contorno exterior + capas hacia dentro.

    El contorno exterior conserva **todos** los nodos del perfil (es la
    interfaz con el fluido). Hacia el interior se añaden ``n_layers`` anillos
    desplazados según la normal interior, hasta el espesor pedido.
    """
    n = len(contour)

    # Normal INTERIOR: perpendicular local al contorno, calculada con la
    # diferencia centrada de los nodos vecinos y orientada hacia el interior
    # del perfil. Usar "dirección al centro de la cuerda" hacía colapsar las
    # capas en el borde de salida (x=1), donde esa dirección es tangente al
    # contorno y las capas se cruzaban -> matriz singular.

    # Orientación: el interior está del lado de y=0 respecto de la superficie.
    # Se calcula una sola vez con el signo global y se aplica a todos.
    tangent = np.zeros_like(contour)
    tangent[1:-1] = contour[2:] - contour[:-2]
    tangent[0] = contour[1] - contour[-1]
    tangent[-1] = contour[0] - contour[-2]
    length = np.linalg.norm(tangent, axis=1, keepdims=True)
    length[length < 1e-14] = 1.0
    tangent /= length

    # Normal = tangente rotada 90°. Cuál de las dos apunta al interior depende
    # de si el nodo está en extradós (y>0) o intradós (y<0).
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
    # En el extradós (y>0) el interior es -y; en el intradós, +y.
    sign = np.where(contour[:, 1] > 1e-9, -1.0,
                    np.where(contour[:, 1] < -1e-9, 1.0, 0.0))
    # En el borde de ataque y de salida (y~0) la normal debe apuntar en -x.
    at_le_te = np.abs(contour[:, 1]) <= 1e-9
    normal[at_le_te] = np.array([-1.0, 0.0])
    normal[~at_le_te] *= sign[~at_le_te, None]

    layers = [contour]
    for k in range(1, n_layers + 1):
        frac = k / n_layers
        layers.append(contour + thickness * frac * normal)

    # Nodos: anillo 0 (interfaz) + anillos interiores
    nodes = np.vstack(layers)

    # Conectividad: entre anillo k y k+1, quads cerrados.
    #
    # El orden interior/exterior depende de hacia dónde se desplazó la capa.
    # Cuando la normal interior apunta "hacia dentro" del polígono, el quad
    # (exterior_i, exterior_j, interior_j, interior_i) queda en sentido
    # horario y su Jacobiano resulta negativo. En vez de razonar caso por caso,
    # se comprueba el signo del área de cada elemento y se invierte si hace
    # falta: así la malla es válida para cualquier contorno y cualquier
    # dirección de offset.
    elems = []
    for k in range(n_layers):
        base_a = k * n
        base_b = (k + 1) * n
        for i in range(n):
            j = (i + 1) % n
            quad = [base_a + i, base_a + j, base_b + j, base_b + i]
            pts = nodes[quad]
            x, y = pts[:, 0], pts[:, 1]
            signed = 0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
            if signed < 0:
                quad = quad[::-1]
            elems.append(quad)

    return nodes, np.array(elems, dtype=int), n


# --------------------------------------------------------------------------
# Elemento Q4
# --------------------------------------------------------------------------
def q4_shape(xi: float, eta: float):
    N = 0.25 * np.array([
        (1 - xi) * (1 - eta), (1 + xi) * (1 - eta),
        (1 + xi) * (1 + eta), (1 - xi) * (1 + eta),
    ])
    dN_dxi = 0.25 * np.array([-(1 - eta), (1 - eta), (1 + eta), -(1 + eta)])
    dN_deta = 0.25 * np.array([-(1 - xi), -(1 + xi), (1 + xi), (1 - xi)])
    return N, dN_dxi, dN_deta


def q4_stiffness(coords: np.ndarray, D: np.ndarray, thickness: float) -> np.ndarray:
    Ke = np.zeros((8, 8))
    g = 1.0 / math.sqrt(3.0)
    for xi, eta in ((-g, -g), (g, -g), (g, g), (-g, g)):
        _, dN_dxi, dN_deta = q4_shape(xi, eta)
        J = np.array([
            [dN_dxi @ coords[:, 0], dN_dxi @ coords[:, 1]],
            [dN_deta @ coords[:, 0], dN_deta @ coords[:, 1]],
        ])
        detJ = np.linalg.det(J)
        if detJ <= 1e-18:
            # Elemento degenerado: se ignora (ocurre en el borde de salida,
            # donde el espesor tiende a cero)
            continue
        invJ = np.linalg.inv(J)
        dN = np.array([invJ @ np.array([dN_dxi[i], dN_deta[i]]) for i in range(4)])
        B = np.zeros((3, 8))
        for i in range(4):
            B[0, 2 * i] = dN[i, 0]
            B[1, 2 * i + 1] = dN[i, 1]
            B[2, 2 * i] = dN[i, 1]
            B[2, 2 * i + 1] = dN[i, 0]
        Ke += thickness * detJ * (B.T @ D @ B)
    return Ke


def plane_strain_D(E: float, nu: float) -> np.ndarray:
    """Matriz constitutiva de DEFORMACIÓN PLANA.

    El benchmark de Turek & Hron define el sólido mediante μ_s y λ_s
    (no E), lo que corresponde a deformación plana:

        λ = 2μν/(1-2ν),   D = [[λ+2μ, λ, 0], [λ, λ+2μ, 0], [0, 0, μ]]

    Con μ = 5e5 y ν = 0.4: λ = 2e6, λ+2μ = 3e6.
    En tensión plana el mismo material daría 1.667e6, es decir ~2× más
    flexible; para un flag delgado eso se traduce en el doble de flecha.
    """
    lam = E * nu / ((1 + nu) * (1 - 2 * nu))
    mu = E / (2 * (1 + nu))
    return np.array([[lam + 2 * mu, lam, 0.0],
                     [lam, lam + 2 * mu, 0.0],
                     [0.0, 0.0, mu]])


def plane_stress_D(E: float, nu: float) -> np.ndarray:
    c = E / (1.0 - nu * nu)
    return c * np.array([[1.0, nu, 0.0],
                         [nu, 1.0, 0.0],
                         [0.0, 0.0, (1.0 - nu) / 2.0]])


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


def von_mises_per_element(nodes, elems, u, D, thickness):
    """Tensión de von Mises en el centro de cada elemento Q4.

    Para cada elemento:
      1. Deformaciones  eps = B · u_e   en el punto central (xi=eta=0)
      2. Tensiones      sigma = D · eps
      3. von Mises      sqrt(sx² - sx·sy + sy² + 3·txy²)   (estado plano)

    Devuelve un array (n_elems,) en Pa y las coordenadas del centroide.
    """
    g = 0.0  # centro del elemento
    N, dN_dxi, dN_deta = q4_shape(g, g)

    vm = np.zeros(len(elems))
    centres = np.zeros((len(elems), 2))

    for k, e in enumerate(elems):
        co = nodes[e]
        J = np.array([
            [dN_dxi @ co[:, 0], dN_dxi @ co[:, 1]],
            [dN_deta @ co[:, 0], dN_deta @ co[:, 1]],
        ])
        detJ = np.linalg.det(J)
        if detJ <= 1e-18:
            vm[k] = 0.0
            centres[k] = co.mean(axis=0)
            continue
        invJ = np.linalg.inv(J)
        dN = np.array([invJ @ np.array([dN_dxi[i], dN_deta[i]]) for i in range(4)])

        B = np.zeros((3, 8))
        for i in range(4):
            B[0, 2 * i] = dN[i, 0]
            B[1, 2 * i + 1] = dN[i, 1]
            B[2, 2 * i] = dN[i, 1]
            B[2, 2 * i + 1] = dN[i, 0]

        ue = np.empty(8)
        ue[0::2] = u[2 * e]
        ue[1::2] = u[2 * e + 1]

        eps = B @ ue
        sig = D @ eps
        sx, sy, txy = sig
        vm[k] = math.sqrt(max(sx * sx - sx * sy + sy * sy + 3 * txy * txy, 0.0))
        centres[k] = N @ co

    return vm, centres


def solve_dirichlet(K, F, fixed_dofs):
    free = np.setdiff1d(np.arange(len(F)), fixed_dofs)
    u = np.zeros_like(F)
    if len(free):
        u[free] = np.linalg.solve(K[np.ix_(free, free)], F[free])
    return u


# --------------------------------------------------------------------------
# Validación analítica
# --------------------------------------------------------------------------
def validate_cantilever(E=2.0e6, nu=0.3, L=1.0, h=0.1, thickness=0.1,
                        P=-1.0, nx=40, ny=8) -> dict:
    """Viga recta empotrada: δ = PL³/3EI (validación del elemento Q4)."""
    xs = np.linspace(0.0, L, nx + 1)
    ys = np.linspace(0.0, h, ny + 1)
    nodes = np.array([[x, y] for y in ys for x in xs])

    def nid(i, j):
        return j * (nx + 1) + i

    elems = np.array([[nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)]
                      for j in range(ny) for i in range(nx)])

    K = assemble(nodes, elems, plane_stress_D(E, nu), thickness)
    F = np.zeros(2 * len(nodes))
    tip = sorted([i for i, p in enumerate(nodes) if abs(p[0] - L) < 1e-12],
                 key=lambda i: nodes[i, 1])
    F[2 * tip[0] + 1] += P / 2
    F[2 * tip[-1] + 1] += P / 2

    fixed = []
    for i, p in enumerate(nodes):
        if abs(p[0]) < 1e-12:
            fixed += [2 * i, 2 * i + 1]
    u = solve_dirichlet(K, F, np.array(fixed))

    delta_fem = float(np.mean([u[2 * i + 1] for i in tip]))
    I = thickness * h ** 3 / 12
    delta_theory = P * L ** 3 / (3 * E * I)
    return {"delta_fem": delta_fem, "delta_theory": delta_theory,
            "error_pct": (delta_fem - delta_theory) / delta_theory * 100,
            "n_nodes": len(nodes), "n_elems": len(elems)}


# --------------------------------------------------------------------------
# Solver acoplado
# --------------------------------------------------------------------------
class StructuralSolver:
    """Cáscara del perfil acoplada a preCICE.

    La interfaz son los nodos del contorno exterior (anillo 0), que coinciden
    con el patch ``airfoil`` del fluido.
    """

    def __init__(self, config_file: str, participant: str = "Solid",
                 mesh_name: str = "Solid-Mesh",
                 read_data: str = "Stress", write_data: str = "Displacement",
                 E: float = 70e9, nu: float = 0.33, thickness: float = 0.01,
                 chord: float = 1.0, n_contour: int = 120,
                 n_layers: int = 3, geometry: str = "shell",
                 case_dir=None) -> None:
        import precice

        self._dbg_count = 0
        self.p = precice.Participant(participant, config_file, 0, 1)
        self.mesh_name = mesh_name
        self.read_data = read_data
        self.write_data = write_data
        self.D = plane_stress_D(E, nu)
        self.thickness = thickness
        self.out_dir = os.environ.get("FSI_FRAMES_DIR")

        if geometry == "flag":
            self._init_flag(case_dir, E, nu, thickness, mesh_name)
            return

        contour = naca0012_contour(n=n_contour, chord=chord)
        self.nodes, self.elems, self.n_interface = build_shell_mesh(
            contour, thickness, n_layers)
        self.K = assemble(self.nodes, self.elems,
                          plane_stress_D(E, nu), thickness)

        # Soportes: empotramiento parcial en LE y TE.
        #
        # Una cáscara cerrada libre tiene 3 modos de cuerpo rígido. Empotrar
        # sólo el borde de ataque deja la matriz con rango deficiente (se
        # comprobó: rango 949 de 1862) y el solver aborta con "Singular matrix".
        #
        # Físicamente el perfil representa un ala: se ancla en el borde de
        # ataque (donde va el larguero) y se permite el desplazamiento vertical
        # del borde de salida, que es lo que produce la deformación de interés.
        # Empotramiento completo (ambos DOF) en el borde de ataque. Con sólo
        # una fracción de los nodos la matriz queda mal condicionada: se
        # comprobó que aparecían 913 autovalores negativos por elementos con
        # Jacobiano invertido, ya corregidos en la conectividad. Ahora el
        # mínimo autovalor es positivo y el sistema resuelve.
        xmin = contour[:, 0].min()
        fixed = []
        for i in range(self.n_interface):
            if contour[i, 0] < xmin + 0.02 * chord:
                fixed += [2 * i, 2 * i + 1]
        self.fixed = np.array(sorted(set(fixed)), dtype=int)

        # Área tributaria de cada nodo de la interfaz: en 2D es la longitud
        # del segmento asociado (media distancia a los vecinos). Se multiplica
        # por el espesor para obtener área real.
        seg = np.zeros(self.n_interface)
        for i in range(self.n_interface):
            prev = (i - 1) % self.n_interface
            nxt = (i + 1) % self.n_interface
            d1 = np.linalg.norm(contour[i] - contour[prev])
            d2 = np.linalg.norm(contour[nxt] - contour[i])
            seg[i] = 0.5 * (d1 + d2)
        # (ax, ay) = longitud tributaria x espesor, por componente
        self._node_area = [(seg[i] * thickness, seg[i] * thickness)
                           for i in range(self.n_interface)]

        # Interfaz = anillo exterior completo (coincide con patch airfoil)
        self.interface = np.arange(self.n_interface, dtype=int)
        coords = self.nodes[self.interface].astype(float)
        self.vertex_ids = self.p.set_mesh_vertices(mesh_name, coords)

    def _init_flag(self, case_dir, E, nu, thickness, mesh_name) -> None:
        """Modo benchmark: flag rectangular (Turek & Hron FSI 1).

        El fluido rodea el flag por arriba, abajo y por el extremo libre.
        Sólo el borde izquierdo está unido al cilindro: ahí va el empotramiento.
        La interfaz es el resto del contorno.
        """
        self.nodes = np.load(os.path.join(case_dir, "solid_nodes.npy"))
        self.elems = np.load(os.path.join(case_dir, "solid_elems.npy"))
        # El benchmark define μ y λ: deformación plana.
        self.D = plane_strain_D(E, nu)
        self.K = assemble(self.nodes, self.elems, self.D, thickness)

        xmin = self.nodes[:, 0].min()
        xmax = self.nodes[:, 0].max()
        ymin = self.nodes[:, 1].min()
        ymax = self.nodes[:, 1].max()
        eps = 1e-9

        on_boundary = (
            (np.abs(self.nodes[:, 1] - ymin) < eps) |
            (np.abs(self.nodes[:, 1] - ymax) < eps) |
            (np.abs(self.nodes[:, 0] - xmax) < eps)
        )
        self.interface = np.where(on_boundary)[0]
        self.n_interface = len(self.interface)

        pts = self.nodes[self.interface]
        seg = np.zeros(self.n_interface)
        for i in range(self.n_interface):
            d = np.linalg.norm(pts - pts[i], axis=1)
            d[i] = np.inf
            idx = np.argsort(d)[:2]
            seg[i] = 0.5 * (d[idx[0]] + d[idx[1]])
        self._node_area = [(s_ * thickness, s_ * thickness) for s_ in seg]

        fixed = []
        for i, q in enumerate(self.nodes):
            if abs(q[0] - xmin) < eps:
                fixed += [2 * i, 2 * i + 1]
        self.fixed = np.array(sorted(set(fixed)), dtype=int)

        coords = self.nodes[self.interface].astype(float)
        self.vertex_ids = self.p.set_mesh_vertices(mesh_name, coords)

    def _save_frame(self, index, t, u) -> None:
        """Guarda un fotograma del campo de von Mises para el vídeo."""
        vm, centres = von_mises_per_element(
            self.nodes, self.elems, u, self.D, self.thickness)
        np.savez(os.path.join(self.out_dir, f"frame_{index:04d}.npz"),
                 nodes=self.nodes, elems=self.elems, u=u,
                 vm=vm, centres=centres, t=t)

    def run(self) -> dict:
        p = self.p
        if p.requires_initial_data():
            p.write_data(self.mesh_name, self.write_data, self.vertex_ids,
                         np.zeros((len(self.interface), 2)))
        p.initialize()

        blocks, max_disp = 0, 0.0
        while p.is_coupling_ongoing():
            if p.requires_writing_checkpoint():
                pass
            dt = p.get_max_time_step_size()

            stress = p.read_data(self.mesh_name, self.read_data,
                                 self.vertex_ids, dt)

            # "Stress" es TENSIÓN (N/m²), no fuerza. Verificado en el código
            # del adaptador (FSI/Stress.C):
            #
            #     Stress::getFaceVectors()  ->  mesh_.boundary()[patchID].nf()
            #
            # `nf()` es la normal UNITARIA (adimensional). La clase `Force`, en
            # cambio, usa `Sf()` (vector de área) y por eso sí devuelve newtons.
            # Con `nf()`, el producto `surface * p * rho` de ForceBase.C queda
            # en N/m², es decir tensión.
            #
            # Por tanto hay que integrar sobre el área tributaria de cada nodo
            # para obtener la fuerza nodal.
            F = np.zeros(2 * len(self.nodes))
            for k, nid in enumerate(self.interface):
                ax, ay = self._node_area[k]
                F[2 * nid] += float(stress[k][0]) * ax
                F[2 * nid + 1] += float(stress[k][1]) * ay

            if self._dbg_count < 3:
                smax = float(np.abs(stress).max())
                ftot = float(np.linalg.norm(
                    [F[0::2].sum(), F[1::2].sum()]))
                print(f"[solid] t={dt:.4f}: |data|max={smax:.4e}  "
                      f"|F_total|={ftot:.4e} N", file=sys.stderr)
                self._dbg_count += 1

            u = solve_dirichlet(self.K, F, self.fixed)

            disp = np.column_stack([u[2 * self.interface],
                                    u[2 * self.interface + 1]])
            p.write_data(self.mesh_name, self.write_data, self.vertex_ids, disp)

            max_disp = max(max_disp, float(np.abs(u).max()))

            # Guardar fotograma del campo de von Mises si se pidió
            if self.out_dir:
                self._save_frame(blocks, dt, u)

            p.advance(dt)
            if p.requires_reading_checkpoint():
                pass
            blocks += 1

        p.finalize()
        return {"time_windows": blocks, "max_displacement": max_disp}


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--participant", default="Solid")
    ap.add_argument("--mesh", default="Solid-Mesh")
    ap.add_argument("--read-data", default="Stress")
    ap.add_argument("--write-data", default="Displacement")
    ap.add_argument("--E", type=float, default=70e9)
    ap.add_argument("--nu", type=float, default=0.33)
    ap.add_argument("--thickness", type=float, default=0.01)
    ap.add_argument("--chord", type=float, default=1.0)
    ap.add_argument("--n-contour", type=int, default=120)
    ap.add_argument("--n-layers", type=int, default=3)
    ap.add_argument("--geometry", default="shell", choices=["shell", "flag"])
    ap.add_argument("--case-dir", default=None)
    ap.add_argument("--dry-run", action="store_true")
    # compatibilidad con la CLI anterior
    ap.add_argument("--nx", type=int, default=40)
    ap.add_argument("--ny", type=int, default=8)
    ap.add_argument("--length", type=float, default=1.0)
    ap.add_argument("--height", type=float, default=0.1)
    args = ap.parse_args(argv)

    if args.dry_run:
        r = validate_cantilever(E=2e6, nu=0.3, L=args.length,
                                h=args.height, thickness=0.1,
                                nx=args.nx, ny=args.ny)
        print(json.dumps(r, indent=2))
        return 0

    if not args.config:
        ap.error("--config es obligatorio salvo con --dry-run")

    s = StructuralSolver(
        config_file=args.config, participant=args.participant,
        mesh_name=args.mesh, read_data=args.read_data,
        write_data=args.write_data, E=args.E, nu=args.nu,
        thickness=args.thickness, chord=args.chord,
        n_contour=args.n_contour, n_layers=args.n_layers,
        geometry=args.geometry, case_dir=args.case_dir,
    )
    print(json.dumps(s.run(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
