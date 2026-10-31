#!/usr/bin/env python3
"""Batería de pruebas: estacionario vs transitorio, esquemas, ángulos.

Objetivo: encontrar por qué α=8 diverge con segundo orden, y si el régimen
transitorio lo resuelve (que es lo que hace la literatura: a α alto la estela
puede ser inherentemente inestable y entonces no existe solución estacionaria).

Cada prueba deja su resultado en un JSON, para poder comparar sin releer logs.

Uso:
    python3 validation/sweep.py --test steady_schemes
    python3 validation/sweep.py --test transient
    python3 validation/sweep.py --list
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "sweep")
sys.path.insert(0, ROOT)

from core.forces import find_force_files, read_forces  # noqa: E402

IMAGE = "opencfd/openfoam-default"
REF_CL = {0.0: -0.0121, 4.0: 0.4272, 8.0: 0.8615, 10.0: 1.0669}
REF_CD = {0.0: 0.00807, 4.0: 0.00823, 8.0: 0.00989, 10.0: 0.01168}


def run_container(cmd: str, workdir: str, timeout: int = 3600):
    """Ejecuta un comando dentro del contenedor sobre el caso."""
    # Docker exige ruta ABSOLUTA en -v: con una relativa la interpreta como
    # nombre de volumen y falla con "includes invalid characters".
    workdir = os.path.abspath(workdir)
    full = [
        "docker", "run", "--rm", "-v", f"{workdir}:/data", "-w", "/data",
        IMAGE, "bash", "-lc",
        ". /usr/lib/openfoam/openfoam2512/etc/bashrc && " + cmd,
    ]
    try:
        r = subprocess.run(full, capture_output=True, text=True,
                           timeout=timeout, errors="replace")
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"


def make_case(work: str, aoa: float, scheme: str, transient: bool,
              farfield: float = 50.0, max_iters: int = 600) -> bool:
    """Genera malla + diccionarios para una configuración dada."""
    os.makedirs(work, exist_ok=True)

    params = {
        "naca": "0012", "chord": 1.0, "aoa": aoa,
        "profile_type": "NACA 4-dígitos",
        "mesh_size_min": 0.006, "mesh_size_max": 0.5,
        "bl_dist_min": 2e-5, "mesh_num_layers": 30,
        "mesh_growth_rate": 1.12, "mesh_nb_points": 400,
        "wake_length": 100.0, "farfield": farfield,
        "depth": 0.1, "mesh_strategy": "structured",
    }
    pfile = os.path.join(work, "params.json")
    json.dump(params, open(pfile, "w"))

    msh = os.path.join(work, "mesh.msh")
    if not os.path.exists(msh):
        r = subprocess.run([sys.executable, "-m", "core.mesh_script", pfile, msh],
                           cwd=ROOT, capture_output=True, text=True, timeout=3600)
        if r.returncode != 0:
            return False
        if "PLAN B" in (r.stdout + r.stderr):
            return False

    from core.openfoam_setup import OpenFoamSetup
    OpenFoamSetup(case_dir=work).create_case(
        u_inlet=15.0, p_outlet=0.0, chord=1.0,
        transient=transient, tolerance="1e-4",
        turbulence="k-Omega SST (RAS)", reynolds=6e6,
        # Tiempo convectivo c/U = 1/15 = 0.067 s. Se simulan ~4 tránsitos
        # (0.27 s) para ver si la solución oscila o se asienta. Con dt
        # adaptativo a maxCo=1 el paso efectivo ronda 4e-4 s.
        delta_t="1e-4", end_time="0.27", write_interval="0.01",
        max_co=1.0, max_iters=max_iters, momentum_scheme=scheme,
    )

    # gmshToFoam. Se comprueba el resultado por la existencia de polyMesh y
    # no sólo por el código de retorno: OpenFOAM puede salir con 0 habiendo
    # impreso "FOAM exiting" sin crear la malla.
    rc, out = run_container(
        "gmshToFoam /data/mesh.msh -case /data", work, timeout=1800)
    # Tipos de parche. gmshToFoam deja frontAndBack como "patch", pero los
    # campos de 2D esperan "empty". Sin esto el solver aborta con
    # "patch type 'patch' not constraint type 'empty'".
    # Esta corrección vive dentro de SolverRunner.run_gmshToFoam, no en
    # gmshToFoam, así que hay que replicarla aquí.
    bfile = os.path.join(work, "constant", "polyMesh", "boundary")
    if os.path.exists(bfile):
        txt = open(bfile).read()
        for name, ty in (("frontAndBack", "empty"), ("defaultFaces", "empty"),
                         ("airfoil", "wall")):
            txt = re.sub(
                r"(" + re.escape(name) + r"\s*\{[^}]*?type\s+)\w+(\s*;)",
                r"\g<1>" + ty + r"\g<2>", txt, count=1, flags=re.DOTALL)
        open(bfile, "w").write(txt)

    points = os.path.join(work, "constant", "polyMesh", "points")
    if not os.path.exists(points):
        print(f"  gmshToFoam falló (rc={rc}): "
              f"{out.strip().splitlines()[-1] if out.strip() else 'sin salida'}",
              flush=True)
        return False
    return True


def read_coeffs(work: str):
    """Últimos Cl/Cd del fichero de coeficientes."""
    if not find_force_files(work):
        return None
    h = read_forces(work)
    if not len(h):
        return None
    return {"t": h.time[-1], "cd": h.cd[-1], "cl": h.cl[-1],
            "cm": h.cm[-1], "n": len(h)}


def test_steady_schemes() -> dict:
    """Compara esquemas de convección a α=4 y 8, régimen estacionario."""
    results = []
    schemes = ["upwind", "linearUpwind", "limitedLinearV"]

    for aoa in (4.0, 8.0):
        for scheme in schemes:
            tag = f"steady_a{aoa:g}_{scheme}"
            work = os.path.join(OUT, tag)
            print(f"[{tag}]", flush=True)

            if not make_case(work, aoa, scheme, transient=False):
                results.append({"test": tag, "ok": False, "error": "setup"})
                continue

            # El log del solver va a run.log, no a la salida del contenedor:
            # contar "Time =" en `out` daba siempre 0. Se lee del fichero.
            run_container(
                "potentialFoam -case /data -writep > /dev/null 2>&1; "
                "simpleFoam -case /data > run.log 2>&1",
                work, timeout=5400)

            c = read_coeffs(work)
            logpath = os.path.join(work, "run.log")
            iters = 0
            if os.path.exists(logpath):
                iters = len(re.findall(r"^Time = ", open(logpath, errors="replace").read(),
                                       re.M))
            ok = (c is not None and abs(c["cl"]) < 100 and abs(c["cd"]) < 10
                  and iters > 0)
            row = {"test": tag, "aoa": aoa, "scheme": scheme, "ok": ok,
                   "iters": iters, "coeffs": c}
            if c and aoa in REF_CL:
                row["cl_ref"] = REF_CL[aoa]
                row["cd_ref"] = REF_CD[aoa]
                if abs(c["cl"]) < 100:
                    row["cl_err"] = (c["cl"] - REF_CL[aoa]) / abs(REF_CL[aoa]) * 100
                    row["cd_err"] = (c["cd"] - REF_CD[aoa]) / REF_CD[aoa] * 100
            results.append(row)
            print(f"  -> ok={ok} iters={iters} coeffs={c}", flush=True)

    return {"test": "steady_schemes", "results": results}


def test_transient() -> dict:
    """Régimen transitorio a α=4 y 8: ¿existe solución estacionaria?"""
    results = []

    for aoa in (4.0, 8.0):
        tag = f"trans_a{aoa:g}"
        work = os.path.join(OUT, tag)
        print(f"[{tag}]", flush=True)

        # pimpleFoam necesita dt; se usa el setup transitorio
        if not make_case(work, aoa, "limitedLinearV", transient=True):
            results.append({"test": tag, "ok": False, "error": "setup"})
            continue

        rc, out = run_container(
            "potentialFoam -case /data -writep > /dev/null 2>&1; "
            "pimpleFoam -case /data > run.log 2>&1; echo EXIT=$?",
            work, timeout=5400)

        c = read_coeffs(work)
        # Serie temporal para ver si oscila (solución periódica) o diverge
        series = []
        if find_force_files(work):
            h = read_forces(work)
            series = [list(fila) for fila in zip(h.time, h.cl, h.cd)]

        # ¿Oscila? Amplitud de los últimos 30% de la serie
        osc = None
        if len(series) > 20:
            tail = series[int(0.7 * len(series)):]
            cls = [r[1] for r in tail]
            osc = {"cl_min": min(cls), "cl_max": max(cls),
                   "amplitude": (max(cls) - min(cls)) / 2 if max(cls) > min(cls) else 0}
            osc["mean_cl"] = sum(cls) / len(cls)

        ok = c is not None and abs(c["cl"]) < 100
        row = {"test": tag, "aoa": aoa, "ok": ok, "coeffs": c,
               "oscillation": osc, "n_samples": len(series)}
        if c and aoa in REF_CL and abs(c["cl"]) < 100:
            row["cl_ref"] = REF_CL[aoa]
            row["cd_ref"] = REF_CD[aoa]
            # Se compara la media de la oscilación si existe
            cl_cmp = osc["mean_cl"] if osc else c["cl"]
            row["cl_err"] = (cl_cmp - REF_CL[aoa]) / abs(REF_CL[aoa]) * 100
            row["cd_err"] = (c["cd"] - REF_CD[aoa]) / REF_CD[aoa] * 100
        results.append(row)
        print(f"  -> ok={ok} coeffs={c} osc={osc}", flush=True)

    return {"test": "transient", "results": results}


def test_angle_sweep() -> dict:
    """Barrido de ángulo en transitorio, de 0 a 12."""
    results = []
    for aoa in (0.0, 2.0, 6.0, 10.0, 12.0):
        tag = f"trans_a{aoa:g}"
        work = os.path.join(OUT, tag)
        print(f"[{tag}]", flush=True)
        if os.path.exists(os.path.join(work, "postProcessing")):
            c = read_coeffs(work)
            results.append({"test": tag, "aoa": aoa, "cached": True,
                            "coeffs": c})
            continue
        results.append({"test": tag, "aoa": aoa, "ok": False,
                        "error": "no ejecutado"})
    return {"test": "angle_sweep", "results": results}


TESTS = {
    "steady_schemes": test_steady_schemes,
    "transient": test_transient,
    "angle_sweep": test_angle_sweep,
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", choices=list(TESTS))
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)

    if args.list:
        for k in TESTS:
            print(k)
        return 0
    if not args.test:
        ap.error("indica --test")

    os.makedirs(OUT, exist_ok=True)
    out = TESTS[args.test]()
    path = os.path.join(OUT, f"{args.test}.json")
    json.dump(out, open(path, "w"), indent=2)
    print(f"\nEscrito: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
