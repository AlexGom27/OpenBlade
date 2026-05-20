"""
Validación de curva polar completa NACA 0012 vs NASA TM 4074, Tabla I (Re=2×10⁶).
Ejecuta múltiples ángulos de ataque y compila la comparación.
"""
import os
import sys
import time
import json
import subprocess
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.openfoam_setup import OpenFoamSetup
from core.solver import SolverRunner

HERE = os.path.dirname(os.path.abspath(__file__))
CASE_DIR = os.path.join(HERE, "openfoam_case")
RESULTS_FILE = os.path.join(HERE, "results_nasa_polar.json")
MSH_FILE = os.path.join(CASE_DIR, "validacion_nasa.msh")
PARAMS_JSON = os.path.join(HERE, "temp_params_validate.json")

NACA = "0012"
CHORD = 1.0
U_INLET = 15.0
RE = 2_000_000.0
TURBULENCE = "k-Omega SST (RAS)"
TOLERANCE = "1e-4"

# Puntos NASA TM 4074, Tabla I, Re=2.00×10⁶, M=0.15 (Free Transition)
NASA_TABLE_I = {
    -4.25: {"Cl": -0.430, "Cd": 0.00730, "Cm": -0.0040},
    -2.10: {"Cl": -0.215, "Cd": 0.00620, "Cm": -0.0020},
     0.00: {"Cl":  0.000, "Cd": 0.00620, "Cm":  0.0000},
     1.85: {"Cl":  0.194, "Cd": 0.00620, "Cm":  0.0030},
     4.25: {"Cl":  0.445, "Cd": 0.00670, "Cm":  0.0040},
     6.05: {"Cl":  0.625, "Cd": 0.00870, "Cm":  0.0070},
     8.15: {"Cl":  0.855, "Cd": 0.01270, "Cm":  0.0080},
    10.15: {"Cl":  1.045, "Cd": 0.01350, "Cm":  0.0120},
    11.15: {"Cl":  1.135, "Cd": 0.01490, "Cm":  0.0140},
    12.10: {"Cl":  1.218, "Cd": 0.01640, "Cm":  0.0180},
    13.08: {"Cl":  1.290, "Cd": 0.01880, "Cm":  0.0190},
    14.25: {"Cl":  1.362, "Cd": 0.02280, "Cm":  0.0220},
    15.25: {"Cl":  1.408, "Cd": 0.02910, "Cm":  0.0250},
}

# Ángulos a simular (clave: lineal pre-stall, denso cerca de stall)
AOA_LIST = [0.0, 4.0, 8.0, 12.0]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def generate_mesh(aoa: float) -> bool:
    """Genera la malla usando mesh_script.py del GUI."""
    params = {
        "naca": NACA, "chord": CHORD, "aoa": aoa,
        "profile_type": "NACA 4-digit",
        "mesh_size_min": 0.01, "mesh_size_max": 0.5,
        "bl_dist_min": 0.001, "mesh_growth_rate": 1.15,
        "mesh_num_layers": 15, "mesh_nb_points": 150, "wake_length": 5.0,
    }
    with open(PARAMS_JSON, "w") as f:
        json.dump(params, f)
    res = subprocess.run(
        [sys.executable, os.path.join(HERE, "core", "mesh_script.py"), PARAMS_JSON, MSH_FILE],
        capture_output=True, text=True, cwd=HERE, timeout=300,
    )
    return res.returncode == 0


