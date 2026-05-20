"""
Validación OpenBlade 2D vs NASA TM 4074
======================================
Reproduce las condiciones de la Tabla I (Re=2×10⁶, M=0.15, α=12°) usando
simpleFoam (estacionario) y compara contra los valores experimentales NASA.

Usa el mismo pipeline que el GUI: mesh_script.py vía subprocess para garantizar
grupos físicos correctos (inlet, outlet, airfoil, walls_TB, frontAndBack).

NASA Cl(α=12.10°) = 1.218,  Cd = 0.0164,  Cm₀.₂₅ = +0.018
"""
import os
import sys
import time
import json
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.openfoam_setup import OpenFoamSetup
from core.solver import SolverRunner

HERE = os.path.dirname(os.path.abspath(__file__))
CASE_DIR = os.path.join(HERE, "openfoam_case")
MSH_FILE = os.path.join(CASE_DIR, "validacion_nasa.msh")
PARAMS_JSON = os.path.join(HERE, "temp_params_validate.json")

# --- Parámetros NASA Tabla I ---
NACA_CODE = "0012"
CHORD = 1.0
AOA = 12.0
U_INLET = 15.0
RE = 2_000_000.0
TURBULENCE = "k-Omega SST (RAS)"
TOLERANCE = "1e-4"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def step1_mesh_via_gui_script():
    """Llama al mesh_script.py del GUI vía subprocess (asegura grupos físicos)."""
    log("PASO 1/4 — Generando malla vía mesh_script.py del GUI…")
    params = {
        "naca": NACA_CODE,
        "chord": CHORD,
        "aoa": AOA,
        "profile_type": "NACA 4-digit",
        "mesh_size_min": 0.01,    # tamaño cerca del perfil (×chord)
        "mesh_size_max": 0.5,     # tamaño en farfield (×chord)
        "bl_dist_min": 0.001,     # primera celda BL (×chord) → ~y+30
        "mesh_growth_rate": 1.15,
        "mesh_num_layers": 15,
        "mesh_nb_points": 150,
        "wake_length": 5.0,
    }
    with open(PARAMS_JSON, "w") as f:
        json.dump(params, f, indent=2)

    cmd = [sys.executable, os.path.join(HERE, "core", "mesh_script.py"), PARAMS_JSON, MSH_FILE]
    log(f"   $ {' '.join(cmd)}")
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
    elapsed = time.time() - t0
    print(res.stdout[-2000:] if len(res.stdout) > 2000 else res.stdout)
    if res.returncode != 0:
        log(f"   ❌ mesh_script falló (código {res.returncode})")
        print("STDERR:", res.stderr[-1500:])
        raise RuntimeError("mesh generation failed")
    msh_size = os.path.getsize(MSH_FILE) / 1e6
    log(f"   ✅ Malla generada en {elapsed:.1f}s ({msh_size:.1f} MB)")


def step2_openfoam_setup():
    log("PASO 2/4 — Configuración OpenFOAM (simpleFoam estacionario)…")
    setup = OpenFoamSetup(case_dir=CASE_DIR)
    setup.create_case(
        u_inlet=U_INLET,
        p_outlet=0.0,
        chord=CHORD,
        transient=False,
        tolerance=TOLERANCE,
        turbulence=TURBULENCE,
        reynolds=RE,
    )
    nu = (U_INLET * CHORD) / RE
    log(f"   simpleFoam | Re={RE:.0f} | ν={nu:.3e} m²/s | tol={TOLERANCE}")


def step3_solve():
    log("PASO 3/4 — Ejecutando solver (vía Docker)…")
    runner = SolverRunner(case_dir=CASE_DIR)

    log("   3a) gmshToFoam")
    runner.run_gmshToFoam(MSH_FILE, log_callback=lambda m: print(f"      {m}", flush=True))

    # Verificar patches creados
    bf = os.path.join(CASE_DIR, "constant", "polyMesh", "boundary")
    if os.path.exists(bf):
        with open(bf) as f:
            content = f.read()
        patches = []
        import re
        for m in re.finditer(r"^    (\w+)\s*\n    \{", content, re.MULTILINE):
            patches.append(m.group(1))
        log(f"   Patches creados: {patches}")
        if "airfoil" not in patches:
            log("   ❌ FATAL: patch 'airfoil' no se creó. Abortando.")
            return None

    log("   3b) potentialFoam")
    done = {"ok": False, "code": None}
    runner.run_potentialFoam(
        log_callback=lambda m: print(f"      {m}", flush=True),
        done_callback=lambda c: done.update({"ok": True, "code": c}),
    )
    t0 = time.time()
    while not done["ok"] and time.time() - t0 < 180:
        time.sleep(1)

    log("   3c) simpleFoam (solver principal)")
    forces = {"Cd": None, "Cl": None, "Cm": None}
    residuals = []
    solver_done = {"ok": False, "code": None}

    def fcb(name, val):
        forces[name] = val

    def rcb(field, val, t):
        residuals.append((t, field, val))

    def dcb(code):
        solver_done.update({"ok": True, "code": code})

    runner.run_solver(
        algo_name="simpleFoam",
        log_callback=lambda m: None,
        force_callback=fcb,
        residual_callback=rcb,
        done_callback=dcb,
    )

    t0 = time.time()
    last_print = 0
    while not solver_done["ok"] and time.time() - t0 < 2400:  # 40 min máx
        time.sleep(3)
        if time.time() - last_print > 30:
            elapsed = int(time.time() - t0)
            n_res = len(residuals)
            log(f"   … {elapsed//60}m{elapsed%60:02d}s  Cd={forces['Cd']} Cl={forces['Cl']} Cm={forces['Cm']} (residuos:{n_res})")
            last_print = time.time()

    if not solver_done["ok"]:
        log("   ⚠️ Timeout esperando solver")
    else:
        log(f"   simpleFoam finalizó (código {solver_done['code']})")

    return forces


def step4_compare(forces):
    log("PASO 4/4 — Comparación con NASA TM 4074, Tabla I (α≈12°)")
    nasa = {"Cl": 1.218, "Cd": 0.0164, "Cm": 0.018}
    sim = {k: float(v) if v is not None else None for k, v in (forces or {}).items()}

    print("\n" + "=" * 70)
    print(f"{'Coef':<8} {'Simulación':>15} {'NASA':>15} {'Δ%':>15} {'Estado':>10}")
    print("-" * 70)
    for k in ("Cl", "Cd", "Cm"):
        s = sim.get(k)
        n = nasa[k]
        if s is None:
            print(f"{k:<8} {'(no leído)':>15} {n:>15.4f} {'—':>15} {'—':>10}")
            continue
        err = (s - n) / n * 100
        ok = ("✅" if abs(err) < 10 else "⚠️" if abs(err) < 30 else "❌")
        print(f"{k:<8} {s:>15.4f} {n:>15.4f} {err:>14.1f}% {ok:>10}")
    print("=" * 70)


if __name__ == "__main__":
    t_start = time.time()
    try:
        step1_mesh_via_gui_script()
        step2_openfoam_setup()
        forces = step3_solve()
        step4_compare(forces)
        log(f"✅ Validación completa — {int(time.time()-t_start)}s total")
    except Exception as e:
        log(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
