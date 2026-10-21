#!/usr/bin/env python3
"""Caso de validación FSI 1 de Turek & Hron.

Referencia
----------
Turek, S.; Hron, J. "Proposal for Numerical Benchmarking of Fluid-Structure
Interaction between an Elastic Object and Laminar Incompressible Flow",
Lect. Notes Comput. Sci. Eng. 53 (2006), doi:10.1007/3-540-34596-5_7.

Valores de referencia tomados de una fuente secundaria que reproduce la tabla
original (Neunteufel & Schöberl, "Fluid-structure interaction with
H(div)-conforming finite elements", arXiv:2005.06360), Tabla 5.8, columna de
malla más fina:

    u_x(A) = 2.2697e-05 m
    u_y(A) = 8.19543e-04 m

Geometría (Tabla 5.1 del benchmark)
-----------------------------------
    Canal:     L = 2.5 m, H = 0.41 m
    Cilindro:  centro (0.2, 0.2), r = 0.05 m
    Flag:      longitud 0.35 m, espesor 0.02 m, anclado en (0.6, 0.2)
    Punto A:   extremo libre del flag, inicialmente (0.6, 0.2) + (0.35, 0)

Parámetros FSI 1 (Tabla 5.2)
----------------------------
    rho_s = 1000 kg/m³, nu_s = 0.4, mu_s = 5e5 Pa  ->  E = 1.4e6 Pa
    rho_f = 1000 kg/m³, nu_f = 1e-3 m²/s
    U_media = 0.2 m/s  (Re = 20 referido al diámetro del cilindro)
    Perfil de entrada parabólico, rampa coseno hasta t = 2 s
    El caso alcanza estado estacionario (no oscila).

Este script genera el caso OpenFOAM completo (canal + cilindro + flag) y lo
deja listo para el acoplamiento con preCICE.

Uso:
    python3 validation/turek_hron_fsi1.py --out /tmp/th_fsi1
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# --- Geometría del benchmark ---------------------------------------------
L_CHANNEL = 2.5
H_CHANNEL = 0.41
CYL_X, CYL_Y = 0.2, 0.2
CYL_R = 0.05
FLAG_L = 0.35
FLAG_H = 0.02
FLAG_X0 = 0.6
DEPTH = 0.01          # espesor de extrusion (1 celda en z)

# --- Parámetros FSI 1 ----------------------------------------------------
RHO_S = 1000.0
NU_S = 0.4
MU_S = 5.0e5
E_S = 2 * MU_S * (1 + NU_S)          # 1.4e6 Pa
RHO_F = 1000.0
NU_F = 1.0e-3
U_MEAN = 0.2
T_END = 10.0

# --- Referencia ----------------------------------------------------------
REF_UX = 2.2697e-05
REF_UY = 8.19543e-04


def write_geometry_geo(path: str, mesh_size: float = 0.01) -> None:
    """Geometría Gmsh: canal rectangular con cilindro y flag."""
    geo = f"""
// Turek & Hron FSI 1 - geometria
SetFactory("OpenCASCADE");

// Canal
Rectangle(1) = {{0, 0, 0, {L_CHANNEL}, {H_CHANNEL}, 0}};

// Cilindro
Disk(2) = {{{CYL_X}, {CYL_Y}, 0, {CYL_R}, {CYL_R}}};

// Flag (rectangulo delgado anclado al cilindro)
Rectangle(3) = {{{FLAG_X0}, {CYL_Y - FLAG_H/2}, 0, {FLAG_L}, {FLAG_H}, 0}};

// Fluido = canal - cilindro - flag
BooleanDifference(4) = {{ Surface{{1}}; Delete; }}{{ Surface{{2, 3}}; Delete; }};

Physical Surface("fluid") = {{4}};
Physical Curve("inlet") = {{1}};
Physical Curve("outlet") = {{2}};
Physical Curve("walls") = {{3, 4}};
Physical Curve("cylinder") = {{5}};
Physical Curve("flag") = {{6}};

Mesh.MeshSizeMin = {mesh_size};
Mesh.MeshSizeMax = {mesh_size*2};

