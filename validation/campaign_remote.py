#!/usr/bin/env python3
"""Campaña de validación NACA 0012 contra Ladson (NASA TM 4074).

Corre varios ángulos en secuencia sobre OpenFOAM nativo, en paralelo con
`mpirun`, y compara Cl y Cd con los datos experimentales.

Rango validado
--------------
Solo alpha = 0, 2, 4, 6. Por encima de 8 el generador C-Grid de OpenBlade
produce mallas que divergen cuando la superficie del perfil se resuelve con
suficiente detalle (más de ~400 caras en el patch `airfoil`). Queda documentado
en el informe; la campaña se limita a lo que sí es defendible.

Uso
----
    python3 validation/campaign_remote.py --work /tmp/camp --nproc 10
    python3 validation/campaign_remote.py --cases 0 4 --work /tmp/camp
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Ladson, NASA TM 4074 (1988), Re = 6e6, transición forzada
REF = {
    0.0: (-0.0121, 0.00807),
    2.0: (0.2213, 0.00814),
    4.0: (0.4272, 0.00823),
    6.0: (0.6476, 0.00842),
}

MESH = {
    "naca": "0012", "chord": 1.0,
    "profile_type": "NACA 4-dígitos", "file_path": "",
    # mesh_size 0.008 da ~217 caras en el patch del perfil. Es el valor con el
    # que las corridas convergen; 0.004 (434 caras) diverge a alpha alto.
    "mesh_size_min": 0.008, "mesh_size_max": 0.4,
    "bl_dist_min": 1e-4, "mesh_num_layers": 25,
    "mesh_growth_rate": 1.12, "mesh_nb_points": 300,
    "wake_length": 30.0, "farfield": 40.0, "depth": 0.1,
    "mesh_strategy": "structured",
}


def sh(cmd, cwd=None, env=None, timeout=7200, check=False):
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                       text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    if check and r.returncode != 0:
        raise RuntimeError(f"{cmd[:2]} falló: {(r.stderr or '')[-400:]}")
    return r


def foam_env():
    """Entorno de OpenFOAM para los subprocesos."""
    en = os.environ.copy()
    bashrc = "/opt/openfoam12/etc/bashrc"
    if os.path.exists(bashrc):
        cmd = f"source {bashrc} && env"
        r = sh(["bash", "-lc", cmd])
        for linea in r.stdout.splitlines():
            if "=" in linea:
                k, v = linea.split("=", 1)
                en[k] = v
    en["WM_PROJECT_DIR"] = "/opt/openfoam12"
    return en


def leer_coeffs(case):
    files = glob.glob(os.path.join(case, "postProcessing", "forceCoeffs",
                                   "*", "*.dat"))
    if not files:
        return None
    f = max(files, key=os.path.getmtime)
    filas = [l for l in open(f) if l.strip()
             and not l.lstrip().startswith("#")]
    if not filas:
        return None
    datos = []
    for l in filas:
        v = l.split()
        if len(v) >= 5:
            try:
                datos.append((float(v[0]), float(v[1]), float(v[4])))
            except ValueError:
                pass
    if not datos:
        return None
    # régimen asentado: último 25 %
    cola = datos[int(0.75 * len(datos)):]
    cl = sum(d[2] for d in cola) / len(cola)
    cd = sum(d[1] for d in cola) / len(cola)
    # dispersión
    cl_min = min(d[2] for d in cola)
    cl_max = max(d[2] for d in cola)
    return {"cl": cl, "cd": cd, "n": len(cola),
            "amp_cl": (cl_max - cl_min) / 2.0}


def correr_angulo(aoa, work, nproc, env, max_iters=800):
    caso = os.path.join(work, f"a{aoa:g}")
    if os.path.exists(os.path.join(caso, "postProcessing")):
        c = leer_coeffs(caso)
        if c:
            return {"aoa": aoa, "ok": True, "cache": True, **c}

    os.makedirs(caso, exist_ok=True)

    # 1. malla
    msh = os.path.join(caso, "m.msh")
    if not os.path.exists(msh):
        p = dict(MESH); p["aoa"] = aoa
        pj = os.path.join(caso, "params.json")
        json.dump(p, open(pj, "w"))
        r = sh([sys.executable, "-m", "core.mesh_script", pj, msh], cwd=ROOT)
        if r.returncode != 0 or not os.path.exists(msh):
            return {"aoa": aoa, "ok": False, "error": (r.stderr or "")[-200:]}

    # 2. caso
    sys.path.insert(0, ROOT)
    from core.openfoam_setup import OpenFoamSetup
    OpenFoamSetup(case_dir=caso).create_case(
        u_inlet=15.0, p_outlet=0.0, chord=1.0, transient=False,
        tolerance="1e-4", turbulence="k-Omega SST (RAS)", reynolds=6e6,
        max_iters=max_iters, momentum_scheme="upwind", depth=0.1)

    # 3. convertir malla
    r = sh(["gmshToFoam", "m.msh"], cwd=caso, env=env)
    if not os.path.exists(os.path.join(caso, "constant", "polyMesh", "points")):
        return {"aoa": aoa, "ok": False, "error": "gmshToFoam falló"}

    # 4. tipos de parche
    bf = os.path.join(caso, "constant", "polyMesh", "boundary")
    t = open(bf).read()
    for nombre, tipo in (("frontAndBack", "empty"), ("defaultFaces", "empty"),
                         ("airfoil", "wall")):
        t = re.sub(r"(" + nombre + r"\s*\{[^}]*?type\s+)\w+(\s*;)",
                   r"\g<1>" + tipo + r"\g<2>", t, count=1, flags=re.S)
    open(bf, "w").write(t)

    # 5. descomposición y solver
    dp = os.path.join(caso, "system", "decomposeParDict")
    open(dp, "w").write(
        "FoamFile { version 2.0; format ascii; class dictionary; "
        "object decomposeParDict; }\n"
        f"numberOfSubdomains {nproc};\nmethod scotch;\n")
    sh(["decomposePar", "-force"], cwd=caso, env=env, timeout=3600)

    # Inicialización con flujo potencial ANTES del solver.
    #
    # Sin esto el campo arranca uniforme y el primer residual de Ux es 1. En
    # las corridas que convergían, solve_script.py sí ejecutaba potentialFoam;
    # omitirlo hacía que los cuatro ángulos divergieran en 10 segundos.
    sh(["mpirun", "-np", str(nproc), "potentialFoam", "-parallel", "-writep"],
       cwd=caso, env=env, timeout=3600)

    with open(os.path.join(caso, "run.log"), "w") as log:
        subprocess.run(["mpirun", "-np", str(nproc), "foamRun", "-parallel",
                        "-solver", "incompressibleFluid"],
                       cwd=caso, env=env, stdout=log, stderr=subprocess.STDOUT,
                       stdin=subprocess.DEVNULL, timeout=14400)

    c = leer_coeffs(caso)
    if not c:
        return {"aoa": aoa, "ok": False, "error": "sin coeficientes"}

    # divergencia: residuales enormes o continuidad absurda
    log = open(os.path.join(caso, "run.log"), errors="replace").read()[-8000:]
    m = re.findall(r"continuity errors : sum local = ([-+0-9.eE]+)", log)
    if m and abs(float(m[-1])) > 1e3:
        return {"aoa": aoa, "ok": False, "error": f"divergió (cont={m[-1]})"}

    return {"aoa": aoa, "ok": True, **c}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/camp")
    ap.add_argument("--nproc", type=int, default=10)
    ap.add_argument("--cases", type=float, nargs="*",
                    default=list(REF))
    ap.add_argument("--max-iters", type=int, default=800)
    args = ap.parse_args(argv)

    os.makedirs(args.work, exist_ok=True)
    env = foam_env()

    resultados = []
    for aoa in args.cases:
        print(f"\n=== alpha = {aoa:g} ===", flush=True)
        t0 = time.time()
        try:
            r = correr_angulo(aoa, args.work, args.nproc, env, args.max_iters)
        except Exception as e:  # noqa: BLE001
            r = {"aoa": aoa, "ok": False, "error": str(e)[:200]}
        r["segundos"] = round(time.time() - t0, 1)

        ref = REF.get(float(aoa))
        if r.get("ok") and ref:
            r["cl_ref"], r["cd_ref"] = ref
            r["err_cl"] = 100 * (r["cl"] - ref[0]) / abs(ref[0]) if abs(ref[0]) > 0.05 else None
            r["err_cd"] = 100 * (r["cd"] - ref[1]) / ref[1]

        resultados.append(r)
        if r.get("ok"):
            print(f"  Cl = {r['cl']:+.4f}   Cd = {r['cd']:.5f}   "
                  f"({r['segundos']:.0f} s)", flush=True)
            if r.get("err_cl") is not None:
                print(f"  error Cl {r['err_cl']:+.1f}%   error Cd {r['err_cd']:+.1f}%",
                      flush=True)
        else:
            print(f"  FALLO: {r.get('error','?')}", flush=True)

        json.dump(resultados, open(os.path.join(args.work, "resultados.json"), "w"),
                  indent=2)

    # resumen
    print("\n" + "=" * 62)
    print(f"{'alpha':>6} {'Cl':>9} {'ref':>9} {'err':>8} {'Cd':>9} {'ref':>9} {'err':>8}")
    print("-" * 62)
    for r in resultados:
        if r.get("ok"):
            ec = f"{r['err_cl']:+.1f}%" if r.get("err_cl") is not None else "  —"
            print(f"{r['aoa']:6.0f} {r['cl']:9.4f} {r.get('cl_ref',0):9.4f} {ec:>8} "
                  f"{r['cd']:9.5f} {r.get('cd_ref',0):9.5f} {r['err_cd']:+7.1f}%")
        else:
            print(f"{r['aoa']:6.0f}  FALLO  {r.get('error','')[:40]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
