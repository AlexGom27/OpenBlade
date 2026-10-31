#!/usr/bin/env python3
"""Programa E1 — turbulencia de entrada NASA TMR y convergencia por fuerzas.

Diseno consensuado en docs/REVISION_INDEPENDIENTE_V3.md, seccion 7.

Pregunta que responde: cuanto cambian Cl y Cd frente a b_0012_a* cuando la
turbulencia de entrada pasa de nut/nu ~ 14000 (I=5 %, l=0.07c) a nut/nu = 0.009
(NASA TMR). Por eso reutiliza la malla exacta de cada b_0012_a* y los mismos
factores de relajacion: el unico cambio en los casos principales es k y omega.

No modifica core/: campana v3 sigue importandolo mientras corre. k y omega se
reescriben dentro de 0/ de cada caso, antes de decomposePar.

Fases:

  smoke  alpha=0, 300 iteraciones. Puerta: omega pasa de 24 a ~4000.
  E1     alpha=0, 4, 8, 10 en malla base (8000 iteraciones)
         controles alpha=0, 8 con bl_dist_min 2e-5 y nutLowReWallFunction

Uso:
    python3 validation/programa_e1.py --fase smoke --work /tmp/e1 --nproc 4
    python3 validation/programa_e1.py --fase E1 --work /tmp/e1 --nproc 4
"""

from __future__ import annotations

import argparse
import fcntl
import glob
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from core.forces import find_force_files, read_forces  # noqa: E402

from programa_v3 import MALLA, env_foam, log, malla, run  # noqa: E402

U = 15.0
NU = 2.5e-6                     # Re = 6e6, c = 1
TU = 0.00052                    # 0.052 %: k/a^2 = 9e-9 de TMR
NUT_NU = 0.009                  # nut/nu de TMR
K_INF = 1.5 * (U * TU) ** 2
OMEGA_INF = K_INF / (NUT_NU * NU)

ITER_E1 = 8000
ITER_SMOKE = 300
VENTANA = 500                   # iteraciones del criterio por fuerzas
TOL_CL = 0.001                  # (max-min)/|media|
TOL_CD = 0.005
CL_CASI_CERO = 0.05             # con |Cl| menor se usa tolerancia absoluta
BASE = "/tmp/prog/b_0012_a{:g}"

RELAX = """relaxationFactors {
    fields { p 0.12; }
    equations { U 0.35; k 0.35; omega 0.35; epsilon 0.5; nuTilda 0.5; gammaInt 0.5; ReThetat 0.5; }
}
"""

# TMR, SST 897x257, CFL3D. Solo hay datos publicados a estos angulos.
TMR_CL = {10.0: 1.0778}
TMR_CD = {0.0: 0.00809, 10.0: 0.01236}


def ladson_80():
    """Zona 80 grit de refs/ladson_clcd.dat como lista (alpha, cl, cd)."""
    filas, dentro = [], False
    for l in open(os.path.join(HERE, "refs", "ladson_clcd.dat")):
        if l.startswith("zone"):
            dentro = "80 grit" in l
        elif dentro:
            v = l.split()
            if len(v) == 3:
                filas.append(tuple(float(x) for x in v))
    return sorted(filas)


def interp(tabla, aoa):
    for (a0, l0, d0), (a1, l1, d1) in zip(tabla, tabla[1:]):
        if a0 <= aoa <= a1:
            f = (aoa - a0) / (a1 - a0)
            return l0 + f * (l1 - l0), d0 + f * (d1 - d0)
    raise ValueError(f"alpha={aoa} fuera de Ladson")


def fuerzas(caso):
    """Filas (it, cd, cl) de forceCoeffs."""
    if not find_force_files(caso):
        return []
    h = read_forces(caso, ("Time", "Cd", "Cl"))
    return list(zip(h.time, h.cd, h.cl))