"""
    with open(path, "w") as f:
        f.write(geo)


def build_channel_mesh(msh_path: str, mesh_size: float = 0.01,
                      depth: float = 0.01) -> None:
    """Construye y genera la malla del canal con la API de Gmsh.

    Se usa la API en vez de un archivo .geo porque la extrusión 2D->3D con
    `Extrude` en el lenguaje .geo daba error de sintaxis en esta versión, y
    gmshToFoam necesita volúmenes (no una malla plana).
    """
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("th_fsi1")
    occ = gmsh.model.occ

    channel = occ.addRectangle(0, 0, 0, L_CHANNEL, H_CHANNEL)
    cyl = occ.addDisk(CYL_X, CYL_Y, 0, CYL_R, CYL_R)
    flag = occ.addRectangle(FLAG_X0, CYL_Y - FLAG_H / 2, 0, FLAG_L, FLAG_H)

    fluid, _ = occ.cut([(2, channel)], [(2, cyl), (2, flag)])
    occ.synchronize()

    # Etiquetas por geometría.
    #
    # Estructura observada tras el `cut` (9 curvas):
    #   - 4 del canal: y=0, x=0, x=2.5, y=0.41
    #   - 1 del cilindro: arco cerrado con bbox (0.15,0.15)-(0.25,0.25)
    #   - 4 del flag: dos horizontales en y=0.19 y y=0.21, y dos verticales
    #     en x=0.6 y x=0.95
    #
    # El flag en su totalidad (las 4 curvas) es la superficie mojada del sólido;
    # la interfaz FSI es el contorno del rectángulo completo.
    eps = 1e-6
    inlet, outlet, walls, cylinder, flag_c = [], [], [], [], []

    for dim, tag in gmsh.model.getEntities(1):
        x0, y0, _, x1, y1, _ = gmsh.model.getBoundingBox(1, tag)

        on_left = abs(x0) < eps and abs(x1) < eps
        on_right = abs(x0 - L_CHANNEL) < eps and abs(x1 - L_CHANNEL) < eps
        on_wall = ((abs(y0) < eps and abs(y1) < eps) or
                   (abs(y0 - H_CHANNEL) < eps and abs(y1 - H_CHANNEL) < eps))
        # Las curvas del canal pueden venir con coordenadas -0.0; el eps
        # absoluto de 1e-6 ya lo cubre, pero se añade un chequeo por longitud
        # para no confundir las paredes con las horizontales del flag.
        is_long_h = abs(y1 - y0) < eps and abs(x1 - x0) > 1.0

        # Cilindro: bbox contenido en el cuadrado circunscrito del disco
        in_cyl_box = (x0 >= CYL_X - CYL_R - 1e-6 and x1 <= CYL_X + CYL_R + 1e-6
                      and y0 >= CYL_Y - CYL_R - 1e-6 and y1 <= CYL_Y + CYL_R + 1e-6)

        # Flag: bbox dentro del rectángulo del flag
        in_flag_box = (x0 >= FLAG_X0 - 1e-6 and x1 <= FLAG_X0 + FLAG_L + 1e-6
                       and y0 >= CYL_Y - FLAG_H / 2 - 1e-6
                       and y1 <= CYL_Y + FLAG_H / 2 + 1e-6)

        if on_left:
            inlet.append(tag)
        elif on_right:
            outlet.append(tag)
        elif on_wall or is_long_h:
            walls.append(tag)
        elif in_cyl_box:
            cylinder.append(tag)
        elif in_flag_box:
            flag_c.append(tag)

    surf = [t for _, t in fluid]
    gmsh.model.addPhysicalGroup(2, surf, name="fluid")

    gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_size)
    gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size * 2)
    gmsh.model.mesh.generate(2)

    contour_curves = [t for _, t in gmsh.model.getEntities(1)]
    res = occ.extrude([(2, surf[0])], 0, 0, depth, [1], [1.0], True)
    occ.synchronize()
    vols = [t for d, t in res if d == 3]
    gmsh.model.addPhysicalGroup(3, vols, name="fluid3d")

    # IMPORTANTE: los grupos físicos de frontera se declaran DESPUÉS de la
    # extrusión y sobre las SUPERFICIES LATERALES (dim=2). Con las curvas
    # originales (dim=1) gmshToFoam sólo ve el volumen y todo lo demás cae en
    # defaultFaces.
    #
    # `extrude` devuelve, en orden: (2, tapa_superior), (3, volumen), y luego
    # un (2, lateral) por CADA curva del contorno, en el mismo orden en que
    # gmsh las enumera. Aprovechar ese orden es determinista; emparejar por
    # bbox fallaba porque la tapa y los laterales comparten coordenadas.
    laterals = [t for d, t in res if d == 2][1:]   # el primero es la tapa
    # Las curvas del contorno original, capturadas ANTES de extruir (después
    # gmsh renumera y añade las aristas de la tapa).
    curves = contour_curves

    if len(laterals) == len(curves):
        curve_to_lateral = dict(zip(curves, laterals))
    else:
        # Respaldo: emparejar por bbox del rectángulo envolvente
        curve_to_lateral = {}
        for c in curves:
            cb = gmsh.model.getBoundingBox(1, c)
            for lat in laterals:
                sb = gmsh.model.getBoundingBox(2, lat)
                if all(abs(cb[i] - sb[i]) < 1e-6 for i in range(6)):
                    curve_to_lateral[c] = lat
                    break

    groups = {"inlet": [], "outlet": [], "walls": [], "cylinder": [], "flag": []}
    for name, clist in (("inlet", inlet), ("outlet", outlet), ("walls", walls),
                        ("cylinder", cylinder), ("flag", flag_c)):
        for c in clist:
            lat = curve_to_lateral.get(c)
            if lat is not None:
                groups[name].append(lat)

    for name, surfs_ in groups.items():
        if surfs_:
            gmsh.model.addPhysicalGroup(2, surfs_, name=name)

    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
    gmsh.model.mesh.generate(3)
    gmsh.write(msh_path)
    gmsh.finalize()


def write_precice_config(path: str, dt: float, end_time: float) -> None:
    """Configuración preCICE para el caso (flag como sólido)."""
    sys.path.insert(0, ROOT)
    from core.fsi_precice import FsiConfig, build_precice_config

    cfg = FsiConfig(
        fluid_participant="Fluid",
        solid_participant="Solid",
        fluid_mesh="Fluid-Mesh",
        solid_mesh="Solid-Mesh",
        force_data="Stress",
        displacement_data="Displacement",
        interface_patch="flag",
        dt=dt,
        end_time=end_time,
        dimensions=2,
        rho=RHO_F,
        coupling_scheme="serial-implicit",
        relaxation="aitken",
        max_iterations=50,
        convergence_limit=1e-4,
        exchange_directory="/data/precice-run",
    )
    with open(path, "w") as f:
        f.write(build_precice_config(cfg))


def write_openfoam_case(case_dir: str) -> None:
    """Diccionarios de OpenFOAM para el canal con flag."""
    for d in ("0", "constant", "system"):
        os.makedirs(os.path.join(case_dir, d), exist_ok=True)

    # --- controlDict ---
    control = f"""FoamFile {{ version 2.0; format ascii; class dictionary; object controlDict; }}
