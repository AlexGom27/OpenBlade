"""
ETAPA 1 — Barrido de Ángulo de Ataque
Perfil: NACA 2412 | Cuerda: 1.0 m | Re=1M | k-Omega SST | Estacionario
Parámetros variables: AoA ∈ {-4, 0, 5, 10, 15, 20}°
"""
import sys, os, json, time, subprocess, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OF_BIN = "/Volumes/OpenFOAM-v2512/platforms/darwin64ClangDPInt32Opt/bin"
OF_LIB = "/Volumes/OpenFOAM-v2512/platforms/darwin64ClangDPInt32Opt/lib"
os.environ["PATH"] = OF_BIN + os.pathsep + os.environ.get("PATH", "")
os.environ["DYLD_LIBRARY_PATH"] = OF_LIB + os.pathsep + os.environ.get("DYLD_LIBRARY_PATH", "")
os.environ["WM_PROJECT_DIR"] = "/Volumes/OpenFOAM-v2512"

PYTHON   = sys.executable
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CASE_DIR = os.path.join(BASE_DIR, "openfoam_case")
RESULTS_CSV = os.path.join(BASE_DIR, "etapa1_resultados.csv")

from core.openfoam_setup import OpenFoamSetup
from core.solver import SolverRunner


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")


def extract_coefficients(case_dir):
    """Lee Cl, Cd, CmPitch del último paso de tiempo en postProcessing."""
    coeff_dir = os.path.join(case_dir, "postProcessing", "forceCoeffs")
    if not os.path.exists(coeff_dir):
        return None
    time_dirs = sorted(
        [d for d in os.listdir(coeff_dir) if os.path.isdir(os.path.join(coeff_dir, d))],
        key=lambda x: float(x) if x.replace('.','').isdigit() else 0
    )
    if not time_dirs:
        return None
    for fname in ("coefficient.dat", "forceCoeffs.dat"):
        coeff_file = os.path.join(coeff_dir, time_dirs[-1], fname)
        if os.path.exists(coeff_file):
            break
    else:
        return None

    with open(coeff_file) as f:
        lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]
    if not lines:
        return None

    # Formato OpenFOAM v2512:
    # Time  Cd  Cd(f)  Cd(r)  Cl  Cl(f)  Cl(r)  CmPitch  CmRoll  CmYaw ...
    parts = lines[-1].split()
    if len(parts) >= 8:
        return {
            "Cd":  float(parts[1]),   # Cd total
            "Cl":  float(parts[4]),   # Cl total
            "Cm":  float(parts[7]),   # CmPitch
        }
    return None


