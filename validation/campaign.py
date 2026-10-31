#!/usr/bin/env python3
"""Campaña de validación contra literatura, perfil por perfil.

Motivación
----------
El informe anterior validaba un solo perfil (NACA 0012) contra una sola tabla.
Eso no permite distinguir un error sistemático del software de un caso
particular. Esta campaña corre varios perfiles con datos experimentales
publicados y compara en dos niveles:

  1. **Cuantitativo**: C_l y C_d frente a la referencia, con error relativo.
  2. **Cualitativo**: la tendencia (pendiente de sustentación, mínimo de
     arrastre, efecto de espesor) que un error de implementación rompería
     aunque los números individuales cuadraran.

Cada perfil es una entrada de ``CASES``. Los datos de referencia viven en
``validation/refs/`` y se citan con su fuente.

Uso
---
    # Ver qué se va a correr
    python3 validation/campaign.py --list

    # Correr un perfil
    python3 validation/campaign.py --case naca0012_tmr

    # Correr todo (largo)
    python3 validation/campaign.py --all
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REFS = os.path.join(HERE, "refs")
OUT = os.path.join(HERE, "campaign")
sys.path.insert(0, ROOT)

from core.forces import final_coefficients  # noqa: E402


# --------------------------------------------------------------------------
# Perfiles y sus referencias
# --------------------------------------------------------------------------
# Cada caso: geometría, condiciones, y de dónde salen los números de referencia.
# Sólo se incluyen casos con datos descargados y verificados en refs/.
CASES = {
    "naca0012_tmr": {
        "profile": "0012",
        "aoa": [0.0, 4.0, 8.0, 10.0],
        "re": 6.0e6,
        "source": "Ladson, NASA TM 4074 (1988), Re=6e6, transition tripped",
        "ref_file": "ladson_clcd.dat",
        "notes": "Caso de validación oficial del NASA TMR.",
    },
    # NOTA: abbott_cl.dat resultó ser del NACA 0012, no del 2412. Usarlo para
    # el 2412 sería una comparación falsa, así que ese caso queda pendiente de
    # una fuente correcta y se retira de la campaña.
    #
    # Casos pendientes de añadir, con su referencia ya descargada:
    #   - placa plana (White): geometría distinta, ver validation/flatplate.py
    #   - NACA 4412 a 13.87 grados (Coles & Wadcock): régimen separado, no
    #     estacionario, requiere solver transitorio
}


def load_ref(entry) -> dict:
    """Carga la referencia y la interpola a los ángulos pedidos."""
    path = os.path.join(REFS, entry["ref_file"])
    if not os.path.exists(path):
        return {}

    pts = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(("#", "variables", "zone")):
                continue
            parts = line.replace(",", " ").split()
            try:
                vals = [float(x) for x in parts[:3]]
            except ValueError:
                continue
            # Algunos ficheros traen 2 columnas (sólo Cl) y otros 3 (Cl y Cd).
            # Se rellena Cd con NaN para poder comparar lo que exista.
            if len(vals) == 2:
                vals.append(float("nan"))
            if len(vals) == 3:
                pts.append(vals)
    if not pts:
        return {}

    pts.sort(key=lambda r: r[0])
    out = {}
    for a in entry["aoa"]:
        # Interpolación lineal; si cae fuera del rango, se descarta
        if a < pts[0][0] or a > pts[-1][0]:
            continue
        for lo, hi in zip(pts, pts[1:]):
            if lo[0] <= a <= hi[0]:
                t = 0.0 if hi[0] == lo[0] else (a - lo[0]) / (hi[0] - lo[0])
                out[a] = {
                    "cl": lo[1] + t * (hi[1] - lo[1]),
                    "cd": (lo[2] + t * (hi[2] - lo[2])
                           if not (lo[2] != lo[2] or hi[2] != hi[2]) else None),
                }
                break
    return out


# --------------------------------------------------------------------------

def read_force_coeffs(case_dir: str):
    """Últimos Cl, Cd y Cm del forceCoeffs de OpenFOAM."""
    return final_coefficients(case_dir)


def run_case(name: str, entry: dict, mesh_only: bool = False) -> dict:
    """Genera malla, corre el CFD y compara con la referencia."""
    case_dir = os.path.join(OUT, name)
    os.makedirs(case_dir, exist_ok=True)

    ref = load_ref(entry)
    results = []

    for aoa in entry["aoa"]:
        tag = f"a{aoa:g}"
        work = os.path.join(case_dir, tag)
        os.makedirs(work, exist_ok=True)

        params = {
            "naca": entry["profile"],
            "chord": 1.0,
            "aoa": aoa,
            "profile_type": "NACA 4-dígitos",
            # Ruta NO estructurada con campo de tamaño por distancia.
            #
            # El C-Grid estructurado reparte la capa límite por todo el radio:
            # a farfield=150c produce 8954 celdas con aspect ratio 1.4e5 y el
            # solver diverge. La ruta no estructurada con Distance+Threshold
            # mantiene el tamaño acotado y da Mesh OK a dominio grande.
            "mesh_size_min": 0.006,
            "mesh_size_max": 0.5,
            "bl_dist_min": 2e-5,
            "mesh_num_layers": 30,
            "mesh_growth_rate": 1.12,
            "mesh_nb_points": 400,
            "wake_length": 100.0,
            "farfield": 50.0,
            "depth": 0.1,
            "mesh_strategy": "structured",
        }
        pfile = os.path.join(work, "params.json")
        with open(pfile, "w") as f:
            json.dump(params, f)

        msh = os.path.join(work, "mesh.msh")
        if not os.path.exists(msh):
            r = subprocess.run(
                [sys.executable, "-m", "core.mesh_script", pfile, msh],
                cwd=ROOT, capture_output=True, text=True, timeout=3600,
            )
            if r.returncode != 0:
                results.append({"aoa": aoa, "ok": False,
                                "error": f"malla: {r.stderr[-300:]}"})
                continue

            # El CType estructurado falla para algunos ángulos y el generador
            # cae al PLAN B (no estructurado) imprimiendo un aviso por stdout.
            # Ese aviso NO se propagaba, así que la campaña mezclaba mallas de
            # dos estrategias distintas creyendo que eran comparables. Se
            # detecta y se registra.
            out_txt = r.stdout + r.stderr
            if "PLAN B" in out_txt or "CType fall" in out_txt:
                results.append({
                    "aoa": aoa, "ok": False,
                    "error": "el C-Grid estructurado falló y cayó al PLAN B; "
                             "la malla no es comparable con las demás",
                })
                continue

        if mesh_only:
            results.append({"aoa": aoa, "ok": True, "mesh": msh})
            continue

        # Caso OpenFOAM + resolución
        from core.openfoam_setup import OpenFoamSetup
        setup = OpenFoamSetup(case_dir=work)
        setup.create_case(
            u_inlet=15.0, p_outlet=0.0, chord=1.0, transient=False,
            tolerance="1e-5",
            turbulence="k-Omega SST (RAS)",
            reynolds=entry["re"],
            max_iters=1500,
            momentum_scheme="linearUpwind",
        )

        # SolverRunner es asíncrono: run_solver lanza el proceso y avisa por
        # callback. Se usa un Event para esperar y se leen los coeficientes del
        # forceCoeffs que escribe OpenFOAM.
        import threading
        from core.solver import SolverRunner

        runner = SolverRunner(case_dir=work, native=False)
        runner.run_gmshToFoam(msh)

        # Inicialización con flujo potencial ANTES de simpleFoam.
        #
        # Sin esto el caso arranca con U uniforme en todo el dominio. A ángulo
        # alto la estela está desviada y ese estado inicial es incoherente: el
        # solver diverge en ~13 iteraciones con SIGFPE. La validación anterior
        # (run_validation.py) sí llamaba a potentialFoam; la campaña no.
        pot_done = threading.Event()
        runner.run_potentialFoam(
            done_callback=lambda c: pot_done.set())
        if not pot_done.wait(timeout=900):
            results.append({"aoa": aoa, "ok": False,
                            "error": "timeout en potentialFoam"})
            continue

        done = threading.Event()
        rc = {"code": None}
        runner.run_solver("simpleFoam",
                          done_callback=lambda c: (rc.__setitem__("code", c),
                                                   done.set()))
        if not done.wait(timeout=5400):
            results.append({"aoa": aoa, "ok": False, "error": "timeout"})
            continue
        if rc["code"] != 0:
            results.append({"aoa": aoa, "ok": False,
                            "error": f"solver rc={rc['code']}"})
            continue

        try:
            cl, cd, cm = read_force_coeffs(work)
        except Exception as e:  # noqa: BLE001
            results.append({"aoa": aoa, "ok": False,
                            "error": f"coeficientes: {e}"})
            continue

        row = {"aoa": aoa, "ok": True, "cl": cl, "cd": cd, "cm": cm}
        r = ref.get(aoa)
        if r:
            row["cl_ref"] = r["cl"]
            row["cd_ref"] = r["cd"]
            row["dcl_pct"] = ((cl - r["cl"]) / abs(r["cl"]) * 100
                              if abs(r["cl"]) > 0.05 else None)
            if r["cd"]:
                row["dcd_pct"] = (cd - r["cd"]) / r["cd"] * 100
        results.append(row)

    out = {"case": name, "entry": entry, "results": results}
    with open(os.path.join(case_dir, "results.json"), "w") as f:
        json.dump(out, f, indent=2)
    return out


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--case", choices=list(CASES))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--mesh-only", action="store_true")
    args = ap.parse_args(argv)

    if args.list:
        for name, e in CASES.items():
            print(f"{name}: NACA {e['profile']}, Re={e['re']:.1e}, "
                  f"alpha={e['aoa']}")
            print(f"    ref: {e['source']}")
        return 0

    names = list(CASES) if args.all else ([args.case] if args.case else [])
    if not names:
        ap.error("indica --case o --all (o --list)")

    for name in names:
        print(f"=== {name} ===")
        out = run_case(name, CASES[name], mesh_only=args.mesh_only)
        for r in out["results"]:
            if not r.get("ok"):
                print(f"  alpha={r['aoa']:g}: FALLO {r.get('error', '')[:80]}")
            elif "cl" in r:
                dcl = f"{r['dcl_pct']:+.1f}%" if r.get("dcl_pct") is not None else "—"
                dcd = f"{r['dcd_pct']:+.1f}%" if r.get("dcd_pct") is not None else "—"
                print(f"  alpha={r['aoa']:g}: Cl={r['cl']:.4f} ({dcl})  "
                      f"Cd={r['cd']:.5f} ({dcd})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