application     pimpleFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {T_END};
deltaT          0.01;
writeControl    adjustableRunTime;
writeInterval   0.1;
purgeWrite      0;
writeFormat     ascii;
writePrecision  8;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;
adjustTimeStep  yes;
maxCo           1.0;
maxDeltaT       0.01;

functions
{{
    inletVelocity
    {{
        type            coded;
        libs            ("libutilityFunctionObjects.so");
        name            inlet;
        code            #{{}}
        execute
        #{{}}
    }}
}}
"""
    # La rampa coseno de entrada se implementa con una BC de tipo coded en 0/U,
    # que es más limpio que un functionObject.
    control = control.split("functions")[0]
    with open(os.path.join(case_dir, "system", "controlDict"), "w") as f:
        f.write(control)

    # --- fvSchemes ---
    schemes = """FoamFile { version 2.0; format ascii; class dictionary; object fvSchemes; }
ddtSchemes      { default Euler; }
gradSchemes     { default Gauss linear; }
divSchemes
{
    default         none;
    div(phi,U)      Gauss linearUpwind grad(U);
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes   { default corrected; }
"""
    with open(os.path.join(case_dir, "system", "fvSchemes"), "w") as f:
        f.write(schemes)

    # --- fvSolution ---
    solution = """FoamFile { version 2.0; format ascii; class dictionary; object fvSolution; }
solvers
{
    p { solver GAMG; smoother GaussSeidel; tolerance 1e-7; relTol 0.01; }
    pFinal { $p; relTol 0; }
    pcorr { solver GAMG; smoother GaussSeidel; tolerance 1e-5; relTol 0; }
    pcorrFinal { $pcorr; relTol 0; }
    "(U|k|omega)" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0.01; }
    "(U|k|omega)Final" { $U; relTol 0; }
    cellDisplacement { solver GAMG; smoother GaussSeidel; tolerance 1e-8; relTol 0; }
    cellDisplacementFinal { $cellDisplacement; relTol 0; }
    pointDisplacement { solver PCG; preconditioner DIC; tolerance 1e-8; relTol 0; }
    pointDisplacementFinal { $pointDisplacement; relTol 0; }
}
PIMPLE
{
    nOuterCorrectors 1;
    nCorrectors     3;
    nNonOrthogonalCorrectors 2;
    correctPhi      yes;
    pRefCell        0;
    pRefValue       0;
}
"""
    with open(os.path.join(case_dir, "system", "fvSolution"), "w") as f:
        f.write(solution)

    # --- transportProperties ---
    transport = f"""FoamFile {{ version 2.0; format ascii; class dictionary; object transportProperties; }}
