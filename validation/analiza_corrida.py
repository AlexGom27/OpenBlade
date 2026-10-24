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
    # columnas reales del yPlus.dat: Time, patch, min, max, average
    # (estaban leídas como medio/min/max, que daba el mínimo por media)
    mins = [r[0] for r in filas]
    maxs = [r[1] for r in filas]
    medias = [r[2] for r in filas]
    return {"medio": st.mean(medias), "min": min(mins), "max": max(maxs)}


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
    # OJO: Cl(f) y Cl(r) NO son presion y friccion.
    #
    # En el codigo fuente de OpenFOAM 12
    # (src/functionObjects/forces/forceCoeffs/forceCoeffs.C, linea ~216):
    #
    #     scalar Clf = Cl/2.0 + Cm;
    #     scalar Clr = Cl/2.0 - Cm;
    #
    # Es decir: la mitad de la sustentacion mas/menos el momento de cabeceo.
    # Siempre cumplen Clf + Clr = Cl, y con Cm ~ 0 (perfil simetrico) ambas
    # valen casi lo mismo. Interpretarlas como presion/friccion lleva a
    # conclusiones falsas: en una version anterior de este script se afirmo
    # que "la friccion aporta el 48% del Cl", que era un error de lectura.
    #
    # Para separar presion de friccion hay que usar el objeto `forces` y mirar
    # las componentes pressure/viscous, no el forceCoeffs.
    res["clf_momento"] = res.pop("cl_friccion", None)
    res["clr_momento"] = res.pop("cl_presion", None)

    y = yplus_medio(case)
    if y:
        res["yplus"] = y

    ref = LADSON.get(float(aoa))
    if ref:
        res["cl_ref"], res["cd_ref"] = ref
        # El error relativo de Cl no tiene sentido cuando la referencia es
        # casi cero (alpha=0 en perfil simetrico: -0.0121). Dividir por ahi
        # da "+100%" aunque el valor calculado sea -0.0000, que es correcto.
        # Se usa diferencia absoluta en ese caso.
        if abs(ref[0]) > 0.05:
            res["err_cl"] = 100 * (res["cl"] - ref[0]) / abs(ref[0])
        else:
            res["err_cl_abs"] = res["cl"] - ref[0]
            res["err_cl"] = None
        res["err_cd"] = 100 * (res["cd"] - ref[1]) / ref[1]

    return res


def veredicto(r: dict) -> str:
    """Decide si el modelo de pared funciona y qué hacer."""
    if not r.get("ok"):
        return f"FALLO: {r.get('error')}"

    L = []
    L = []
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
        L.append(f"  {'Cm':14s} {r['cm']:10.4f}")
    L.append("")
    L.append(f"  oscilacion Cl: +/- {r['amplitud_cl']/2:.4f}   "
             f"(std {r['cl_std']:.4f})")
    if "yplus" in r:
        y = r["yplus"]
        L.append(f"  y+: media {y['medio']:.1f}  rango [{y['min']:.1f}, "
                 f"{y['max']:.1f}]")
    L.append("")

    # Veredicto por separado para Cl y Cd.
    if "err_cl" in r:
        if abs(r["err_cl"]) < 10:
            L.append(f"  ✅ Cl dentro del 10% ({r['err_cl']:+.1f}%)")
        else:
            L.append(f"  ❌ Cl fuera del 10% ({r['err_cl']:+.1f}%)")

    if "err_cd" in r:
        if abs(r["err_cd"]) < 15:
            L.append(f"  ✅ Cd dentro del 15% ({r['err_cd']:+.1f}%)")
        elif abs(r["err_cd"]) < 50:
            L.append(f"  ⚠️  Cd alto ({r['err_cd']:+.1f}%)")
        else:
            L.append(f"  ❌ Cd muy alto ({r['err_cd']:+.1f}%)")
            L.append("")
            L.append("  El Cd NO se desglosa en el forceCoeffs: solo da el total.")
            L.append("  Para separar presion de friccion hace falta el objeto")
            L.append("  `forces` con las componentes pressure y viscous.")
            if "yplus" in r:
                y = r["yplus"]
                if y["min"] < 30:
                    L.append(f"  y+ minimo {y['min']:.1f} < 30: parte del perfil")
                    L.append("  esta en zona buffer, donde ninguna ley de pared vale.")

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