def evaluar(filas):
    """Criterio de seccion 7: rango en la ventana final, no un promedio."""
    if len(filas) < VENTANA:
        return {"convergido": False, "n": len(filas)}
    cola = filas[-VENTANA:]
    cd = [x[1] for x in cola]
    cl = [x[2] for x in cola]
    m_cd, m_cl = statistics.fmean(cd), statistics.fmean(cl)
    rango_cd = (max(cd) - min(cd)) / abs(m_cd)
    if abs(m_cl) < CL_CASI_CERO:
        rango_cl = max(cl) - min(cl)
        ok_cl = rango_cl < TOL_CL
    else:
        rango_cl = (max(cl) - min(cl)) / abs(m_cl)
        ok_cl = rango_cl < TOL_CL
    return {"convergido": bool(ok_cl and rango_cd < TOL_CD),
            "n": len(filas), "it_final": cola[-1][0],
            "cl": m_cl, "cd": m_cd,
            "cl_min": min(cl), "cl_max": max(cl),
            "cd_min": min(cd), "cd_max": max(cd),
            "rango_cl": rango_cl, "rango_cd": rango_cd,
            "cl_abs": abs(m_cl) < CL_CASI_CERO}


def lista_escalar(texto, clave):
    """Valores de 'clave uniform x' o 'clave nonuniform List<scalar> n(...)'."""
    m = re.search(clave + r"\s+uniform\s+(\S+?)\s*;", texto)
    if m:
        return [float(m.group(1))]
    m = re.search(clave + r"\s+nonuniform\s+List<scalar>\s*\d*\s*\((.*?)\)",
                  texto, flags=re.S)
    return [float(x) for x in m.group(1).split()] if m else []


def nut_medido(caso):
    """nut/nu en la entrada y en el dominio del ultimo campo escrito."""
    entrada, dominio = [], []
    for proc in glob.glob(os.path.join(caso, "processor*")):
        tiempos = [d for d in os.listdir(proc)
                   if re.fullmatch(r"[\d.eE+-]+", d) and float(d) > 0]
        if not tiempos:
            continue
        ruta = os.path.join(proc, max(tiempos, key=float), "nut")
        if not os.path.exists(ruta):
            continue
        t = open(ruta).read()
        cuerpo, _, frontera = t.partition("boundaryField")
        dominio += lista_escalar(cuerpo, "internalField")
        m = re.search(r"\binlet\s*\{(.*?)\}", frontera, flags=re.S)
        if m:
            entrada += lista_escalar(m.group(1), "value")
    if not dominio:
        return {}
    r = {"nut_nu_dominio_mediana": statistics.median(dominio) / NU}
    if entrada:
        r["nut_nu_entrada_mediana"] = statistics.median(entrada) / NU
    return r


def yplus(caso):
    fs = glob.glob(os.path.join(caso, "postProcessing", "yPlus", "*", "*.dat"))
    if not fs:
        return {}
    ult = [l for l in open(fs[0]) if l.strip() and not l.startswith("#")]
    if not ult:
        return {}
    v = ult[-1].split()
    try:
        return {"yplus_min": float(v[2]), "yplus_max": float(v[3]),
                "yplus_medio": float(v[4])}
    except (IndexError, ValueError):
        return {}


def residuo_p(caso):
    """Residuo inicial de p en las ultimas 500 iteraciones. Solo diagnostico."""
    res = []
    for l in open(os.path.join(caso, "run.log"), errors="replace"):
        if "Solving for p," in l:
            m = re.search(r"Initial residual = ([\d.eE+-]+)", l)
            if m:
                res.append(float(m.group(1)))
    if not res:
        return {}
    cola = res[-VENTANA:]
    return {"res_p_mediana": statistics.median(cola), "res_p_max": max(cola)}