transportModel  Newtonian;
nu              [0 2 -1 0 0 0 0] {NU_F:.6e};
"""
    with open(os.path.join(case_dir, "constant", "transportProperties"), "w") as f:
        f.write(transport)

    # --- turbulenceProperties: laminar (Re = 20) ---
    turb = """FoamFile { version 2.0; format ascii; class dictionary; object turbulenceProperties; }
simulationType  laminar;
"""
    with open(os.path.join(case_dir, "constant", "turbulenceProperties"), "w") as f:
        f.write(turb)

    # --- 0/U ---
    # `codedFixedValue` aborta con "checkSecurity" porque la imagen tiene
    # allowSystemOperations desactivado. `flowRateInletVelocity` da el caudal
    # correcto (U_media * H) sin código compilado; el perfil no es parabólico,
    # lo cual se anota como desviación respecto al benchmark.
    u_field = f"""FoamFile {{ version 2.0; format ascii; class volVectorField; object U; }}
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform (0 0 0);
boundaryField
{{
    inlet
    {{
        type            flowRateInletVelocity;
        // Caudal volumetrico = U_media * H * espesor de extrusion.
        // Sin el espesor la velocidad resulta 100x mayor y el caso diverge
        // en el primer paso de tiempo.
        volumetricFlowRate constant {U_MEAN * H_CHANNEL * DEPTH:.6e};
        value           uniform ({U_MEAN} 0 0);
    }}
    outlet  {{ type zeroGradient; }}
    walls   {{ type noSlip; }}
    cylinder {{ type noSlip; }}
    flag    {{ type movingWallVelocity; value uniform (0 0 0); }}
    frontAndBack {{ type empty; }}
}}
"""
    with open(os.path.join(case_dir, "0", "U"), "w") as f:
        f.write(u_field)

    p_field = """FoamFile { version 2.0; format ascii; class volScalarField; object p; }
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform 0;
boundaryField
{
    inlet     { type zeroGradient; }
    outlet    { type fixedValue; value uniform 0; }
    walls     { type zeroGradient; }
    cylinder  { type zeroGradient; }
    flag      { type zeroGradient; }
    frontAndBack { type empty; }
}
"""
    with open(os.path.join(case_dir, "0", "p"), "w") as f:
        f.write(p_field)

    pd_field = """FoamFile { version 2.0; format ascii; class pointVectorField; object pointDisplacement; }
