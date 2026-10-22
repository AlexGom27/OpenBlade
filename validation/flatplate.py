#!/usr/bin/env python3
"""Caso de placa plana turbulenta — validación con solución teórica.

Por qué este caso
-----------------
Es el único de la campaña con **solución analítica**, no experimental. Eso
permite separar dos cosas que la comparación con datos experimentales confunde:

  * un error de implementación (el código no resuelve lo que dice resolver);
  * la diferencia entre el modelo de turbulencia y la física real.

Aquí la referencia es la ley de Cf(x) de White, *Viscous Fluid Flow* (1974),
para Re_L = 5×10⁶ con L = 2 m.

Geometría
----------
Placa plana desde x=0 hasta x=L, con el borde de ataque en el origen. Dominio
rectangular: [-0.2L, 1.1L] × [-0.3L, 0.5L]. La placa es una línea en y=0.

El caso es estacionario; se resuelve con simpleFoam y k-ω SST.

Uso
---
    python3 validation/flatplate.py --out /tmp/flatplate --run
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
REFS = os.path.join(HERE, "refs")

# --- Parámetros del caso -------------------------------------------------
L_PLATE = 2.0
RE_L = 5.0e6
U_INF = 1.0                        # m/s; Re se impone con nu
DEPTH = 0.02                      # espesor de extrusión
X_MIN, X_MAX = -0.2 * L_PLATE, 1.1 * L_PLATE
Y_MIN, Y_MAX = -0.3 * L_PLATE, 0.5 * L_PLATE


def nu_from_re() -> float:
    return U_INF * L_PLATE / RE_L


def load_reference(xs) -> dict:
    """Cf teórico de White interpolado en las posiciones pedidas."""
    path = os.path.join(REFS, "flatplate_cf.dat")
    pts = []
    with open(path) as f:
        for line in f:
            if line.startswith(("#", "variables", "zone")):
                continue
            p = line.split()
            if len(p) >= 3:
                try:
                    pts.append((float(p[0]), float(p[1])))
                except ValueError:
                    pass
    pts.sort()
    out = {}
    for x in xs:
        if not pts or x < pts[0][0] or x > pts[-1][0]:
            continue
        for (x0, c0), (x1, c1) in zip(pts, pts[1:]):
            if x0 <= x <= x1:
                t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
                out[x] = c0 + t * (c1 - c0)
                break
    return out


def build_mesh(msh_path: str, n_len: int = 240, n_h: int = 120,
               first_layer: float = 2e-6, ratio: float = 1.12,
               h_domain: float = 0.6) -> None:
    """Malla del canal con la placa en y=0, generada con Gmsh.

    Se construye un rectángulo y se le incrusta la placa como una línea
    interior. Gmsh se encarga de la topología; escribir los quads a mano
    producía celdas con volumen negativo.

    El refinamiento es geométrico hacia la placa por ambos lados, con un campo
    de tamaño por distancia a la línea y=0.
    """
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("flatplate")
    occ = gmsh.model.occ

    # Dominio: x de X_MIN a X_MAX, y de -h a +h_domain
    surf = occ.addRectangle(X_MIN, -h_domain, 0, X_MAX - X_MIN, 2 * h_domain)

    # La placa: línea interior de x=0 a x=L en y=0
    p0 = occ.addPoint(0.0, 0.0, 0.0)
    p1 = occ.addPoint(L_PLATE, 0.0, 0.0)
    plate = occ.addLine(p0, p1)

    occ.synchronize()

    # La línea debe quedar embebida en la superficie
    occ.fragment([(2, surf)], [(1, plate)])
    occ.synchronize()

    # Identificar la línea de la placa tras el fragment
    plate_curves = []
    for dim, tag in gmsh.model.getEntities(1):
        x0, y0, _, x1, y1, _ = gmsh.model.getBoundingBox(1, tag)
        if abs(y0) < 1e-9 and abs(y1) < 1e-9 and x0 >= -1e-9:
            plate_curves.append(tag)

    # Grupos físicos
    inlet, outlet, walls = [], [], []
    for dim, tag in gmsh.model.getEntities(1):
        if tag in plate_curves:
            continue
        x0, y0, _, x1, y1, _ = gmsh.model.getBoundingBox(1, tag)
        if abs(x0 - X_MIN) < 1e-9 and abs(x1 - X_MIN) < 1e-9:
            inlet.append(tag)
        elif abs(x0 - X_MAX) < 1e-9 and abs(x1 - X_MAX) < 1e-9:
            outlet.append(tag)
        else:
            walls.append(tag)

    surfaces = [t for _, t in gmsh.model.getEntities(2)]
    if inlet:
        gmsh.model.addPhysicalGroup(1, inlet, name="inlet")
    if outlet:
        gmsh.model.addPhysicalGroup(1, outlet, name="outlet")
    if walls:
        gmsh.model.addPhysicalGroup(1, walls, name="walls")
    if plate_curves:
        gmsh.model.addPhysicalGroup(1, plate_curves, name="plate")
    gmsh.model.addPhysicalGroup(2, surfaces, name="fluid")

    # Refinamiento por distancia a la placa
    dist = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(dist, "CurvesList", plate_curves)
    gmsh.model.mesh.field.setNumber(dist, "Sampling", 300)

    thr = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(thr, "InField", dist)
    gmsh.model.mesh.field.setNumber(thr, "SizeMin", first_layer * 20)
    gmsh.model.mesh.field.setNumber(thr, "SizeMax", 0.05)
    gmsh.model.mesh.field.setNumber(thr, "DistMin", 0.0)
    gmsh.model.mesh.field.setNumber(thr, "DistMax", 0.15)
    gmsh.model.mesh.field.setAsBackgroundMesh(thr)

    # Capa límite sobre la placa
    bl = gmsh.model.mesh.field.add("BoundaryLayer")
    gmsh.model.mesh.field.setNumbers(bl, "CurvesList", plate_curves)
    gmsh.model.mesh.field.setNumber(bl, "Size", first_layer)
    gmsh.model.mesh.field.setNumber(bl, "Ratio", ratio)
    gmsh.model.mesh.field.setNumber(bl, "NbLayers", 30)
    gmsh.model.mesh.field.setAsBoundaryLayer(bl)

    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)

    gmsh.model.mesh.generate(2)

    # Extruir a 3D
    res = gmsh.model.occ.extrude([(2, surfaces[0])], 0, 0, DEPTH, [1], [1.0], True)
    gmsh.model.occ.synchronize()
    vols = [t for d, t in res if d == 3]
    gmsh.model.addPhysicalGroup(3, vols, name="fluid3d")

    # Las fronteras laterales se añaden tras extruir
    laterals = [t for d, t in res if d == 2][1:]
    curves_before = plate_curves + inlet + outlet + walls
    if len(laterals) == len(curves_before):
        for c, lat in zip(curves_before, laterals):
            if c in plate_curves:
                gmsh.model.addPhysicalGroup(2, [lat], name="plate_wall")
            elif 0:  # pragma: no cover
                pass

    gmsh.model.mesh.generate(3)
    gmsh.write(msh_path)
    gmsh.finalize()


def write_msh(path, nodes, elems, n_plate, depth):
    """Escribe un .msh 2.2 con la placa como borde inferior de la malla."""
    # Extruir en z
    n2 = len(nodes)
    nodes3 = np.column_stack([np.vstack([nodes, nodes]),
                              np.concatenate([np.zeros(n2), np.full(n2, depth)])])
    nz = n2

    lines = []
    lines.append("$MeshFormat")
    lines.append("2.2 0 8")
    lines.append("$EndMeshFormat")

    lines.append("$PhysicalNames")
    lines.append("4")
    lines.append('1 1 "inlet"')
    lines.append('1 2 "outlet"')
    lines.append('1 3 "top"')
    lines.append('1 4 "plate"')
    lines.append("$EndPhysicalNames")

    lines.append("$Nodes")
    lines.append(str(2 * n2))
    for i, (x, y, z) in enumerate(nodes3, 1):
        lines.append(f"{i} {x:.10e} {y:.10e} {z:.10e}")
    lines.append("$EndNodes")

    # Elementos: quads en z=0 y z=depth, y hexaedros
    lines.append("$Elements")
    body = []
    eid = 1
    n_elem = len(elems)

    # Grupos de borde: identificar por geometría
    # - inlet: x == x_min de la placa
    # - outlet: x == x_max
    # - plate: y == 0
    # - top: resto
    boundary_edges = {}

    for quad in elems:
        for a, b in ((quad[0], quad[1]), (quad[1], quad[2]),
                     (quad[2], quad[3]), (quad[3], quad[0])):
            key = (min(a, b), max(a, b))
            boundary_edges[key] = boundary_edges.get(key, 0) + 1

    def classify(a, b):
        xa, ya = nodes[a][0], nodes[a][1]
        xb, yb = nodes[b][0], nodes[b][1]
        if abs(ya) < 1e-12 and abs(yb) < 1e-12:
            return 4  # plate
        if abs(xa - nodes[:, 0].min()) < 1e-9 and abs(xb - nodes[:, 0].min()) < 1e-9:
            return 1
        if abs(xa - nodes[:, 0].max()) < 1e-9 and abs(xb - nodes[:, 0].max()) < 1e-9:
            return 2
        return 3

    # Elementos 1D de borde (sólo las aristas que pertenecen a una cara)
    for (a, b), cnt in boundary_edges.items():
        if cnt != 1:
            continue
        g = classify(a, b)
        for zoff in (0, nz):
            body.append(f"{eid} 1 2 {g} 0 {a+zoff} {b+zoff}")
            eid += 1

    # Quads de las dos tapas
    for quad in elems:
        body.append(f"{eid} 3 2 0 0 " + " ".join(str(v) for v in quad))
        eid += 1
        body.append(f"{eid} 3 2 0 0 " + " ".join(str(v + nz) for v in quad))
        eid += 1

    # Hexaedros
    for quad in elems:
        body.append(f"{eid} 5 2 0 0 " + " ".join(str(v) for v in quad) +
                    " " + " ".join(str(v + nz) for v in quad))
        eid += 1

    lines.append(str(len(body)))
    lines.extend(body)
    lines.append("$EndElements")

    with open(path, "w") as f:
        f.write("\n".join(lines))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/flatplate")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    msh = os.path.join(args.out, "flatplate.msh")
    build_mesh(msh)

    ref = load_reference([0.25, 0.5, 1.0, 1.5, 1.9])
    meta = {
        "case": "flatplate",
        "L": L_PLATE,
        "Re_L": RE_L,
        "U": U_INF,
        "nu": nu_from_re(),
        "depth": DEPTH,
        "reference": "White, Viscous Fluid Flow (1974), Cf(x), Re_L=5e6",
        "cf_ref": {str(k): v for k, v in ref.items()},
    }
    with open(os.path.join(args.out, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