def run_case(label, aoa,
             naca="2412", chord=1.0, u_inlet=15.0, reynolds=1_000_000,
             turbulence="k-Omega SST (RAS)", transient=False,
             mesh_size_min=0.02, mesh_size_max=1.0):
    """Ejecuta una simulación completa y devuelve dict de resultados."""
    sep = "=" * 64
    print(f"\n{sep}")
    print(f"  CASO: {label}  |  NACA {naca}  |  AoA = {aoa}°")
    print(f"  Re = {reynolds:.0f}  |  Turb = {turbulence}")
    print(sep)

    result = {
        "label": label, "naca": naca, "aoa": aoa,
        "u_inlet": u_inlet, "reynolds": reynolds,
        "turbulence": turbulence, "transient": transient,
        "Cl": None, "Cd": None, "Cm": None,
        "status": "PENDING", "error": "",
        "wall_time_s": 0,
    }
    t_start = time.time()

    try:
        # 1 — Generar malla
        print("\n  [1/4] Generando malla...")
        mesh_params = {
            "naca": naca, "chord": chord, "aoa": aoa,
            "mesh_size_min": mesh_size_min, "mesh_size_max": mesh_size_max,
            "bl_dist_min": 0.001, "mesh_num_layers": 5, "mesh_growth_rate": 1.15,
            "mesh_nb_points": 100, "wake_length": 5.0, "profile_type": "NACA",
        }
        json_path = os.path.join(BASE_DIR, "temp_params_mesh.json")
        msh_path  = os.path.join(CASE_DIR, f"perfil_{naca}.msh")
        os.makedirs(CASE_DIR, exist_ok=True)
        with open(json_path, "w") as f:
            json.dump(mesh_params, f)

        r = subprocess.run(
            [PYTHON, "-m", "core.mesh_script", json_path, msh_path],
            capture_output=True, text=True, cwd=BASE_DIR, timeout=120
        )
        if r.returncode != 0:
            raise RuntimeError(f"mesh_script falló (código {r.returncode}): {r.stderr[-300:]}")
        log("✅ Malla OK")

        # 2 — Setup OpenFOAM
        print("\n  [2/4] Configurando caso OpenFOAM...")
        setup = OpenFoamSetup(case_dir=CASE_DIR)
        setup.create_case(
            u_inlet=u_inlet, chord=chord, transient=transient,
            tolerance="1e-5", turbulence=turbulence, reynolds=reynolds,
        )
        log("✅ Setup OK")

        # 3 — gmshToFoam
        print("\n  [3/4] Convirtiendo malla + inicializando solver...")
        solver = SolverRunner(case_dir=CASE_DIR, native=True)
        solver.run_gmshToFoam(msh_path, log_callback=log)

        done_pot = {"rc": None}
        solver.run_potentialFoam(log_callback=log,
                                 done_callback=lambda rc: done_pot.update({"rc": rc}))
        t0 = time.time()
        while done_pot["rc"] is None and time.time()-t0 < 120:
            time.sleep(1)

        # 4 — Solver
        algo = "pimpleFoam" if transient else "simpleFoam"
        print(f"\n  [4/4] Ejecutando {algo}...")
        done_sol = {"rc": None}
        solver.run_solver(
            algo_name=algo,
            log_callback=log,
            done_callback=lambda rc: done_sol.update({"rc": rc}),
        )
        t0 = time.time()
        while done_sol["rc"] is None and time.time()-t0 < 900:
            time.sleep(5)
        if done_sol["rc"] is None:
            solver.stop()
            raise TimeoutError("Solver superó 900 s")
        if done_sol["rc"] != 0:
            raise RuntimeError(f"Solver terminó con código {done_sol['rc']}")

        # Extraer coeficientes
        coeffs = extract_coefficients(CASE_DIR)
        if coeffs:
            result.update({**coeffs, "status": "OK"})
            print(f"\n  ✅ Cl={result['Cl']:.4f}  Cd={result['Cd']:.5f}  Cm={result['Cm']:.4f}")
        else:
            result["status"] = "NO_RESULTS"
            print("\n  ⚠️  No se encontraron coeficientes en postProcessing")

    except Exception as e:
        result["status"] = "ERROR"
        result["error"] = str(e)
        print(f"\n  ❌ ERROR: {e}")

    result["wall_time_s"] = round(time.time() - t_start, 1)
    return result


def save_csv(results, path):
    fields = ["label","naca","aoa","u_inlet","reynolds","turbulence",
              "transient","Cl","Cd","Cm","status","error","wall_time_s"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
    print(f"\n📄 Resultados guardados en: {path}")


# ══════════════════════════════════════════════════════════════════════════════
STAGE1_CASES = [
    {"label": "AoA_-4",  "aoa": -4.0},
    {"label": "AoA_0",   "aoa":  0.0},
    {"label": "AoA_5",   "aoa":  5.0},
    {"label": "AoA_10",  "aoa": 10.0},
    {"label": "AoA_15",  "aoa": 15.0},
    {"label": "AoA_20",  "aoa": 20.0},
]

if __name__ == "__main__":
    print("\n" + "█"*64)
    print(" ETAPA 1 — Barrido de Ángulo de Ataque")
    print(" Perfil: NACA 2412  |  Re = 1 000 000  |  k-Omega SST")
    print("█"*64)

    results = []
    for case in STAGE1_CASES:
        r = run_case(**case)
        results.append(r)
        # Guardar parcialmente tras cada caso
        save_csv(results, RESULTS_CSV)

    # Resumen final
    ok  = [r for r in results if r["status"] == "OK"]
    err = [r for r in results if r["status"] != "OK"]
    print(f"\n{'═'*64}")
    print(f" RESUMEN ETAPA 1: {len(ok)}/{len(results)} casos exitosos")
    if ok:
        print(f"\n  {'AoA':>6}  {'Cl':>8}  {'Cd':>10}  {'Cm':>9}  {'L/D':>8}")
        print(f"  {'-'*6}  {'-'*8}  {'-'*10}  {'-'*9}  {'-'*8}")
        for r in ok:
            ld = r['Cl']/r['Cd'] if r['Cd'] else float('nan')
            print(f"  {r['aoa']:>6.1f}°  {r['Cl']:>8.4f}  {r['Cd']:>10.5f}  "
                  f"{r['Cm']:>9.4f}  {ld:>8.2f}")
    if err:
        print("\n  Casos fallidos:")
        for r in err:
            print(f"  ❌ {r['label']}: {r['status']} — {r['error'][:80]}")
    print(f"{'═'*64}\n")
