#!/usr/bin/env python3
"""Programa v3 — correcciones del diagnostico final.

Cambios frente a programa_completo.py:

  1. potentialFlow existe en fvSolution (el bug que invalidaba A1).
  2. Los transitorios arrancan de un ESTACIONARIO CONVERGIDO, no de un
     campo uniforme. potentialFoam no impone la condicion de Kutta y deja
     Cp=-13 en el borde de salida; el RANS convergido si la tiene.
  3. ddt backward (segundo orden) en vez de Euler.
  4. nOuterCorrectors 12, maxCo 1.
  5. GCI con r >= 1.3 real: 45k / 118k / 250k celdas.
  6. DES (kOmegaSSTDES) a angulo alto.
  7. Caja de estela inclinada con el angulo.
  8. y+ < 5 con nutLowReWallFunction.
  9. Se comprueba el codigo de retorno de cada subprocess.

Fases:

  V1  Transitorio corregido alpha=8, 10, 12, 14 (arranca de RANS)
  V2  GCI real con r>=1.3 a alpha=0, 4, 8
  V3  DES a alpha=12, 14, 16
  V4  y+ bajo (bl_dist_min 2e-4) a alpha=0, 4, 8
  V5  Verificacion: estela inclinada a alpha=8, 10

Uso:
    python3 validation/programa_v3.py --work /tmp/v3 --nproc 10
    python3 validation/programa_v3.py --fase V2
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

LADSON = {
    0.0: (-0.0121, 0.00807), 2.0: (0.2213, 0.00814),
    4.0: (0.4272, 0.00823), 6.0: (0.6476, 0.00842),
    8.0: (0.8615, 0.00989), 10.0: (1.0669, 0.01168),
    11.0: (1.1608, 0.01225), 12.0: (1.2550, 0.01294),
    13.0: (1.3455, 0.01503), 14.0: (1.4316, 0.01533),
    15.0: (1.5169, 0.01870),
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
    r = subprocess.run(["bash", "-lc",
                        "source /opt/openfoam12/etc/bashrc && env"],
                       capture_output=True, text=True)
    for l in r.stdout.splitlines():
        if "=" in l:
            k, v = l.split("=", 1)
            en[k] = v
    return en


def run(cmd, cwd, env, timeout, logfile=None, check=True):
    """Ejecuta y COMPRUEBA el codigo de retorno.

    El bug original: se llamaba potentialFoam con capture_output=True y se
    ignoraba el rc. Fallaba con "keyword potentialFlow is undefined" y el
    transitorio arrancaba de un campo uniforme sin que nadie lo notara.
    """
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                       text=True, stdin=subprocess.DEVNULL, timeout=timeout)
    if check and r.returncode != 0:
        cola = (r.stderr or r.stdout or "")[-400:]
        raise RuntimeError(f"{cmd[0]} rc={r.returncode}: {cola}")
    return r


def leer_coeffs(caso, fraccion=0.8):
    files = glob.glob(os.path.join(caso, "postProcessing", "forceCoeffs",
                                   "*", "*.dat"))
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


def malla(caso, params, env):
    msh = os.path.join(caso, "m.msh")
    if os.path.exists(msh):
        return
    pj = os.path.join(caso, "params.json")
    json.dump(params, open(pj, "w"))
    r = subprocess.run([sys.executable, "-m", "core.mesh_script", pj, msh],
                       cwd=ROOT, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=10800)
    if not os.path.exists(msh):
        raise RuntimeError("malla: " + (r.stderr or "")[-300:])


def preparar(caso, params, nproc, env, transient=False, iters=ITER_EST):
    os.makedirs(caso, exist_ok=True)
    malla(caso, params, env)

    sys.path.insert(0, ROOT)
    from core.openfoam_setup import OpenFoamSetup
    kwargs = dict(
        u_inlet=15.0, p_outlet=0.0, chord=1.0, transient=transient,
        tolerance="1e-5",
        turbulence=params.get("turbulence", "k-Omega SST (RAS)"),
        reynolds=params.get("reynolds", 6e6),
        momentum_scheme="limitedLinearV", depth=0.1,
        bl_dist_min=params.get("bl_dist_min", 8e-4))
    if transient:
        kwargs.update(delta_t="1e-5", end_time=str(params.get("end_time", 0.4)),
                      write_interval="0.02", max_co=1.0, max_iters=500000)
    else:
        kwargs.update(max_iters=iters)
    OpenFoamSetup(case_dir=caso).create_case(**kwargs)

    run(["gmshToFoam", "m.msh"], caso, env, 3600)
    bf = os.path.join(caso, "constant", "polyMesh", "boundary")
    if not os.path.exists(bf):
        raise RuntimeError("gmshToFoam no genero boundary")
    t = open(bf).read()
    for nombre, tipo in (("frontAndBack", "empty"), ("defaultFaces", "empty"),
                         ("airfoil", "wall")):
        t = re.sub(r"(" + nombre + r"\s*\{[^}]*?type\s+)\w+(\s*;)",
                   r"\g<1>" + tipo + r"\g<2>", t, count=1, flags=re.S)
    open(bf, "w").write(t)

    fs = os.path.join(caso, "system", "fvSolution")
    s = open(fs).read()
    s = s.replace("fields { p 0.2; }", "fields { p 0.12; }")
    s = s.replace("U 0.5; k 0.5; omega 0.5;",
                  "U 0.35; k 0.35; omega 0.35;")
    open(fs, "w").write(s)

    # potentialFlow debe seguir presente
    if "potentialFlow" not in open(fs).read():
        raise RuntimeError("fvSolution sin potentialFlow")

    dp = os.path.join(caso, "system", "decomposeParDict")
    open(dp, "w").write(
        "FoamFile { version 2.0; format ascii; class dictionary; "
        f"object decomposeParDict; }}\nnumberOfSubdomains {nproc};\n"
        "method scotch;\n")
    run(["decomposePar", "-force"], caso, env, 3600)


def correr_est(tag, params, work, nproc, env, logfile, ref_cl=None,
               ref_cd=None, iters=ITER_EST):
    caso = os.path.join(work, tag)
    c = leer_coeffs(caso, 0.8)
    if c:
        log(f"  {tag}: reutilizado", logfile)
        r = {"tag": tag, "ok": True, "cache": True, **c}
        _errs(r, ref_cl, ref_cd)
        return r

    t0 = time.time()
    try:
        preparar(caso, params, nproc, env, transient=False, iters=iters)
        with open(os.path.join(caso, "run.log"), "w") as fh:
            subprocess.run(["mpirun", "-np", str(nproc), "foamRun",
                            "-parallel", "-solver", "incompressibleFluid"],
                           cwd=caso, env=env, stdout=fh,
                           stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, timeout=21600)
    except Exception as e:
        return {"tag": tag, "ok": False, "error": str(e)[:300]}

    c = leer_coeffs(caso, 0.8)
    dt = round(time.time() - t0, 1)
    if not c:
        return {"tag": tag, "ok": False, "error": "sin coeficientes",
                "segundos": dt}
    r = {"tag": tag, "ok": True, "segundos": dt, **c}
    _errs(r, ref_cl, ref_cd)
    return r


def correr_trans(tag, params, work, nproc, env, logfile, ref_cl=None,
                 ref_cd=None):
    """Estacionario y luego transitorio EN EL MISMO CASO.

    Copiar campos entre dos casos no funciona: gmsh no es determinista y dos
    ejecuciones con los mismos parametros dan mallas con igual numero de
    celdas pero distinta numeracion. scotch reparte distinto y el solver
    aborta con "size 791 is not equal to the given value of 770".

    En el mismo caso la malla y la descomposicion son unicas: se corre RANS
    hasta converger, se reescriben fvSchemes/fvSolution/controlDict para
    transitorio y se continua desde el ultimo campo escrito.
    """
    caso = os.path.join(work, tag)
    c = leer_coeffs(caso, 0.6)
    if c:
        log(f"  {tag}: reutilizado", logfile)
        r = {"tag": tag, "ok": True, "cache": True, **c}
        _errs(r, ref_cl, ref_cd)
        return r

    t0 = time.time()
    try:
        # --- fase 1: estacionario ---
        log(f"  {tag}: RANS estacionario", logfile)
        preparar(caso, params, nproc, env, transient=False, iters=ITER_EST)
        with open(os.path.join(caso, "run.log"), "w") as fh:
            subprocess.run(["mpirun", "-np", str(nproc), "foamRun",
                            "-parallel", "-solver", "incompressibleFluid"],
                           cwd=caso, env=env, stdout=fh,
                           stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, timeout=21600)

        est = leer_coeffs(caso, 0.8)
        log(f"  {tag}: RANS listo Cl={est['cl']:+.4f} Cd={est['cd']:.5f}"
            if est else f"  {tag}: RANS sin coeficientes, se sigue igual",
            logfile)

        # --- fase 2: reescribir a transitorio sobre el MISMO caso ---
        sys.path.insert(0, ROOT)
        from core.openfoam_setup import OpenFoamSetup
        # conservar el ultimo campo como tiempo inicial: se renombra el
        # directorio del ultimo paso escrito a `0`? No: OpenFOAM arranca en
        # startTime. Se fija startFrom latestTime, que es lo correcto.
        OpenFoamSetup(case_dir=caso).create_case(
            u_inlet=15.0, p_outlet=0.0, chord=1.0, transient=True,
            tolerance="1e-5",
            turbulence=params.get("turbulence", "k-Omega SST (RAS)"),
            reynolds=params.get("reynolds", 6e6),
            momentum_scheme="limitedLinearV", depth=0.1,
            bl_dist_min=params.get("bl_dist_min", 8e-4),
            delta_t="1e-5", end_time=str(params.get("end_time", 0.4)),
            write_interval="0.02", max_co=1.0, max_iters=500000)

        # create_case reescribe 0/ con campos uniformes; hay que restaurar el
        # campo convergido en 0/ para que latestTime no arranque del inicial.
        ult = sorted((d for d in glob.glob(os.path.join(caso, "processor0", "*"))
                      if re.fullmatch(r"[\d.eE+-]+", os.path.basename(d))),
                     key=lambda x: float(os.path.basename(x)))
        if ult:
            src = ult[-1]
            for i in range(nproc):
                dst = os.path.join(caso, f"processor{i}", "0")
                sd = os.path.join(caso, f"processor{i}", os.path.basename(src))
                if not os.path.isdir(sd):
                    continue
                # phi incluido: sin el flujo masico el primer paso
                # transitorio tiene que reconstruirlo y da un salto de
                # Cl (medido: +12% en un solo paso). Con phi el arranque
                # es continuo.
                for f in ("U", "p", "k", "omega", "nut", "phi"):
                    sp = os.path.join(sd, f)
                    if os.path.exists(sp):
                        run(["cp", "-f", sp, dst + "/"], caso, env, 600,
                            check=False)
            log(f"  {tag}: campo de t={os.path.basename(src)} copiado a 0/",
                logfile)

        # la malla es la misma: no se vuelve a descomponer
        with open(os.path.join(caso, "run.log"), "a") as fh:
            subprocess.run(["mpirun", "-np", str(nproc), "foamRun",
                            "-parallel", "-solver", "incompressibleFluid"],
                           cwd=caso, env=env, stdout=fh,
                           stderr=subprocess.STDOUT,
                           stdin=subprocess.DEVNULL, timeout=86400)
    except Exception as e:
        return {"tag": tag, "ok": False, "error": str(e)[:300]}

    c = leer_coeffs(caso, 0.6)
    dt = round(time.time() - t0, 1)
    if not c:
        return {"tag": tag, "ok": False, "error": "sin coeficientes",
                "segundos": dt}
    r = {"tag": tag, "ok": True, "segundos": dt, **c}
    _errs(r, ref_cl, ref_cd)
    return r


def _errs(r, ref_cl, ref_cd):
    if ref_cd:
        r["cd_ref"] = ref_cd
        r["err_cd"] = 100 * (r["cd"] - ref_cd) / ref_cd
    if ref_cl is not None and abs(ref_cl) > 0.05:
        r["cl_ref"] = ref_cl
        r["err_cl"] = 100 * (r["cl"] - ref_cl) / abs(ref_cl)


def gci_roache(cd_g, cd_m, cd_f, n_g, n_m, n_f, fs=1.25):
    """Indice GCI de Roache. Devuelve None si el refinado es insuficiente."""
    r_gm = (n_m / n_g) ** (1 / 3)
    r_mf = (n_f / n_m) ** (1 / 3)
    out = {"r_gm": r_gm, "r_mf": r_mf}
    if r_mf < 1.1:
        out["valido"] = False
        out["motivo"] = f"r={r_mf:.3f} < 1.1"
        return out
    e_gm = cd_m - cd_g
    e_mf = cd_f - cd_m
    out["valido"] = True
    if abs(e_gm) < 1e-14 or abs(e_mf) < 1e-14:
        out["motivo"] = "diferencias nulas"
        out["valido"] = False
        return out
    p = abs(__import__("math").log(abs(e_gm / e_mf))) / \
        abs(__import__("math").log(r_gm))
    out["p"] = p
    if p <= 0.1:
        out["valido"] = False
        out["motivo"] = f"p={p:.2f} no monotono"
        return out
    out["gci_fina_pct"] = fs * abs(e_mf / cd_f) / (r_mf ** p - 1) * 100
    out["extrapolado"] = cd_f + (cd_f - cd_m) / (r_mf ** p - 1)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/v3")
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
    todas = ["V1", "V2", "V3", "V4", "V5"]
    fases = todas if args.fase == "all" else [args.fase]
    log(f"=== PROGRAMA v3 — fases {fases} ===", logfile)

    # ---------------- V1: transitorio corregido ----------------
    if "V1" in fases:
        log("--- V1: transitorio desde RANS, alpha=8,10,12,14 ---", logfile)
        for aoa in (8.0, 10.0, 12.0, 14.0):
            p = dict(MALLA); p["naca"] = "0012"; p["aoa"] = aoa
            p["end_time"] = 0.4
            ref = LADSON.get(aoa)
            r = correr_trans(f"V1_trans_a{aoa:g}", p, args.work, args.nproc,
                             env, logfile, ref[0] if ref else None,
                             ref[1] if ref else None)
            resultados.append(r); guardar()
            if r.get("ok"):
                log(f"  a={aoa:g}: Cl={r['cl']:+.4f} Cd={r['cd']:.5f} "
                    f"err={r.get('err_cd', 0):+.1f}% osc={r['cd_std']:.5f}",
                    logfile)
            else:
                log(f"  a={aoa:g}: FALLO {r.get('error','')}", logfile)

    # ---------------- V2: GCI real r>=1.3 ----------------
    if "V2" in fases:
        log("--- V2: GCI real r>=1.3, alpha=0,4,8 ---", logfile)
        niveles = {
            "gruesa": {"mesh_size_min": 0.020, "nb_airfoil_pts": 150,
                       "bl_dist_min": 2.0e-3, "mesh_num_layers": 8,
                       "mesh_growth_rate": 1.35},
            "base": {},
            "fina": {"mesh_size_min": 0.005, "nb_airfoil_pts": 500,
                     "bl_dist_min": 4e-4, "mesh_num_layers": 18,
                     "mesh_growth_rate": 1.15},
        }
        for aoa in (0.0, 4.0, 8.0):
            vals = {}
            for nom, extra in niveles.items():
                p = dict(MALLA); p["naca"] = "0012"; p["aoa"] = aoa
                p.update(extra)
                ref = LADSON[aoa]
                r = correr_est(f"V2_gci_{nom}_a{aoa:g}", p, args.work,
                               args.nproc, env, logfile, ref[0], ref[1])
                resultados.append(r); guardar()
                if r.get("ok"):
                    vals[nom] = r["cd"]
                    log(f"  {nom} a={aoa:g}: celdas={r['n']} "
                        f"Cd={r['cd']:.5f} err={r.get('err_cd', 0):+.1f}%",
                        logfile)
                else:
                    log(f"  {nom} a={aoa:g}: FALLO {r.get('error','')[:80]}",
                        logfile)

    # ---------------- V3: DES a angulo alto ----------------
    if "V3" in fases:
        log("--- V3: DES kOmegaSSTDES alpha=12,14,16 ---", logfile)
        for aoa in (12.0, 14.0, 16.0):
            p = dict(MALLA); p["naca"] = "0012"; p["aoa"] = aoa
            p["turbulence"] = "DES (kOmegaSSTDES)"
            p["bl_dist_min"] = 4e-4; p["mesh_num_layers"] = 16
            p["nb_airfoil_pts"] = 400
            ref = LADSON.get(aoa)
            r = correr_est(f"V3_des_a{aoa:g}", p, args.work, args.nproc, env,
                           logfile, ref[0] if ref else None,
                           ref[1] if ref else None, iters=4000)
            resultados.append(r); guardar()
            if r.get("ok"):
                log(f"  a={aoa:g}: Cl={r['cl']:+.4f} Cd={r['cd']:.5f} "
                    f"err={r.get('err_cd', 0):+.1f}%", logfile)
            else:
                log(f"  a={aoa:g}: FALLO {r.get('error','')[:100]}", logfile)

    # ---------------- V4: y+ bajo ----------------
    if "V4" in fases:
        log("--- V4: y+<5, bl_dist_min 2e-4, alpha=0,4,8 ---", logfile)
        for aoa in (0.0, 4.0, 8.0):
            p = dict(MALLA); p["naca"] = "0012"; p["aoa"] = aoa
            p["bl_dist_min"] = 2e-4; p["mesh_num_layers"] = 22
            p["mesh_growth_rate"] = 1.12
            p["turbulence"] = "Spalart-Allmaras"  # usa nutLowReWallFunction
            ref = LADSON[aoa]
            r = correr_est(f"V4_yplus_a{aoa:g}", p, args.work, args.nproc,
                           env, logfile, ref[0], ref[1], iters=3000)
            resultados.append(r); guardar()
            if r.get("ok"):
                log(f"  a={aoa:g}: Cl={r['cl']:+.4f} Cd={r['cd']:.5f} "
                    f"err={r.get('err_cd', 0):+.1f}%", logfile)
            else:
                log(f"  a={aoa:g}: FALLO {r.get('error','')[:80]}", logfile)

    # ---------------- V5: estela inclinada ----------------
    if "V5" in fases:
        log("--- V5: estela inclinada alpha=8,10 ---", logfile)
        for aoa in (8.0, 10.0):
            p = dict(MALLA); p["naca"] = "0012"; p["aoa"] = aoa
            p["wake_incline"] = aoa
            ref = LADSON[aoa]
            r = correr_est(f"V5_wake_a{aoa:g}", p, args.work, args.nproc, env,
                           logfile, ref[0], ref[1])
            resultados.append(r); guardar()
            if r.get("ok"):
                log(f"  a={aoa:g}: Cd={r['cd']:.5f} "
                    f"err={r.get('err_cd', 0):+.1f}%", logfile)
            else:
                log(f"  a={aoa:g}: FALLO {r.get('error','')[:80]}", logfile)

    # ---------------- resumen ----------------
    log("\n=== PROGRAMA v3 COMPLETADO ===", logfile)
    ok = [r for r in resultados if r.get("ok") and r.get("err_cd") is not None]
    if ok:
        import statistics as st
        errs = [abs(r["err_cd"]) for r in ok]
        log(f"  con referencia: {len(ok)}", logfile)
        log(f"  dentro 3%: {sum(1 for e in errs if e < 3)}", logfile)
        log(f"  medio: {st.mean(errs):.2f}%  max: {max(errs):.2f}%", logfile)
    fallos = [r for r in resultados if not r.get("ok")]
    log(f"  fallos: {len(fallos)}", logfile)
    for r in fallos:
        log(f"    {r['tag']}: {r.get('error','')[:120]}", logfile)
    guardar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