def fijar_turbulencia(caso):
    """Reescribe k y omega en 0/ con los valores TMR y lo comprueba."""
    for campo, valor in (("k", K_INF), ("omega", OMEGA_INF)):
        ruta = os.path.join(caso, "0", campo)
        t, n = re.subn(r"uniform\s+[\d.eE+-]+;", f"uniform {valor:.6e};",
                       open(ruta).read())
        if n < 3:
            raise RuntimeError(f"0/{campo}: solo {n} valores reemplazados")
        open(ruta, "w").write(t)


def preparar(caso, params, nproc, env, iters):
    os.makedirs(caso, exist_ok=True)
    malla(caso, params, env)

    from core.openfoam_setup import OpenFoamSetup
    OpenFoamSetup(case_dir=caso).create_case(
        u_inlet=U, p_outlet=0.0, chord=1.0, transient=False, tolerance="1e-5",
        turbulence="k-Omega SST (RAS)", reynolds=6e6,
        momentum_scheme="limitedLinearV", depth=0.1,
        bl_dist_min=params["bl_dist_min"], max_iters=iters)

    run(["gmshToFoam", "m.msh"], caso, env, 3600)
    bf = os.path.join(caso, "constant", "polyMesh", "boundary")
    t = open(bf).read()
    for nombre, tipo in (("frontAndBack", "empty"), ("defaultFaces", "empty"),
                         ("airfoil", "wall")):
        t = re.sub(r"(" + nombre + r"\s*\{[^}]*?type\s+)\w+(\s*;)",
                   r"\g<1>" + tipo + r"\g<2>", t, count=1, flags=re.S)
    open(bf, "w").write(t)

    fs = os.path.join(caso, "system", "fvSolution")
    s, n = re.subn(r"relaxationFactors\s*\{.*\}\s*$", RELAX, open(fs).read(),
                   flags=re.S)
    if n != 1:
        raise RuntimeError("fvSolution sin relaxationFactors")
    open(fs, "w").write(s)

    fijar_turbulencia(caso)

    open(os.path.join(caso, "system", "decomposeParDict"), "w").write(
        "FoamFile { version 2.0; format ascii; class dictionary; "
        f"object decomposeParDict; }}\nnumberOfSubdomains {nproc};\n"
        "method scotch;\n")
    run(["decomposePar", "-force"], caso, env, 3600)