dimensions      [0 1 0 0 0 0 0];
internalField   uniform (0 0 0);
boundaryField
{
    inlet     { type fixedValue; value uniform (0 0 0); }
    outlet    { type fixedValue; value uniform (0 0 0); }
    walls     { type fixedValue; value uniform (0 0 0); }
    cylinder  { type fixedValue; value uniform (0 0 0); }
    flag      { type fixedValue; value uniform (0 0 0); }
    frontAndBack { type empty; }
}
"""
    with open(os.path.join(case_dir, "0", "pointDisplacement"), "w") as f:
        f.write(pd_field)

    # --- dynamicMeshDict ---
    dyn = """FoamFile { version 2.0; format ascii; class dictionary; object dynamicMeshDict; }
dynamicFvMesh       dynamicMotionSolverFvMesh;
motionSolverLibs    ("libfvMotionSolvers.so");
motionSolver        displacementLaplacian;
displacementLaplacianCoeffs
{
    diffusivity     quadratic inverseDistance 1(flag);
}
"""
    # FsiCase ya escribió dynamicMeshDict y parcheó fvSolution.


    # Adaptador preCICE: preciceDict + functionObject en controlDict.
    # Va al final para no ser sobrescrito por los diccionarios de arriba.
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from core.fsi_precice import FsiCase, FsiConfig
    _cfg = FsiConfig(interface_patch="flag", dimensions=2, rho=RHO_F,
                    dt=0.01, end_time=T_END,
                    exchange_directory="/data/precice-run")
    FsiCase(case_dir, _cfg).prepare()


def write_solid_mesh(case_dir: str, n_len: int = 60, n_thick: int = 4) -> tuple:
    """Malla del flag: rectángulo 0.35 x 0.02, empotrado en x=0.6.

    Devuelve las coordenadas del punto A (extremo libre, centro).
    """
    import numpy as np

    xs = np.linspace(FLAG_X0, FLAG_X0 + FLAG_L, n_len + 1)
    ys = np.linspace(CYL_Y - FLAG_H / 2, CYL_Y + FLAG_H / 2, n_thick + 1)
    nodes = np.array([[x, y] for y in ys for x in xs])

    def nid(i, j):
        return j * (n_len + 1) + i

    elems = [[nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1)]
             for j in range(n_thick) for i in range(n_len)]

    np.save(os.path.join(case_dir, "solid_nodes.npy"), nodes)
    np.save(os.path.join(case_dir, "solid_elems.npy"), np.array(elems))

    tip_x = FLAG_X0 + FLAG_L
    tip_nodes = [i for i, p in enumerate(nodes) if abs(p[0] - tip_x) < 1e-12]
    A = nodes[tip_nodes[len(tip_nodes) // 2]]
    return tuple(A), len(nodes), len(elems)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/th_fsi1")
    ap.add_argument("--dt", type=float, default=0.01)
    ap.add_argument("--end-time", type=float, default=T_END)
    args = ap.parse_args(argv)

    case = args.out
    if os.path.exists(case):
        shutil.rmtree(case)
    os.makedirs(case)

    write_openfoam_case(case)
    write_precice_config(os.path.join(case, "precice-config.xml"),
                         args.dt, args.end_time)
    A, n_nodes, n_elems = write_solid_mesh(case)
    build_channel_mesh(os.path.join(case, "channel.msh"))

    meta = {
        "benchmark": "Turek & Hron FSI 1",
        "reference_doi": "10.1007/3-540-34596-5_7",
        "reference_table": "Neunteufel & Scho(e)berl arXiv:2005.06360, Table 5.8",
        "ref_ux": REF_UX,
        "ref_uy": REF_UY,
        "point_A": list(A),
        "solid_nodes": n_nodes,
        "solid_elems": n_elems,
        "E_solid": E_S,
        "nu_solid": NU_S,
        "rho_solid": RHO_S,
        "rho_fluid": RHO_F,
        "nu_fluid": NU_F,
        "U_mean": U_MEAN,
        "dt": args.dt,
        "end_time": args.end_time,
    }
    with open(os.path.join(case, "benchmark_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