def run_aoa(aoa: float) -> dict:
    """Pipeline completo: malla + setup + solve para un AoA dado."""
    log(f"\n────────── α = {aoa:+.2f}° ──────────")

    # Limpieza
    try:
        shutil.rmtree(os.path.join(CASE_DIR, "constant", "polyMesh"), ignore_errors=True)
        shutil.rmtree(os.path.join(CASE_DIR, "postProcessing"), ignore_errors=True)
        for item in os.listdir(CASE_DIR):
            try:
                float(item)
                if item != "0":
                    shutil.rmtree(os.path.join(CASE_DIR, item), ignore_errors=True)
            except (ValueError, FileNotFoundError):
                pass
    except Exception:
        pass

    # 1. Malla
    log("  Generando malla…")
    t0 = time.time()
    if not generate_mesh(aoa):
        log("  ❌ Falló malla")
        return {"aoa": aoa, "ok": False, "error": "mesh"}
    log(f"  ✅ Malla en {time.time()-t0:.1f}s")

    # 2. Setup OpenFOAM
    setup = OpenFoamSetup(case_dir=CASE_DIR)
    setup.create_case(u_inlet=U_INLET, p_outlet=0.0, chord=CHORD, transient=False,
                       tolerance=TOLERANCE, turbulence=TURBULENCE, reynolds=RE)

    # 3. Solver
    runner = SolverRunner(case_dir=CASE_DIR)
    log("  gmshToFoam…")
    runner.run_gmshToFoam(MSH_FILE, log_callback=lambda m: None)

    # Verificar patches
    bf = os.path.join(CASE_DIR, "constant", "polyMesh", "boundary")
    if os.path.exists(bf):
        with open(bf) as f: content = f.read()
        if "airfoil" not in content:
            log("  ❌ Sin patch airfoil")
            return {"aoa": aoa, "ok": False, "error": "no_airfoil_patch"}

    log("  potentialFoam…")
    done = {"ok": False}
    runner.run_potentialFoam(log_callback=lambda m: None,
                              done_callback=lambda c: done.update({"ok": True}))
    t0 = time.time()
    while not done["ok"] and time.time() - t0 < 120:
        time.sleep(1)

    log("  simpleFoam…")
    forces = {"Cd": None, "Cl": None, "Cm": None}
    solver_done = {"ok": False, "code": None}
    runner.run_solver(
        algo_name="simpleFoam", log_callback=lambda m: None,
        force_callback=lambda n, v: forces.__setitem__(n, v),
        residual_callback=lambda f, v, t: None,
        done_callback=lambda c: solver_done.update({"ok": True, "code": c}),
    )
    t0 = time.time()
    while not solver_done["ok"] and time.time() - t0 < 600:
        time.sleep(2)

    elapsed = time.time() - t0
    log(f"  ✅ Solver en {elapsed:.0f}s")
    return {
        "aoa": aoa, "ok": True,
        "Cl": float(forces["Cl"]) if forces["Cl"] is not None else None,
        "Cd": float(forces["Cd"]) if forces["Cd"] is not None else None,
        "Cm": float(forces["Cm"]) if forces["Cm"] is not None else None,
        "solver_time_s": int(elapsed),
    }


def print_report(results: list):
    """Imprime tabla comparativa y guarda JSON."""
    print("\n" + "=" * 95)
    print(f"VALIDACIÓN OpenBlade 2D vs NASA TM 4074, Tabla I  (Re=2×10⁶, M=0.15, Free Transition)")
    print("=" * 95)
    print(f"{'α (°)':>7} | {'Cl sim':>9} {'Cl NASA':>9} {'ΔCl%':>7} | "
          f"{'Cd sim':>10} {'Cd NASA':>10} {'ΔCd%':>8} | "
          f"{'Cm sim':>10} {'Cm NASA':>10}")
    print("-" * 95)

    summary = []
    for r in results:
        if not r["ok"]:
            print(f"{r['aoa']:>7.2f} |  FALLÓ ({r.get('error', 'desconocido')})")
            continue
        a = r["aoa"]
        # Encontrar punto NASA más cercano
        nasa_a = min(NASA_TABLE_I.keys(), key=lambda x: abs(x - a))
        nasa = NASA_TABLE_I[nasa_a]
        cl_err = (r["Cl"] - nasa["Cl"]) / nasa["Cl"] * 100 if abs(nasa["Cl"]) > 0.01 else float("nan")
        cd_err = (r["Cd"] - nasa["Cd"]) / nasa["Cd"] * 100
        print(f"{a:>7.2f} | {r['Cl']:>9.4f} {nasa['Cl']:>9.4f} {cl_err:>+6.1f}% | "
              f"{r['Cd']:>10.5f} {nasa['Cd']:>10.5f} {cd_err:>+7.1f}% | "
              f"{r['Cm']:>10.5f} {nasa['Cm']:>10.5f}")
        summary.append({"aoa": a, "cl_err_pct": cl_err, "cd_err_pct": cd_err,
                         "sim": r, "nasa": nasa})

    print("=" * 95)

    with open(RESULTS_FILE, "w") as f:
        json.dump({"results": results, "summary": summary,
                    "nasa_source": "NASA TM 4074, Tabla I, Re=2.00e6, M=0.15"}, f, indent=2)
    log(f"Resultados guardados en {RESULTS_FILE}")


if __name__ == "__main__":
    t0_total = time.time()
    all_results = []
    for aoa in AOA_LIST:
        try:
            r = run_aoa(aoa)
        except Exception as e:
            r = {"aoa": aoa, "ok": False, "error": f"exception: {e}"}
            import traceback; traceback.print_exc()
        all_results.append(r)
        # Guardado parcial por si algo crashea
        with open(RESULTS_FILE, "w") as f:
            json.dump({"results": all_results}, f, indent=2)

    print_report(all_results)
    log(f"✅ Validación polar completa — {int(time.time()-t0_total)}s total")