def correr(tag, aoa, bl, iters, work, nproc, env, logfile, malla_base=None):
    caso = os.path.join(work, tag)
    marca = os.path.join(caso, "resultado.json")
    # Solo cuenta como hecho un caso que escribio su resultado: tener
    # coeficientes no basta, ese fue el falso "reutilizado" de programa_v3.
    if os.path.exists(marca):
        log(f"  {tag}: ya terminado", logfile)
        return json.load(open(marca))

    if os.path.isdir(caso):
        shutil.rmtree(caso)
    os.makedirs(caso)
    p = dict(MALLA, naca="0012", aoa=aoa, bl_dist_min=bl)
    if malla_base:
        shutil.copy(os.path.join(malla_base, "m.msh"),
                    os.path.join(caso, "m.msh"))

    r = {"tag": tag, "aoa": aoa, "bl_dist_min": bl, "ok": False,
         "k_inf": K_INF, "omega_inf": OMEGA_INF, "malla_base": malla_base}
    t0 = time.time()
    log(f"  {tag}: inicio alpha={aoa:g} bl={bl:g} iters={iters}", logfile)
    try:
        preparar(caso, p, nproc, env, iters)
        # --bind-to none: V1 corre a la vez y otro mpirun no debe fijarse a
        # los mismos nucleos.
        with open(os.path.join(caso, "run.log"), "w") as fh:
            rc = subprocess.run(
                ["mpirun", "--bind-to", "none", "-np", str(nproc), "foamRun",
                 "-parallel", "-solver", "incompressibleFluid"],
                cwd=caso, env=env, stdout=fh, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, timeout=21600).returncode
        r["rc"] = rc
        r["ok"] = rc == 0
        if rc != 0:
            r["error"] = f"foamRun rc={rc}"
    except Exception as e:
        r["error"] = str(e)[:300]

    r["segundos"] = round(time.time() - t0, 1)
    filas = fuerzas(caso)
    r.update(evaluar(filas))
    r.update(nut_medido(caso))
    r.update(yplus(caso))
    if os.path.exists(os.path.join(caso, "run.log")):
        r.update(residuo_p(caso))

    if r.get("cd") is not None and aoa >= 0:
        cl_ref, cd_ref = interp(ladson_80(), aoa)
        r["ladson80_cl"], r["ladson80_cd"] = cl_ref, cd_ref
        r["err_cd_ladson80"] = 100 * (r["cd"] - cd_ref) / cd_ref
        if abs(cl_ref) > CL_CASI_CERO:
            r["err_cl_ladson80"] = 100 * (r["cl"] - cl_ref) / abs(cl_ref)
        if aoa in TMR_CL:
            r["err_cl_tmr"] = 100 * (r["cl"] - TMR_CL[aoa]) / TMR_CL[aoa]
        if aoa in TMR_CD:
            r["err_cd_tmr"] = 100 * (r["cd"] - TMR_CD[aoa]) / TMR_CD[aoa]
        base = evaluar(fuerzas(BASE.format(aoa)))
        if base.get("cd"):
            r["base_cl"], r["base_cd"] = base["cl"], base["cd"]
            r["base_rango_cd"] = base["rango_cd"]
            r["delta_cd_pct"] = 100 * (r["cd"] - base["cd"]) / base["cd"]
            r["delta_cl"] = r["cl"] - base["cl"]

    json.dump(r, open(marca, "w"), indent=2)
    resumen = (f"Cl={r['cl']:+.4f} Cd={r['cd']:.5f} "
               f"rangoCl={r['rango_cl']:.4f} rangoCd={r['rango_cd']:.4f} "
               f"convergido={r['convergido']}" if r.get("cd") is not None
               else "sin ventana completa de fuerzas")
    log(f"  {tag}: rc={r.get('rc')} {r['segundos']:.0f}s {resumen}", logfile)
    return r


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/e1")
    ap.add_argument("--nproc", type=int, default=4)
    ap.add_argument("--fase", choices=["smoke", "E1"], required=True)
    args = ap.parse_args(argv)

    os.makedirs(args.work, exist_ok=True)
    lock = open(os.path.join(args.work, "e1.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("Ya hay otra instancia de programa_e1 en " + args.work)

    logfile = os.path.join(args.work, "programa.log")
    resfile = os.path.join(args.work, "resultados_e1.json")
    env = env_foam()
    log(f"=== E1 fase {args.fase} nproc={args.nproc} k={K_INF:.4e} "
        f"omega={OMEGA_INF:.1f} ===", logfile)

    bl = MALLA["bl_dist_min"]
    if args.fase == "smoke":
        casos = [("E1_smoke_a0", 0.0, bl, ITER_SMOKE, BASE.format(0.0))]
    else:
        casos = [(f"E1_a{a:g}", a, bl, ITER_E1, BASE.format(a))
                 for a in (0.0, 4.0, 8.0, 10.0)]
        casos += [(f"E1_ctrl_a{a:g}", a, 2e-5, ITER_E1, None)
                  for a in (0.0, 8.0)]

    resultados = []
    for tag, aoa, b, iters, base in casos:
        resultados.append(correr(tag, aoa, b, iters, args.work, args.nproc,
                                 env, logfile, base))
        json.dump(resultados, open(resfile, "w"), indent=2)

    if args.fase == "E1":
        open(os.path.join(args.work, "DONE"), "w").write(
            time.strftime("%Y-%m-%d %H:%M\n"))
    log(f"=== E1 fase {args.fase} terminada ===", logfile)


if __name__ == "__main__":
    main()
