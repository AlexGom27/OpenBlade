#!/usr/bin/env python3
"""Validación de OpenBlade 2D contra NASA TM 4074 (Ladson 1988).

Referencia: NACA 0012, M=0.15, R=2.0e6.
- Tabla VII (transición forzada con grit #60) para RANS totalmente turbulento.
- Tabla I (transición libre) para el modelo k-omega SST-LM.

Fuente: NTRS 19880019495, transcrita en nasa_tm4074_naca0012.csv.

Uso:
    python3 validation/run_validation.py --alphas 0 2 4 6 --tag sst-upwind
    python3 validation/run_validation.py --alphas 0 4 --tag sst-lu --scheme linearUpwind
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
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

REF_CSV = os.path.join(HERE, "nasa_tm4074_naca0012.csv")

CHORD = 1.0
U_INLET = 15.0
RE = 2_000_000.0


# --------------------------------------------------------------------------
# Referencia experimental
# --------------------------------------------------------------------------
def load_ref(table: str) -> List[Dict[str, float]]:
    rows: List[Dict[str, float]] = []
    with open(REF_CSV) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            t, a, cl, cd, cm = line.split(",")
            if t == table:
                rows.append({"aoa": float(a), "Cl": float(cl),
                             "Cd": float(cd), "Cm": float(cm)})
    return sorted(rows, key=lambda r: r["aoa"])


def interp_ref(alpha: float, rows: List[Dict[str, float]]) -> Dict[str, float]:
    if alpha <= rows[0]["aoa"]:
        return dict(rows[0])
    if alpha >= rows[-1]["aoa"]:
        return dict(rows[-1])
    for lo, hi in zip(rows, rows[1:]):
        if lo["aoa"] <= alpha <= hi["aoa"]:
            t = (alpha - lo["aoa"]) / (hi["aoa"] - lo["aoa"])
            return {"aoa": alpha,
                    "Cl": lo["Cl"] + t * (hi["Cl"] - lo["Cl"]),
                    "Cd": lo["Cd"] + t * (hi["Cd"] - lo["Cd"]),
                    "Cm": lo["Cm"] + t * (hi["Cm"] - lo["Cm"])}
    return dict(rows[-1])


# --------------------------------------------------------------------------
# Presets de malla / solver
# --------------------------------------------------------------------------
PRESETS: Dict[str, Dict[str, Any]] = {
    # Defaults del GUI (malla pobre: y+ ~ 2700)
    "gui": {
        "mesh_size_min": 0.01, "mesh_size_max": 1.0,
        "bl_dist_min": 0.05, "mesh_num_layers": 5,
        "mesh_growth_rate": 1.15, "mesh_nb_points": 100,
        "wake_length": 5.0, "farfield": 10.0, "depth": 0.1,
        "mesh_strategy": "auto",
    },
    # Corregido: y+ ~ 1, dominio 50c
    "fine": {
        "mesh_size_min": 0.006, "mesh_size_max": 0.4,
        "bl_dist_min": 2e-5, "mesh_num_layers": 30,
        "mesh_growth_rate": 1.12, "mesh_nb_points": 400,
        "wake_length": 20.0, "farfield": 50.0, "depth": 0.1,
        "mesh_strategy": "structured",
    },
}
# Dominio muy grande para descartar bloqueo del túnel
# Dominio grande pero con tamaño de celda exterior acotado: con 0.8c el
# aspect ratio llegaba a 4e4 y el solver divergía.
PRESETS["huge"] = dict(PRESETS["fine"], farfield=150.0, wake_length=100.0,
                       mesh_size_max=0.12, mesh_size_min=0.006)
PRESETS["medium"] = dict(PRESETS["fine"], mesh_size_min=0.008,
                         mesh_size_max=0.4, mesh_nb_points=250, farfield=30.0)


# --------------------------------------------------------------------------
# Extracción de métricas del caso
# --------------------------------------------------------------------------
def yplus_stats(case_dir: str) -> Optional[Dict[str, float]]:
    pp = os.path.join(case_dir, "postProcessing", "yPlus")
    if not os.path.isdir(pp):
        return None
    times = sorted((d for d in os.listdir(pp) if re.fullmatch(r"[\d.]+", d)), key=float)
    if not times:
        return None
    dat = os.path.join(pp, times[-1], "yPlus.dat")
    if not os.path.exists(dat):
        return None
    vals = []
    with open(dat) as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    vals.append(float(parts[2]))
                except ValueError:
                    pass
    if not vals:
        return None
    import numpy as np
    a = np.array(vals)
    return {"mean": float(a.mean()), "min": float(a.min()), "max": float(a.max()),
            "p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)),
            "n": int(a.size)}


def n_cells(case_dir: str) -> Optional[int]:
    owner = os.path.join(case_dir, "constant", "polyMesh", "owner")
    if not os.path.exists(owner):
        return None
    with open(owner) as f:
        head = f.read(500)
    m = re.search(r"nCells:\s*(\d+)", head)
    return int(m.group(1)) if m else None


def last_residuals(log: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for m in re.finditer(r"Solving for (\w+), Initial residual = ([\d.eE+-]+)", log):
        out[m.group(1)] = float(m.group(2))
    return out


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------
def generate_mesh(aoa: float, preset: Dict[str, Any], msh: str, logf) -> bool:
    params = {"naca": "0012", "chord": CHORD, "aoa": aoa,
              "profile_type": "NACA 4-dígitos", "element_type": "Quads (Gmsh)"}
    params.update(preset)
    js = os.path.join(HERE, f"params_{os.path.basename(msh)}.json")
    with open(js, "w") as f:
        json.dump(params, f)
    env = os.environ.copy()
    env["PYTHONPATH"] = ROOT + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    r = subprocess.run([sys.executable, "-m", "core.mesh_script", js, msh],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=HERE, env=env, timeout=1800)
    logf.write(r.stdout + "\n" + r.stderr + "\n")
    return r.returncode == 0 and os.path.exists(msh)


def run_one(alpha: float, preset: Dict[str, Any], turbulence: str,
            scheme: str, tag: str) -> Dict[str, Any]:
    from core.openfoam_setup import OpenFoamSetup
    from core.solver import SolverRunner

    case = os.path.join(HERE, "cases", f"{tag}_a{alpha:g}")
    shutil.rmtree(case, ignore_errors=True)
    os.makedirs(case, exist_ok=True)
    msh = os.path.join(case, "mesh.msh")

    print(f"\n=== alpha={alpha:+.2f}  [{tag}]  preset={preset.get('_name')} ===", flush=True)
    t0 = time.time()

    with open(os.path.join(case, "mesh.log"), "w") as logf:
        if not generate_mesh(alpha, preset, msh, logf):
            return {"aoa": alpha, "ok": False, "error": "mesh"}

    setup = OpenFoamSetup(case_dir=case)
    setup.create_case(u_inlet=U_INLET, p_outlet=0.0, chord=CHORD, transient=False,
                      tolerance="1e-5", turbulence=turbulence, reynolds=RE,
                      max_iters=1500, momentum_scheme=scheme)

    runner = SolverRunner(case_dir=case)
    logs: List[str] = []
    runner.run_gmshToFoam(msh, log_callback=logs.append)

    boundary = os.path.join(case, "constant", "polyMesh", "boundary")
    if not os.path.exists(boundary):
        return {"aoa": alpha, "ok": False, "error": "gmshToFoam"}
    btxt = open(boundary).read()

    done: Dict[str, Any] = {}
    runner.run_potentialFoam(log_callback=logs.append,
                             done_callback=lambda c: done.update({"pf": c}))
    dl = time.time() + 300
    while "pf" not in done and time.time() < dl:
        time.sleep(1)

    forces: Dict[str, Optional[float]] = {"Cl": None, "Cd": None, "Cm": None}
    final: Dict[str, Any] = {}

    def on_force(name: str, value: str) -> None:
        if name in forces:
            forces[name] = float(value)

    t_solve = time.time()
    runner.run_solver(algo_name="simpleFoam", log_callback=logs.append,
                      force_callback=on_force, done_callback=lambda c: final.update({"code": c}))
    dl = time.time() + 5400
    while "code" not in final and time.time() < dl:
        time.sleep(2)

    log_text = "\n".join(logs)
    with open(os.path.join(case, "solver.log"), "w") as f:
        f.write(log_text)

    return {
        "aoa": alpha, "ok": True, "tag": tag,
        "turbulence": turbulence, "scheme": scheme, "preset": preset.get("_name"),
        "Cl": forces["Cl"], "Cd": forces["Cd"], "Cm": forces["Cm"],
        "exit_code": final.get("code"),
        "residuals": last_residuals(log_text),
        "cells": n_cells(case),
        "yplus": yplus_stats(case),
        "patches_ok": "airfoil" in btxt,
        "mesh_time_s": None,
        "total_time_s": round(time.time() - t0, 1),
        "solve_time_s": round(time.time() - t_solve, 1),
    }


def report(rows: List[Dict[str, Any]], ref: List[Dict[str, float]], table: str) -> str:
    lines = []
    lines.append("")
    lines.append("=" * 108)
    lines.append(f"NACA 0012 — OpenBlade 2D vs NASA TM 4074 Tabla {table} "
                 f"(M=0.15, R=2.0e6)")
    lines.append("=" * 108)
    hdr = (f"{'alpha':>6} | {'Cl sim':>8} {'Cl ref':>8} {'dCl%':>7} | "
           f"{'Cd sim':>9} {'Cd ref':>8} {'dCd%':>8} | {'Cm sim':>9} {'Cm ref':>8} | "
           f"{'cells':>7} {'y+50':>6}")
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for r in rows:
        if not r.get("ok"):
            lines.append(f"{r['aoa']:>6.2f} | FALLÓ: {r.get('error')}")
            continue
        rf = interp_ref(r["aoa"], ref)
        cl, cd, cm = r["Cl"], r["Cd"], r["Cm"]
        dcl = (cl - rf["Cl"]) / abs(rf["Cl"]) * 100 if abs(rf["Cl"]) > 0.02 else float("nan")
        dcd = (cd - rf["Cd"]) / rf["Cd"] * 100 if rf["Cd"] else float("nan")
        yp = (r.get("yplus") or {}).get("p50", float("nan"))
        lines.append(f"{r['aoa']:>6.2f} | {cl:>8.4f} {rf['Cl']:>8.4f} {dcl:>+6.1f}% | "
                     f"{cd:>9.5f} {rf['Cd']:>8.5f} {dcd:>+7.1f}% | "
                     f"{cm:>9.5f} {rf['Cm']:>8.4f} | "
                     f"{r.get('cells') or 0:>7} {yp:>6.2f}")
    lines.append("=" * 108)
    txt = "\n".join(lines)
    print(txt)
    return txt


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--alphas", nargs="+", type=float, default=[0.0, 2.0, 4.0, 6.0])
    ap.add_argument("--tag", default="sst_fine_upwind")
    ap.add_argument("--preset", default="fine", choices=sorted(PRESETS))
    ap.add_argument("--turbulence", default="k-Omega SST (RAS)")
    ap.add_argument("--scheme", default="upwind", choices=["upwind", "linearUpwind"])
    args = ap.parse_args()

    preset = dict(PRESETS[args.preset])
    preset["_name"] = args.preset
    table = "VII" if "SST-LM" not in args.turbulence else "I"
    ref = load_ref(table)

    out = os.path.join(HERE, f"results_{args.tag}.json")
    rows: List[Dict[str, Any]] = []
    for a in args.alphas:
        try:
            r = run_one(a, preset, args.turbulence, args.scheme, args.tag)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            r = {"aoa": a, "ok": False, "error": f"{type(e).__name__}: {e}"}
        rows.append(r)
        with open(out, "w") as f:
            json.dump({"tag": args.tag, "reference_table": table,
                       "preset": preset, "results": rows}, f, indent=2)

    txt = report(rows, ref, table)
    with open(os.path.join(HERE, f"report_{args.tag}.txt"), "w") as f:
        f.write(txt)


if __name__ == "__main__":
    main()
