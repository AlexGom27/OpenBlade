#!/usr/bin/env python3
"""Campana de validacion autonoma para NACA 0012 y otros perfiles.

Disenada para correr semanas sin intervencion:
  * reanuda tras interrupciones (si el caso ya tiene resultados, no lo repite)
  * guarda el JSON tras cada caso, no al final
  * tolera fallos individuales sin detener la campana
  * corre en segundo plano con nohup
  * log append-only para poder seguirlo desde fuera

Configuracion validada el 2026-10-24 (Cd -1.46% a alpha=0):
    malla no estructurada, limitedLinearV 1, bl=8e-4, 2000 iteraciones

Uso:
    python3 validation/campana_auto.py --work /tmp/camp --nproc 10
    python3 validation/campana_auto.py --work /tmp/camp --solo 0012
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from core.forces import tail_statistics  # noqa: E402

# ---------------------------------------------------------------- referencias
# Datos experimentales publicados. Solo se incluyen casos con fuente verificada.
REFERENCIAS = {
    # Ladson, NASA TM 4074 (1988), Re=6e6, transicion forzada
    ("0012", 0.0): (-0.0121, 0.00807),
    ("0012", 2.0): (0.2213, 0.00814),
    ("0012", 4.0): (0.4272, 0.00823),
    ("0012", 6.0): (0.6476, 0.00842),
    ("0012", 8.0): (0.8615, 0.00989),
    ("0012", 10.0): (1.0669, 0.01168),
    ("0012", 12.0): (1.2550, 0.01294),
    ("0012", 14.0): (1.4316, 0.01533),
    ("0012", 15.0): (1.5169, 0.01870),
}

# ---------------------------------------------------------------- malla base
MALLA = {
    "chord": 1.0,
    "profile_type": "NACA 4-dígitos",
    "file_path": "",
    "mesh_size_min": 0.008,
    "mesh_size_max": 0.4,
    "bl_dist_min": 8e-4,
    "mesh_num_layers": 12,
    "mesh_growth_rate": 1.22,
    "mesh_nb_points": 300,
    "nb_airfoil_pts": 300,
    "wake_length": 30.0,
    "farfield": 40.0,
    "depth": 0.1,
    "mesh_strategy": "unstructured",
    "bl_growth_dist": 8.0,
}

ITERACIONES = 2000


def log(msg: str, path: str) -> None:
    linea = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(linea, flush=True)
    with open(path, "a") as f:
        f.write(linea + "\n")


def env_foam() -> dict:
    en = os.environ.copy()
    r = subprocess.run(
        ["bash", "-lc", "source /opt/openfoam12/etc/bashrc && env"],
        capture_output=True, text=True)
    for l in r.stdout.splitlines():
        if "=" in l:
            k, v = l.split("=", 1)
            en[k] = v
    return en


def leer_coeffs(caso: str):
    return tail_statistics(caso, 0.8, minimo=50)


def correr(perfil: str, aoa: float, work: str, nproc: int, env: dict,
           logfile: str) -> dict:
    tag = f"{perfil}_a{aoa:g}"
    caso = os.path.join(work, tag)

    # reanudar: si ya tiene resultados validos, no repetir
    c = leer_coeffs(caso)
    if c:
        log(f"  {tag}: ya existe, reutilizando", logfile)
        return {"perfil": perfil, "aoa": aoa, "ok": True, "cache": True, **c}

    os.makedirs(caso, exist_ok=True)
    t0 = time.time()

    # 1. malla
    msh = os.path.join(caso, "m.msh")
    if not os.path.exists(msh):
        p = dict(MALLA)
        p["naca"] = perfil
        p["aoa"] = aoa
        pj = os.path.join(caso, "params.json")
        json.dump(p, open(pj, "w"))
        r = subprocess.run([sys.executable, "-m", "core.mesh_script", pj, msh],
                           cwd=ROOT, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=7200)
        if not os.path.exists(msh):
            return {"perfil": perfil, "aoa": aoa, "ok": False,
                    "error": "malla fallo: " + (r.stderr or "")[-150:]}

    # 2. caso
    sys.path.insert(0, ROOT)
    from core.openfoam_setup import OpenFoamSetup
    OpenFoamSetup(case_dir=caso).create_case(
        u_inlet=15.0, p_outlet=0.0, chord=1.0, transient=False,
        tolerance="1e-5", turbulence="k-Omega SST (RAS)", reynolds=6e6,
        max_iters=ITERACIONES, momentum_scheme="limitedLinearV",
        depth=0.1, bl_dist_min=8e-4)

    # 3. convertir y parches
    subprocess.run(["gmshToFoam", "m.msh"], cwd=caso, env=env,
                   capture_output=True, stdin=subprocess.DEVNULL, timeout=3600)
    bf = os.path.join(caso, "constant", "polyMesh", "boundary")
    if not os.path.exists(bf):
        return {"perfil": perfil, "aoa": aoa, "ok": False,
                "error": "gmshToFoam fallo"}
    t = open(bf).read()
    for nombre, tipo in (("frontAndBack", "empty"), ("defaultFaces", "empty"),
                         ("airfoil", "wall")):
        t = re.sub(r"(" + nombre + r"\s*\{[^}]*?type\s+)\w+(\s*;)",
                   r"\g<1>" + tipo + r"\g<2>", t, count=1, flags=re.S)
    open(bf, "w").write(t)

    # 4. relajacion (la que valido)
    fs = os.path.join(caso, "system", "fvSolution")
    s = open(fs).read()
    s = s.replace("fields { p 0.2; }", "fields { p 0.12; }")
    s = s.replace("U 0.5; k 0.5; omega 0.5;", "U 0.35; k 0.35; omega 0.35;")
    open(fs, "w").write(s)

    # 5. descomponer y correr
    dp = os.path.join(caso, "system", "decomposeParDict")
    open(dp, "w").write(
        "FoamFile { version 2.0; format ascii; class dictionary; "
        "object decomposeParDict; }\n"
        f"numberOfSubdomains {nproc};\nmethod scotch;\n")
    subprocess.run(["decomposePar", "-force"], cwd=caso, env=env,
                   capture_output=True, stdin=subprocess.DEVNULL, timeout=3600)
    subprocess.run(["mpirun", "-np", str(nproc), "potentialFoam", "-parallel",
                    "-writep"], cwd=caso, env=env, capture_output=True,
                   stdin=subprocess.DEVNULL, timeout=3600)

    with open(os.path.join(caso, "run.log"), "w") as fh:
        subprocess.run(["mpirun", "-np", str(nproc), "foamRun", "-parallel",
                        "-solver", "incompressibleFluid"],
                       cwd=caso, env=env, stdout=fh, stderr=subprocess.STDOUT,
                       stdin=subprocess.DEVNULL, timeout=14400)

    c = leer_coeffs(caso)
    dt = round(time.time() - t0, 1)
    if not c:
        return {"perfil": perfil, "aoa": aoa, "ok": False,
                "error": "sin coeficientes estables", "segundos": dt}

    # comparar con referencia
    ref = REFERENCIAS.get((perfil, float(aoa)))
    if ref:
        c["cl_ref"], c["cd_ref"] = ref
        c["err_cl"] = (100 * (c["cl"] - ref[0]) / abs(ref[0])
                       if abs(ref[0]) > 0.05 else None)
        c["err_cd"] = 100 * (c["cd"] - ref[1]) / ref[1]

    return {"perfil": perfil, "aoa": aoa, "ok": True, "segundos": dt, **c}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/camp_auto")
    ap.add_argument("--nproc", type=int, default=10)
    ap.add_argument("--perfiles", nargs="*", default=None)
    ap.add_argument("--angulos", nargs="*", type=float,
                    default=[0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0])
    args = ap.parse_args(argv)

    os.makedirs(args.work, exist_ok=True)
    logfile = os.path.join(args.work, "campana.log")
    resfile = os.path.join(args.work, "resultados.json")

    perfiles = args.perfiles or ["0012"]

    # cargar resultados previos
    resultados = []
    if os.path.exists(resfile):
        try:
            resultados = json.load(open(resfile))
        except json.JSONDecodeError:
            resultados = []

    def guardar():
        json.dump(resultados, open(resfile, "w"), indent=2)

    env = env_foam()
    log(f"=== CAMPANA: {len(perfiles)} perfiles x {len(args.angulos)} angulos ===",
        logfile)

    for perfil in perfiles:
        for aoa in args.angulos:
            log(f"--- {perfil} alpha={aoa:g} ---", logfile)
            try:
                r = correr(perfil, aoa, args.work, args.nproc, env, logfile)
            except Exception as e:  # noqa: BLE001
                r = {"perfil": perfil, "aoa": aoa, "ok": False,
                     "error": str(e)[:200]}
            resultados.append(r)
            guardar()   # tras cada caso, no al final

            if r.get("ok"):
                ec = f"{r['err_cd']:+.2f}%" if r.get("err_cd") is not None else "-"
                log(f"  Cl={r['cl']:+.4f}  Cd={r['cd']:.5f}  err_cd={ec}"
                    f"  ({r.get('segundos', 0):.0f}s)", logfile)
            else:
                log(f"  FALLO: {r.get('error', '?')}", logfile)

    # resumen final
    log("\n=== RESUMEN ===", logfile)
    ok = [r for r in resultados if r.get("ok") and r.get("err_cd") is not None]
    if ok:
        import statistics as st
        errs = [abs(r["err_cd"]) for r in ok]
        log(f"  casos validados: {len(ok)}", logfile)
        log(f"  error |Cd| medio: {st.mean(errs):.2f}%", logfile)
        log(f"  error |Cd| maximo: {max(errs):.2f}%", logfile)

    guardar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
