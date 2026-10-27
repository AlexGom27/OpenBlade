#!/usr/bin/env python3
"""Programa completo de validacion: prioridad alta, media y baja.

Fases (todas reanudables):

  A1  Transitorio alpha=8, 10, 12, 14 — promediado de ciclos
      Es la hipotesis principal para el Cd a angulo alto: si el flujo separa
      y oscila, el estacionario no tiene sentido y el transitorio promediado
      deberia acercarse a Ladson.

  A2  Modelo de transicion gamma-ReTheta SST a alpha=8, 10, 12
      El k-omega SST puro no captura la transicion laminar-turbulenta. Para
      un perfil a Re=6e6 con transicion forzada en el experimento, el modelo
      de transicion puede cambiar el arrastre varios por ciento.

  A3  Segunda fuente: NACA 0012 contra Abbott & von Doenhoff
      Comparar Cl y Cd contra una fuente independiente de Ladson.

  M1  Dominio 80c con malla base, alpha 0 y 8 — explicar por que mejora a 0
      y empeora a 8.

  M2  limitedLinearV con topologia C-Grid (si converge, malla mas ligera).

  M3  GCI ampliado: alpha 4 y 12, tres niveles.

  B1  Barrido de Reynolds: 1e6 y 3e6, alpha 0 y 8.

  B2  Barrido de espesor relativo: 0009, 0012, 0015, 0018, 0021 a alpha 0.

Cada caso guarda su resultado en cuanto termina. Si se interrumpe, al
relanzar continua.

Uso:
    python3 validation/programa_completo.py --work /tmp/full --nproc 10
    python3 validation/programa_completo.py --fase A1
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# --------------------------------------------------------------- referencias
LADSON = {
    0.0: (-0.0121, 0.00807), 2.0: (0.2213, 0.00814),
    4.0: (0.4272, 0.00823), 6.0: (0.6476, 0.00842),
    8.0: (0.8615, 0.00989), 10.0: (1.0669, 0.01168),
    11.0: (1.1608, 0.01225), 12.0: (1.2550, 0.01294),
    13.0: (1.3455, 0.01503), 14.0: (1.4316, 0.01533),
    15.0: (1.5169, 0.01870),
}

# Abbott & von Doenhoff (1959), NACA 0012. Solo Cl: el libro da graficas y
# la digitalizacion del Cd es de baja calidad.
ABBOTT_CL = {
    0.0: 0.0000, 2.0: 0.2194, 4.0: 0.4558,
    6.0: 0.6566, 8.0: 0.8749, 10.0: 1.0995,
}

MALLA = {
    "profile_type": "NACA 4-dígitos", "file_path": "",
    "mesh_size_min": 0.008, "mesh_size_max": 0.4,
    "bl_dist_min": 8e-4, "mesh_num_layers": 12,
    "mesh_growth_rate": 1.22, "mesh_nb_points": 300,
    "nb_airfoil_pts": 300, "wake_length": 30.0,
    "farfield": 40.0, "depth": 0.1,
    "mesh_strategy": "unstructured", "bl_growth_dist": 8.0,
}

ITER_EST = 2500


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


def leer_coeffs(caso, fraccion=0.8):
    files = glob.glob(os.path.join(caso, "postProcessing", "forceCoeffs", "*", "*.dat"))
    if not files:
        return None
    f = max(files, key=os.path.getmtime)
    filas = []
    for l in open(f, errors="replace"):
        if l.strip() and not l.lstrip().startswith("#"):
            v = l.split()
            if len(v) >= 5:
                try:
                    filas.append((float(v[0]), float(v[2]), float(v[3])))
                except ValueError:
                    pass
    if len(filas) < 30:
        return None
    cola = filas[int(fraccion * len(filas)):]
    cl = sum(x[2] for x in cola) / len(cola)
    cd = sum(x[1] for x in cola) / len(cola)
    sd_cd = (sum((x[1] - cd) ** 2 for x in cola) / len(cola)) ** 0.5
    sd_cl = (sum((x[2] - cl) ** 2 for x in cola) / len(cola)) ** 0.5
    return {"cl": cl, "cd": cd, "n": len(cola),
            "cl_std": sd_cl, "cd_std": sd_cd}


def preparar(caso, params, nproc, env, transient=False):
    """Genera malla, caso, parches, relajacion y descompone."""
    os.makedirs(caso, exist_ok=True)

    msh = os.path.join(caso, "m.msh")
    if not os.path.exists(msh):
        pj = os.path.join(caso, "params.json")
        json.dump(params, open(pj, "w"))
        r = subprocess.run([sys.executable, "-m", "core.mesh_script", pj, msh],
                           cwd=ROOT, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=10800)
        if not os.path.exists(msh):
            return "malla fallo: " + (r.stderr or "")[-150:]

    sys.path.insert(0, ROOT)
    from core.openfoam_setup import OpenFoamSetup
    kwargs = dict(
        u_inlet=15.0, p_outlet=0.0, chord=1.0, transient=transient,
        tolerance="1e-5", turbulence=params.get("turbulence", "k-Omega SST (RAS)"),
        reynolds=params.get("reynolds", 6e6),
        momentum_scheme="limitedLinearV", depth=0.1,
        bl_dist_min=params.get("bl_dist_min", 8e-4))
    if transient:
        kwargs.update(delta_t="1e-5", end_time=str(params.get("end_time", 0.6)),
                      write_interval="0.02", max_co=3.0, max_iters=500000)
    else:
        kwargs.update(max_iters=params.get("iters", ITER_EST))
    OpenFoamSetup(case_dir=caso).create_case(**kwargs)

    subprocess.run(["gmshToFoam", "m.msh"], cwd=caso, env=env,
                   capture_output=True, stdin=subprocess.DEVNULL, timeout=3600)
    bf = os.path.join(caso, "constant", "polyMesh", "boundary")
    if not os.path.exists(bf):
        return "gmshToFoam fallo"
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
    return None


def correr(tag, params, work, nproc, env, logfile, ref_cl=None, ref_cd=None,
           transient=False):
    caso = os.path.join(work, tag)

    c = leer_coeffs(caso, 0.6 if transient else 0.8)
    if c:
        log(f"  {tag}: reutilizado", logfile)
        r = {"tag": tag, "ok": True, "cache": True, **c}
        if ref_cd:
            r["cd_ref"] = ref_cd
            r["err_cd"] = 100 * (c["cd"] - ref_cd) / ref_cd
        if ref_cl is not None and abs(ref_cl) > 0.05:
            r["cl_ref"] = ref_cl
            r["err_cl"] = 100 * (c["cl"] - ref_cl) / abs(ref_cl)
        return r

    t0 = time.time()
    err = preparar(caso, params, nproc, env, transient)
    if err:
        return {"tag": tag, "ok": False, "error": err}

    with open(os.path.join(caso, "run.log"), "w") as fh:
        subprocess.run(["mpirun", "-np", str(nproc), "foamRun", "-parallel",
                        "-solver", "incompressibleFluid"],
                       cwd=caso, env=env, stdout=fh, stderr=subprocess.STDOUT,
                       stdin=subprocess.DEVNULL,
                       timeout=86400 if transient else 21600)

    c = leer_coeffs(caso, 0.6 if transient else 0.8)
    dt = round(time.time() - t0, 1)
    if not c:
        return {"tag": tag, "ok": False, "error": "sin coeficientes", "segundos": dt}

    r = {"tag": tag, "ok": True, "segundos": dt, **c}
    if ref_cd:
        r["cd_ref"] = ref_cd
        r["err_cd"] = 100 * (c["cd"] - ref_cd) / ref_cd
    if ref_cl is not None and abs(ref_cl) > 0.05:
        r["cl_ref"] = ref_cl
        r["err_cl"] = 100 * (c["cl"] - ref_cl) / abs(ref_cl)
    return r


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/full")
    ap.add_argument("--nproc", type=int, default=10)
    ap.add_argument("--fase", default="all")
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
    todas = ["A1", "A2", "A3", "M1", "M2", "M3", "B1", "B2"]
    fases = todas if args.fase == "all" else [args.fase]

    log(f"=== PROGRAMA COMPLETO — fases {fases} ===", logfile)

    # ---------------- A1: transitorio a angulo alto ----------------
    if "A1" in fases:
        log("--- A1: transitorio alpha=8,10,12,14 ---", logfile)
        for aoa in (8.0, 10.0, 12.0, 14.0):
            p = dict(MALLA); p["naca"] = "0012"; p["aoa"] = aoa
            p["end_time"] = 0.8
            ref = LADSON.get(aoa)
            r = correr(f"A1_trans_a{aoa:g}", p, args.work, args.nproc, env,
                       logfile, ref[0] if ref else None,
                       ref[1] if ref else None, transient=True)
            resultados.append(r); guardar()
            e = f"{r['err_cd']:+.1f}%" if r.get("err_cd") is not None else "-"
            log(f"  a={aoa:g}: Cl={r.get('cl',0):+.4f} Cd={r.get('cd',0):.5f} "
                f"err={e} osc_cd={r.get('cd_std',0):.5f}"
                if r.get("ok") else f"  a={aoa:g}: FALLO {r.get('error','')}",
                logfile)

    # ---------------- A2: modelo de transicion ----------------
    if "A2" in fases:
        log("--- A2: gamma-ReTheta SST alpha=8,10,12 ---", logfile)
        for aoa in (8.0, 10.0, 12.0):
            p = dict(MALLA); p["naca"] = "0012"; p["aoa"] = aoa
            p["turbulence"] = "SST-LM (gamma-ReTheta)"
            ref = LADSON.get(aoa)
            r = correr(f"A2_lm_a{aoa:g}", p, args.work, args.nproc, env,
                       logfile, ref[0] if ref else None,
                       ref[1] if ref else None)
            resultados.append(r); guardar()
            e = f"{r['err_cd']:+.1f}%" if r.get("err_cd") is not None else "-"
            log(f"  a={aoa:g}: Cd={r.get('cd',0):.5f} err={e}"
                if r.get("ok") else f"  a={aoa:g}: FALLO {r.get('error','')}",
                logfile)

    # ---------------- A3: segunda fuente, Abbott ----------------
    if "A3" in fases:
        log("--- A3: 0012 contra Abbott & von Doenhoff (solo Cl) ---", logfile)
        for aoa, cl_ref in ABBOTT_CL.items():
            if aoa == 0:
                continue
            p = dict(MALLA); p["naca"] = "0012"; p["aoa"] = aoa
            r = correr(f"A3_abbott_a{aoa:g}", p, args.work, args.nproc, env,
                       logfile, cl_ref, None)
            resultados.append(r); guardar()
            e = f"{r['err_cl']:+.1f}%" if r.get("err_cl") is not None else "-"
            log(f"  a={aoa:g}: Cl={r.get('cl',0):+.4f} ref={cl_ref:.4f} err={e}"
                if r.get("ok") else f"  a={aoa:g}: FALLO", logfile)

    # ---------------- M1: dominio 80c ----------------
    if "M1" in fases:
        log("--- M1: dominio 80c, malla base ---", logfile)
        for aoa in (0.0, 8.0):
            p = dict(MALLA); p["naca"] = "0012"; p["aoa"] = aoa
            p["farfield"] = 80.0; p["wake_length"] = 60.0
            ref = LADSON[aoa]
            r = correr(f"M1_dom80_a{aoa:g}", p, args.work, args.nproc, env,
                       logfile, ref[0], ref[1])
            resultados.append(r); guardar()
            log(f"  a={aoa:g}: Cd={r.get('cd',0):.5f} err={r.get('err_cd',0):+.1f}%"
                if r.get("ok") else f"  a={aoa:g}: FALLO", logfile)

    # ---------------- M2: C-Grid con limitedLinearV ----------------
    if "M2" in fases:
        log("--- M2: C-Grid estructurado con limitedLinearV ---", logfile)
        for aoa in (0.0, 4.0, 8.0):
            p = dict(MALLA); p["naca"] = "0012"; p["aoa"] = aoa
            p["mesh_strategy"] = "structured"
            p["farfield"] = 50.0; p["wake_length"] = 50.0
            p["bl_dist_min"] = 2.5e-4; p["mesh_num_layers"] = 30
            p["mesh_size_min"] = 0.006; p["mesh_nb_points"] = 300
            ref = LADSON[aoa]
            r = correr(f"M2_cgrid_a{aoa:g}", p, args.work, args.nproc, env,
                       logfile, ref[0], ref[1])
            resultados.append(r); guardar()
            log(f"  a={aoa:g}: Cd={r.get('cd',0):.5f} err={r.get('err_cd',0):+.1f}%"
                if r.get("ok") else f"  a={aoa:g}: FALLO {r.get('error','')[:50]}",
                logfile)

    # ---------------- M3: GCI a alpha 4 y 12 ----------------
    if "M3" in fases:
        log("--- M3: GCI alpha=4 y 12 ---", logfile)
        niveles = {
            "gruesa": {"mesh_size_min": 0.012, "nb_airfoil_pts": 220,
                       "bl_dist_min": 1.2e-3},
            "base": {},
            "fina": {"mesh_size_min": 0.006, "nb_airfoil_pts": 420,
                     "bl_dist_min": 5e-4},
        }
        for aoa in (4.0, 12.0):
            for nom, extra in niveles.items():
                p = dict(MALLA); p["naca"] = "0012"; p["aoa"] = aoa
                p.update(extra)
                ref = LADSON[aoa]
                r = correr(f"M3_gci_{nom}_a{aoa:g}", p, args.work, args.nproc,
                           env, logfile, ref[0], ref[1])
                resultados.append(r); guardar()
                log(f"  {nom} a={aoa:g}: Cd={r.get('cd',0):.5f} "
                    f"err={r.get('err_cd',0):+.1f}%"
                    if r.get("ok") else f"  {nom} a={aoa:g}: FALLO", logfile)

    # ---------------- B1: barrido de Reynolds ----------------
    if "B1" in fases:
        log("--- B1: Reynolds 1e6 y 3e6 ---", logfile)
        for re in (1e6, 3e6):
            for aoa in (0.0, 8.0):
                p = dict(MALLA); p["naca"] = "0012"; p["aoa"] = aoa
                p["reynolds"] = re
                r = correr(f"B1_re{re:.0e}_a{aoa:g}", p, args.work, args.nproc,
                           env, logfile, None, None)
                resultados.append(r); guardar()
                log(f"  Re={re:.0e} a={aoa:g}: Cl={r.get('cl',0):+.4f} "
                    f"Cd={r.get('cd',0):.5f}"
                    if r.get("ok") else f"  Re={re:.0e} a={aoa:g}: FALLO", logfile)

    # ---------------- B2: espesor relativo ----------------
    if "B2" in fases:
        log("--- B2: barrido de espesor a alpha=0 ---", logfile)
        for perfil in ("0009", "0012", "0015", "0018", "0021"):
            p = dict(MALLA); p["naca"] = perfil; p["aoa"] = 0.0
            r = correr(f"B2_t_{perfil}", p, args.work, args.nproc, env,
                       logfile, None, None)
            resultados.append(r); guardar()
            log(f"  {perfil}: Cd={r.get('cd',0):.5f}"
                if r.get("ok") else f"  {perfil}: FALLO", logfile)

    # resumen
    log("\n=== PROGRAMA COMPLETADO ===", logfile)
    ok = [r for r in resultados if r.get("ok") and r.get("err_cd") is not None]
    if ok:
        import statistics as st
        errs = [abs(r["err_cd"]) for r in ok]
        log(f"  con referencia: {len(ok)}", logfile)
        log(f"  dentro 3%: {sum(1 for e in errs if e < 3)}", logfile)
        log(f"  medio: {st.mean(errs):.2f}%  mediana: {st.median(errs):.2f}%",
            logfile)
    guardar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
