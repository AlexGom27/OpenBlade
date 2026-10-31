#!/usr/bin/env python3
"""Programa de validacion completo para 2 semanas de computo autonomo.

Fases
-----
1. Barrido fino NACA 0012: alpha 0-15 en pasos de 1 grado
2. Estudio de convergencia de malla (GCI): 3 niveles de refinado
3. Sensibilidad al dominio: farfield 20c, 40c, 80c
4. Otros perfiles NACA con datos publicados
5. Repeticion de los angulos problematicos con malla mas fina

Todo reanudable: si un caso ya tiene resultados, no se repite.
Escrito para correr semanas sin supervision.

Uso:
    python3 validation/programa_2sem.py --work /tmp/prog --nproc 10
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from core.forces import tail_statistics  # noqa: E402

# ------------------------------------------------------------- referencias
# Ladson, NASA TM 4074 (1988), Re=6e6, transicion forzada
LADSON_0012 = {
    0.0: (-0.0121, 0.00807), 1.0: (0.1045, 0.00810),
    2.0: (0.2213, 0.00814), 3.0: (0.3243, 0.00818),
    4.0: (0.4272, 0.00823), 5.0: (0.5374, 0.00832),
    6.0: (0.6476, 0.00842), 7.0: (0.7546, 0.00912),
    8.0: (0.8615, 0.00989), 9.0: (0.9642, 0.01076),
    10.0: (1.0669, 0.01168), 11.0: (1.1608, 0.01225),
    12.0: (1.2550, 0.01294), 13.0: (1.3455, 0.01503),
    14.0: (1.4316, 0.01533), 15.0: (1.5169, 0.01870),
}

# Malla base validada: Cd -1.46% a alpha=0
MALLA_BASE = {
    "profile_type": "NACA 4-dígitos", "file_path": "",
    "mesh_size_min": 0.008, "mesh_size_max": 0.4,
    "bl_dist_min": 8e-4, "mesh_num_layers": 12,
    "mesh_growth_rate": 1.22, "mesh_nb_points": 300,
    "nb_airfoil_pts": 300, "wake_length": 30.0,
    "farfield": 40.0, "depth": 0.1,
    "mesh_strategy": "unstructured", "bl_growth_dist": 8.0,
}

ITER = 2500


def log(msg, path):
    linea = f"[{time.strftime('%Y-%m-%d %H:%M')}] {msg}"
    print(linea, flush=True)
    with open(path, "a") as f:
        f.write(linea + "\n")


def env_foam():
    en = os.environ.copy()
    r = subprocess.run(["bash", "-lc", "source /opt/openfoam12/etc/bashrc && env"],
                       capture_output=True, text=True)
    for l in r.stdout.splitlines():
        if "=" in l:
            k, v = l.split("=", 1)
            en[k] = v
    return en


def leer_coeffs(caso):
    return tail_statistics(caso, 0.8, minimo=50)


def correr(tag, params, work, nproc, env, logfile, ref=None):
    caso = os.path.join(work, tag)

    c = leer_coeffs(caso)
    if c:
        log(f"  {tag}: reutilizado", logfile)
        r = {"tag": tag, "ok": True, "cache": True, **c}
        if ref:
            r["cl_ref"], r["cd_ref"] = ref
            r["err_cd"] = 100 * (c["cd"] - ref[1]) / ref[1]
        return r

    os.makedirs(caso, exist_ok=True)
    t0 = time.time()

    msh = os.path.join(caso, "m.msh")
    if not os.path.exists(msh):
        pj = os.path.join(caso, "params.json")
        json.dump(params, open(pj, "w"))
        r = subprocess.run([sys.executable, "-m", "core.mesh_script", pj, msh],
                           cwd=ROOT, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=10800)
        if not os.path.exists(msh):
            return {"tag": tag, "ok": False, "error": "malla: " + (r.stderr or "")[-150:]}

    sys.path.insert(0, ROOT)
    from core.openfoam_setup import OpenFoamSetup
    OpenFoamSetup(case_dir=caso).create_case(
        u_inlet=15.0, p_outlet=0.0, chord=1.0, transient=False,
        tolerance="1e-5", turbulence="k-Omega SST (RAS)", reynolds=6e6,
        max_iters=ITER, momentum_scheme="limitedLinearV",
        depth=0.1, bl_dist_min=params.get("bl_dist_min", 8e-4))

    subprocess.run(["gmshToFoam", "m.msh"], cwd=caso, env=env,
                   capture_output=True, stdin=subprocess.DEVNULL, timeout=3600)
    bf = os.path.join(caso, "constant", "polyMesh", "boundary")
    if not os.path.exists(bf):
        return {"tag": tag, "ok": False, "error": "gmshToFoam fallo"}
    t = open(bf).read()
    for nombre, tipo in (("frontAndBack", "empty"), ("defaultFaces", "empty"),
                         ("airfoil", "wall")):
        t = re.sub(r"(" + nombre + r"\s*\{[^}]*?type\s+)\w+(\s*;)",
                   r"\g<1>" + tipo + r"\g<2>", t, count=1, flags=re.S)
    open(bf, "w").write(t)

    fs = os.path.join(caso, "system", "fvSolution")
    s = open(fs).read()
    s = s.replace("fields { p 0.2; }", "fields { p 0.12; }")
    s = s.replace("U 0.5; k 0.5; omega 0.5;", "U 0.35; k 0.35; omega 0.35;")
    open(fs, "w").write(s)

    dp = os.path.join(caso, "system", "decomposeParDict")
    open(dp, "w").write(
        "FoamFile { version 2.0; format ascii; class dictionary; "
        f"object decomposeParDict; }}\nnumberOfSubdomains {nproc};\nmethod scotch;\n")
    subprocess.run(["decomposePar", "-force"], cwd=caso, env=env,
                   capture_output=True, stdin=subprocess.DEVNULL, timeout=3600)
    subprocess.run(["mpirun", "-np", str(nproc), "potentialFoam", "-parallel",
                    "-writep"], cwd=caso, env=env, capture_output=True,
                   stdin=subprocess.DEVNULL, timeout=3600)

    with open(os.path.join(caso, "run.log"), "w") as fh:
        subprocess.run(["mpirun", "-np", str(nproc), "foamRun", "-parallel",
                        "-solver", "incompressibleFluid"],
                       cwd=caso, env=env, stdout=fh, stderr=subprocess.STDOUT,
                       stdin=subprocess.DEVNULL, timeout=21600)

    c = leer_coeffs(caso)
    dt = round(time.time() - t0, 1)
    if not c:
        return {"tag": tag, "ok": False, "error": "sin coeficientes", "segundos": dt}

    r = {"tag": tag, "ok": True, "segundos": dt, **c}
    if ref:
        r["cl_ref"], r["cd_ref"] = ref
        r["err_cd"] = 100 * (c["cd"] - ref[1]) / ref[1]
    return r


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/prog")
    ap.add_argument("--nproc", type=int, default=10)
    ap.add_argument("--fase", default="all",
                    choices=["all", "barrido", "gci", "dominio", "perfiles", "finos"])
    args = ap.parse_args(argv)

    os.makedirs(args.work, exist_ok=True)
    logfile = os.path.join(args.work, "programa.log")
    resfile = os.path.join(args.work, "resultados.json")

    resultados = []
    if os.path.exists(resfile):
        try:
            resultados = json.load(open(resfile))
        except json.JSONDecodeError:
            pass

    def guardar():
        json.dump(resultados, open(resfile, "w"), indent=2)

    env = env_foam()
    fases = (["barrido", "gci", "dominio", "perfiles", "finos"]
             if args.fase == "all" else [args.fase])

    log(f"=== PROGRAMA 2 SEMANAS — fases: {fases} ===", logfile)

    # ---- FASE 1: barrido fino 0012, 1 grado ----
    if "barrido" in fases:
        log("--- FASE 1: barrido 0012 0-15 deg ---", logfile)
        for aoa in [float(a) for a in range(0, 16)]:
            p = dict(MALLA_BASE); p["naca"] = "0012"; p["aoa"] = aoa
            ref = LADSON_0012.get(aoa)
            r = correr(f"b_0012_a{aoa:g}", p, args.work, args.nproc, env,
                       logfile, ref)
            resultados.append(r); guardar()
            e = f"{r['err_cd']:+.1f}%" if r.get("err_cd") is not None else "-"
            log(f"  a={aoa:g}: Cl={r.get('cl',0):+.4f} Cd={r.get('cd',0):.5f} "
                f"err={e}" if r.get("ok") else f"  a={aoa:g}: FALLO {r.get('error','')}",
                logfile)

    # ---- FASE 2: convergencia de malla (GCI) ----
    if "gci" in fases:
        log("--- FASE 2: GCI, 3 niveles a alpha=0 y 8 ---", logfile)
        niveles = {
            "gruesa": {"mesh_size_min": 0.012, "nb_airfoil_pts": 220,
                       "bl_dist_min": 1.2e-3},
            "base": {},
            "fina": {"mesh_size_min": 0.006, "nb_airfoil_pts": 420,
                     "bl_dist_min": 5e-4},
        }
        for aoa in (0.0, 8.0):
            for nom, extra in niveles.items():
                p = dict(MALLA_BASE); p["naca"] = "0012"; p["aoa"] = aoa
                p.update(extra)
                ref = LADSON_0012.get(aoa)
                r = correr(f"gci_{nom}_a{aoa:g}", p, args.work, args.nproc,
                           env, logfile, ref)
                resultados.append(r); guardar()
                log(f"  {nom} a={aoa:g}: Cd={r.get('cd',0):.5f}"
                    if r.get("ok") else f"  {nom} a={aoa:g}: FALLO", logfile)

    # ---- FASE 3: sensibilidad al dominio ----
    if "dominio" in fases:
        log("--- FASE 3: dominio 20c / 40c / 80c ---", logfile)
        for far in (20.0, 80.0):
            for aoa in (0.0, 8.0):
                p = dict(MALLA_BASE); p["naca"] = "0012"; p["aoa"] = aoa
                p["farfield"] = far
                p["wake_length"] = far * 0.75
                ref = LADSON_0012.get(aoa)
                r = correr(f"dom_{far:g}c_a{aoa:g}", p, args.work, args.nproc,
                           env, logfile, ref)
                resultados.append(r); guardar()
                log(f"  {far:g}c a={aoa:g}: Cd={r.get('cd',0):.5f}"
                    if r.get("ok") else f"  {far:g}c a={aoa:g}: FALLO", logfile)

    # ---- FASE 4: otros perfiles (sin ref verificada aun) ----
    if "perfiles" in fases:
        log("--- FASE 4: otros perfiles (recoleccion) ---", logfile)
        for perfil in ("2412", "4412", "0015", "0009"):
            for aoa in (0.0, 4.0, 8.0):
                p = dict(MALLA_BASE); p["naca"] = perfil; p["aoa"] = aoa
                r = correr(f"p_{perfil}_a{aoa:g}", p, args.work, args.nproc,
                           env, logfile, None)
                resultados.append(r); guardar()
                log(f"  {perfil} a={aoa:g}: Cd={r.get('cd',0):.5f}"
                    if r.get("ok") else f"  {perfil} a={aoa:g}: FALLO", logfile)

    # ---- FASE 5: angulos problematicos con malla mas fina ----
    if "finos" in fases:
        log("--- FASE 5: 8, 10, 14 con malla fina ---", logfile)
        for aoa in (8.0, 10.0, 14.0):
            for nom, extra in (("media", {"mesh_size_min": 0.006,
                                          "nb_airfoil_pts": 420}),
                               ("fina", {"mesh_size_min": 0.005,
                                         "nb_airfoil_pts": 520,
                                         "bl_dist_min": 4e-4})):
                p = dict(MALLA_BASE); p["naca"] = "0012"; p["aoa"] = aoa
                p.update(extra)
                ref = LADSON_0012.get(aoa)
                r = correr(f"f_{nom}_a{aoa:g}", p, args.work, args.nproc,
                           env, logfile, ref)
                resultados.append(r); guardar()
                e = f"{r['err_cd']:+.1f}%" if r.get("err_cd") is not None else "-"
                log(f"  {nom} a={aoa:g}: Cd={r.get('cd',0):.5f} err={e}"
                    if r.get("ok") else f"  {nom} a={aoa:g}: FALLO", logfile)

    # resumen
    log("\n=== PROGRAMA COMPLETADO ===", logfile)
    ok = [r for r in resultados if r.get("ok") and r.get("err_cd") is not None]
    if ok:
        import statistics as st
        errs = [abs(r["err_cd"]) for r in ok]
        buenos = [r for r in ok if abs(r["err_cd"]) < 3]
        log(f"  casos con referencia: {len(ok)}", logfile)
        log(f"  dentro del 3%: {len(buenos)}", logfile)
        log(f"  error medio: {st.mean(errs):.2f}%  maximo: {max(errs):.2f}%",
            logfile)
    guardar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
