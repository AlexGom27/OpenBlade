#!/usr/bin/env python3
"""Analiza una corrida terminada de NACA 0012 y la compara con Ladson.

Extrae Cl, Cd y el desglose presión/fricción del forceCoeffs, promedia sobre
los ciclos finales, y emite un veredicto:

  * si Cl(r)/Cl baja a ~10% el modelo de pared funciona -> lanzar campaña
  * si sigue alto, indica que hay que investigar (probablemente y+).

Uso:
    python3 validation/analiza_corrida.py --case /tmp/r8 --aoa 8
    python3 validation/analiza_corrida.py --case /tmp/r8 --aoa 8 --json
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import statistics as st
import subprocess
import sys

# Ladson, NASA TM 4074 (1988), Re = 6e6, transición forzada
LADSON = {
    0.0: (-0.0121, 0.00807),
    2.0: (0.2213, 0.00814),
    4.0: (0.4272, 0.00823),
    6.0: (0.6476, 0.00842),
    8.0: (0.8615, 0.00989),
    10.0: (1.0669, 0.01168),
    12.0: (1.2550, 0.01294),
}


def leer_coeffs(case: str):
    """Devuelve listas de t, Cm, Cd, Cl, Cl(f), Cl(r) del forceCoeffs."""
    files = glob.glob(os.path.join(case, "postProcessing", "forceCoeffs",
                                   "*", "*.dat"))
    if not files:
        return None
    f = max(files, key=os.path.getmtime)

    filas = []
    for linea in open(f, errors="replace"):
        if not linea.strip() or linea.lstrip().startswith("#"):
            continue
        v = linea.split()
        if len(v) >= 6:
            try:
                # orden: Time Cm Cd Cl Cl(f) Cl(r)
                filas.append([float(x) for x in v[:6]])
            except ValueError:
                pass
    if not filas:
        return None
    return filas


def yplus_medio(case: str):
    """y+ medio, mínimo y máximo sobre el perfil."""
    files = glob.glob(os.path.join(case, "postProcessing", "yPlus", "*",
                                   "*.dat"))
    if not files:
        return None
    f = max(files, key=os.path.getmtime)
    filas = []
    for linea in open(f, errors="replace"):
        if not linea.strip() or linea.lstrip().startswith("#"):
            continue
        v = linea.split()
        if len(v) >= 4:
            try:
                filas.append((float(v[1]), float(v[2]), float(v[3])))
            except ValueError:
                pass
    if not filas:
        return None
    # columnas tras el tiempo: yPlus medio, mínimo, máximo
    medios = [r[0] for r in filas]
    mins = [r[1] for r in filas]
    maxs = [r[2] for r in filas]
    return {"medio": st.mean(medios), "min": min(mins), "max": max(maxs)}


def comprobar_proceso(case: str) -> int:
    try:
        out = subprocess.run(["pgrep", "-c", "-f", "foamRun"],
                             capture_output=True, text=True, timeout=5).stdout
        return int(out.strip() or 0)
    except Exception:
        return 0


def analizar(case: str, aoa: float, fraccion: float = 0.25) -> dict:
    datos = leer_coeffs(case)
    if not datos:
        return {"ok": False, "error": "sin forceCoeffs"}

    n = len(datos)
    cola = datos[int((1 - fraccion) * n):]

    t = [r[0] for r in cola]
    cm = [r[1] for r in cola]
    cd = [r[2] for r in cola]
    cl = [r[3] for r in cola]
    clf = [r[4] for r in cola]
    clr = [r[5] for r in cola]

    # descartar el arranque: primeros instantes con campo sin desarrollar
    cl_ok = [c for c in cl if abs(c) < 10]
    if not cl_ok:
        return {"ok": False, "error": "Cl fuera de rango (divergencia)"}

    res = {
        "ok": True,
        "case": case,
        "aoa": aoa,
        "muestras": len(cola),
        "t_inicio": t[0],
        "t_fin": t[-1],
        "cl": st.mean(cl),
        "cl_std": st.stdev(cl) if len(cl) > 1 else 0.0,
        "cd": st.mean(cd),
        "cd_std": st.stdev(cd) if len(cd) > 1 else 0.0,
        "cm": st.mean(cm),
        "cl_presion": st.mean(clf),
        "cl_friccion": st.mean(clr),
        "amplitud_cl": max(cl) - min(cl),
        "amplitud_cd": max(cd) - min(cd),
    }
    res["frac_friccion"] = (
        abs(res["cl_friccion"]) / abs(res["cl"]) if res["cl"] else None)

    y = yplus_medio(case)
    if y:
        res["yplus"] = y

    ref = LADSON.get(float(aoa))
    if ref:
        res["cl_ref"], res["cd_ref"] = ref
        res["err_cl"] = 100 * (res["cl"] - ref[0]) / abs(ref[0])
        res["err_cd"] = 100 * (res["cd"] - ref[1]) / ref[1]

    return res


def veredicto(r: dict) -> str:
    """Decide si el modelo de pared funciona y qué hacer."""
    if not r.get("ok"):
        return f"FALLO: {r.get('error')}"

    L = []
    fr = r.get("frac_friccion")
    L.append("=" * 64)
    L.append(f"NACA 0012   alpha = {r['aoa']:g} deg")
    L.append("=" * 64)
    L.append(f"  muestras analizadas: {r['muestras']}  "
             f"(t = {r['t_inicio']:.3f} a {r['t_fin']:.3f})")
    L.append("")
    L.append(f"  {'':14s} {'calculado':>10s} {'Ladson':>10s} {'error':>9s}")
    L.append("  " + "-" * 46)
    if "cl_ref" in r:
        L.append(f"  {'Cl':14s} {r['cl']:10.4f} {r['cl_ref']:10.4f} "
                 f"{r['err_cl']:+8.1f}%")
        L.append(f"  {'Cd':14s} {r['cd']:10.5f} {r['cd_ref']:10.5f} "
                 f"{r['err_cd']:+8.1f}%")
    L.append("")
    L.append(f"  oscilacion Cl: +/- {r['amplitud_cl']/2:.4f}   "
             f"(std {r['cl_std']:.4f})")
    L.append(f"  Cl presion:  {r['cl_presion']:+.4f}")
    L.append(f"  Cl friccion: {r['cl_friccion']:+.4f}"
             + (f"   ({100*fr:.0f}% del total)" if fr is not None else ""))
    if "yplus" in r:
        y = r["yplus"]
        L.append(f"  y+: medio {y['medio']:.1f}  rango [{y['min']:.1f}, "
                 f"{y['max']:.1f}]")
    L.append("")

    if fr is None:
        L.append("  SIN VEREDICTO: falta el desglose de friccion.")
    elif fr < 0.15:
        L.append("  ✅ MODELO DE PARED OK")
        L.append(f"     La friccion aporta {100*fr:.0f}% del Cl (esperado ~10%).")
        if r.get("err_cd", 999) < 50:
            L.append("     -> LANZAR la campana alpha = 0..6")
        else:
            L.append(f"     Pero Cd sigue a {r['err_cd']:+.0f}%: revisar antes.")
    elif fr < 0.30:
        L.append("  ⚠️  PARCIALMENTE ALTO")
        L.append(f"     Friccion {100*fr:.0f}% (esperado ~10%). Mejorable.")
        L.append("     -> Refinar y+ o revisar la ley de pared.")
    else:
        L.append("  ❌ MODELO DE PARED NO VALE")
        L.append(f"     Friccion {100*fr:.0f}% del Cl (esperado ~10%).")
        L.append("     -> INVESTIGAR: el cortante se sobreestima.")
        if "yplus" in r:
            y = r["yplus"]
            if 5 < y["medio"] < 30:
                L.append("     y+ en zona buffer: ni resuelta ni logaritmica.")
                L.append("     Opciones: y+ ~1 (LowRe, dt inviable) o")
                L.append("               y+ > 30 (nutk, ya es el caso)")
                L.append("               -> probar nutUWallFunction / kqRWallFunction")
            elif y["medio"] <= 5:
                L.append("     y+ bajo: usar nutLowReWallFunction")

    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="/tmp/r8")
    ap.add_argument("--aoa", type=float, default=8.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--esperar", action="store_true",
                    help="esperar a que el solver termine")
    args = ap.parse_args(argv)

    case = os.path.expanduser(args.case)

    if args.esperar:
        print("Esperando a que termine el solver...", flush=True)
        while comprobar_proceso(case) > 0:
            import time
            time.sleep(60)
        print("Solver terminado.\n", flush=True)

    r = analizar(case, args.aoa)
    if args.json:
        print(json.dumps(r))
    else:
        print(veredicto(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
