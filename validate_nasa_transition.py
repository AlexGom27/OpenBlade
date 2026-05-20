"""Validación con modelo de transición k-ω SST-LM (γ-Reθ) — equivalente CFD a Free Transition de NASA."""
import os, sys, time, json, subprocess, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.openfoam_setup import OpenFoamSetup
from core.solver import SolverRunner

HERE = os.path.dirname(os.path.abspath(__file__))
CASE_DIR = os.path.join(HERE, "openfoam_case")
RESULTS = os.path.join(HERE, "results_nasa_transition.json")
MSH = os.path.join(CASE_DIR, "validacion_nasa.msh")
PJ = os.path.join(HERE, "temp_params_validate.json")

MESH = {
    "naca": "0012", "chord": 1.0, "profile_type": "NACA 4-digit",
    "mesh_size_min": 0.01, "mesh_size_max": 0.5,
    "bl_dist_min": 0.0005, "mesh_growth_rate": 1.15,
    "mesh_num_layers": 25, "mesh_nb_points": 300, "wake_length": 5.0,
}

AOA_LIST = [0.0, 4.0, 8.0, 12.0]


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def run_aoa(aoa):
    log(f"\n══ α = {aoa:+.1f}° (transición) ══")
    for item in os.listdir(CASE_DIR):
        try:
            float(item)
            if item != "0": shutil.rmtree(os.path.join(CASE_DIR, item), ignore_errors=True)
        except (ValueError, FileNotFoundError): pass
    shutil.rmtree(os.path.join(CASE_DIR, "constant", "polyMesh"), ignore_errors=True)
    shutil.rmtree(os.path.join(CASE_DIR, "postProcessing"), ignore_errors=True)

    p = {**MESH, "aoa": aoa}
    with open(PJ, "w") as f: json.dump(p, f)
    t0 = time.time()
    r = subprocess.run([sys.executable, os.path.join(HERE, "core", "mesh_script.py"), PJ, MSH],
                       capture_output=True, text=True, cwd=HERE, timeout=600)
    if r.returncode != 0:
        log(f"  ❌ Malla falló")
        return {"aoa": aoa, "ok": False}
    used_planb = "PLAN B" in r.stdout
    log(f"  Malla en {time.time()-t0:.1f}s ({os.path.getsize(MSH)/1e6:.1f} MB) [{'PLAN B' if used_planb else 'PLAN A'}]")

    setup = OpenFoamSetup(case_dir=CASE_DIR)
    # IMPORTANTE: modelo de transición = "k-Omega SST-LM"
    setup.create_case(u_inlet=15.0, p_outlet=0.0, chord=1.0, transient=False,
                       tolerance="1e-5", turbulence="k-Omega SST-LM (RAS)",
                       reynolds=2_000_000.0)

    runner = SolverRunner(case_dir=CASE_DIR)
    runner.run_gmshToFoam(MSH, log_callback=lambda m: None)
    done = {"ok": False}
    runner.run_potentialFoam(log_callback=lambda m: None,
                              done_callback=lambda c: done.update({"ok": True}))
    t0 = time.time()
    while not done["ok"] and time.time() - t0 < 120: time.sleep(1)

    forces = {"Cd": None, "Cl": None, "Cm": None}
    sd = {"ok": False}
    runner.run_solver(algo_name="simpleFoam", log_callback=lambda m: None,
                      force_callback=lambda n, v: forces.__setitem__(n, v),
                      residual_callback=lambda f, v, t: None,
                      done_callback=lambda c: sd.update({"ok": True}))
    t0 = time.time()
    while not sd["ok"] and time.time() - t0 < 900: time.sleep(2)
    log(f"  Solver en {int(time.time()-t0)}s | Cd={forces['Cd']} Cl={forces['Cl']} Cm={forces['Cm']}")

    return {"aoa": aoa, "ok": True,
            "Cl": float(forces["Cl"]) if forces["Cl"] else None,
            "Cd": float(forces["Cd"]) if forces["Cd"] else None,
            "Cm": float(forces["Cm"]) if forces["Cm"] else None}


if __name__ == "__main__":
    t0 = time.time()
    results = []
    for a in AOA_LIST:
        try: results.append(run_aoa(a))
        except Exception as e:
            results.append({"aoa": a, "ok": False, "error": str(e)})
            import traceback; traceback.print_exc()
        with open(RESULTS, "w") as f: json.dump({"results": results}, f, indent=2)
    log(f"✅ Transición completo — {int(time.time()-t0)}s")
