"""
ETAPA 4 — Sensibilidad de Malla
Perfil: NACA 2412 | AoA=5° | Re=1M | k-Omega SST | Estacionario
Niveles: Gruesa → Media → Fina
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
RESULTS_CSV = os.path.join(BASE_DIR, "etapa4_resultados.csv")

from core.openfoam_setup import OpenFoamSetup
from core.solver import SolverRunner


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")


def extract_coefficients(case_dir):
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
    parts = lines[-1].split()
    if len(parts) >= 8:
        return {"Cd": float(parts[1]), "Cl": float(parts[4]), "Cm": float(parts[7])}
    return None


def count_mesh_cells(msh_path):
    """Cuenta nodos en el .msh para estimar tamaño de malla."""
    try:
        nodes = 0
        with open(msh_path) as f:
            for line in f:
                if line.strip().startswith("$Nodes"):
                    next(f)  # saltar la línea de count
                    nodes_line = next(f).strip()
                    nodes = int(nodes_line.split()[-1])
                    break
        return nodes
    except Exception:
        return -1


def run_case(label, mesh_size_min, mesh_size_max, mesh_num_layers, mesh_nb_points,
             naca="2412", chord=1.0, aoa=5.0,
             u_inlet=15.0, reynolds=1_000_000,
             turbulence="k-Omega SST (RAS)", transient=False):
    sep = "=" * 64
    print(f"\n{sep}")
    print(f"  CASO: {label}")
    print(f"  size_min={mesh_size_min}c  size_max={mesh_size_max}c  "
          f"BL_layers={mesh_num_layers}  pts={mesh_nb_points}")
    print(sep)

    result = {
        "label": label, "naca": naca, "aoa": aoa,
        "u_inlet": u_inlet, "reynolds": reynolds,
        "turbulence": turbulence, "transient": transient,
        "mesh_size_min": mesh_size_min, "mesh_num_layers": mesh_num_layers,
        "mesh_nodes": None,
        "Cl": None, "Cd": None, "Cm": None,
        "status": "PENDING", "error": "", "wall_time_s": 0,
    }
    t_start = time.time()

    try:
        # 1 — Malla
        print("\n  [1/4] Generando malla...")
        mesh_params = {
            "naca": naca, "chord": chord, "aoa": aoa,
            "mesh_size_min": mesh_size_min, "mesh_size_max": mesh_size_max,
            "bl_dist_min": 0.001, "mesh_num_layers": mesh_num_layers,
            "mesh_growth_rate": 1.15, "mesh_nb_points": mesh_nb_points,
            "wake_length": 5.0, "profile_type": "NACA",
        }
        json_path = os.path.join(BASE_DIR, "temp_params_mesh.json")
        msh_path  = os.path.join(CASE_DIR, f"perfil_{naca}.msh")
        os.makedirs(CASE_DIR, exist_ok=True)
        with open(json_path, "w") as f:
            json.dump(mesh_params, f)

        r = subprocess.run(
            [PYTHON, "-m", "core.mesh_script", json_path, msh_path],
            capture_output=True, text=True, cwd=BASE_DIR, timeout=300
        )
        if r.returncode != 0:
            raise RuntimeError(f"mesh_script falló ({r.returncode}): {r.stderr[-300:]}")

        # Estimar tamaño de malla desde stdout
        for line in r.stdout.splitlines():
            if "nodes" in line.lower() and "elements" in line.lower():
                log(f"📐 {line.strip()}")
                break

        log("✅ Malla OK")

        # 2 — Setup
        print("\n  [2/4] Configurando caso OpenFOAM...")
        setup = OpenFoamSetup(case_dir=CASE_DIR)
        setup.create_case(
            u_inlet=u_inlet, chord=chord, transient=transient,
            tolerance="1e-5", turbulence=turbulence, reynolds=reynolds,
        )
        log("✅ Setup OK")

        # 3 — gmshToFoam + potentialFoam
        print("\n  [3/4] Convirtiendo malla + inicializando...")
        solver = SolverRunner(case_dir=CASE_DIR, native=True)
        solver.run_gmshToFoam(msh_path, log_callback=log)

        done_pot = {"rc": None}
        solver.run_potentialFoam(log_callback=log,
                                 done_callback=lambda rc: done_pot.update({"rc": rc}))
        t0 = time.time()
        while done_pot["rc"] is None and time.time()-t0 < 120:
            time.sleep(1)

        # 4 — simpleFoam
        print("\n  [4/4] Ejecutando simpleFoam...")
        done_sol = {"rc": None}
        solver.run_solver(
            algo_name="simpleFoam", log_callback=log,
            done_callback=lambda rc: done_sol.update({"rc": rc}),
        )
        t0 = time.time()
        while done_sol["rc"] is None and time.time()-t0 < 1800:
            time.sleep(5)
        if done_sol["rc"] is None:
            solver.stop()
            raise TimeoutError("Solver superó 1800 s")
        if done_sol["rc"] != 0:
            raise RuntimeError(f"Solver terminó con código {done_sol['rc']}")

        coeffs = extract_coefficients(CASE_DIR)
        if coeffs:
            result.update({**coeffs, "status": "OK"})
            ld = coeffs['Cl'] / coeffs['Cd'] if coeffs['Cd'] else float('nan')
            print(f"\n  ✅ Cl={result['Cl']:.4f}  Cd={result['Cd']:.5f}  "
                  f"Cm={result['Cm']:.4f}  L/D={ld:.2f}")
        else:
            result["status"] = "NO_RESULTS"

    except Exception as e:
        result["status"] = "ERROR"
        result["error"] = str(e)
        print(f"\n  ❌ ERROR: {e}")

    result["wall_time_s"] = round(time.time() - t_start, 1)
    return result


def save_csv(results, path):
    fields = ["label","naca","aoa","u_inlet","reynolds","turbulence",
              "transient","mesh_size_min","mesh_num_layers","mesh_nodes",
              "Cl","Cd","Cm","status","error","wall_time_s"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
    print(f"\n📄 Resultados → {path}")


# ── Tres niveles de malla ────────────────────────────────────────────────────
# Gruesa  : mesh_size_min=0.05c, 5  capas BL, 80  pts perfil
# Media   : mesh_size_min=0.02c, 10 capas BL, 150 pts perfil  (referencia)
# Fina    : mesh_size_min=0.008c, 20 capas BL, 250 pts perfil
STAGE4_CASES = [
    {
        "label": "Gruesa",
        "mesh_size_min": 0.05, "mesh_size_max": 1.5,
        "mesh_num_layers": 5,  "mesh_nb_points": 80,
    },
    {
        "label": "Media",
        "mesh_size_min": 0.02, "mesh_size_max": 1.0,
        "mesh_num_layers": 10, "mesh_nb_points": 150,
    },
    {
        "label": "Fina",
        "mesh_size_min": 0.008, "mesh_size_max": 0.8,
        "mesh_num_layers": 20,  "mesh_nb_points": 250,
    },
]

if __name__ == "__main__":
    print("\n" + "█"*64)
    print(" ETAPA 4 — Sensibilidad de Malla")
    print(" Perfil: NACA 2412  |  AoA=5°  |  Re=1M  |  k-ω SST")
    print("█"*64)

    results = []
    for case in STAGE4_CASES:
        r = run_case(**case)
        results.append(r)
        save_csv(results, RESULTS_CSV)

    ok  = [r for r in results if r["status"] == "OK"]
    err = [r for r in results if r["status"] != "OK"]

    print(f"\n{'═'*64}")
    print(f" RESUMEN ETAPA 4: {len(ok)}/{len(results)} casos exitosos")
    if ok:
        print(f"\n  {'Malla':<8}  {'size_min':>8}  {'BL':>4}  "
              f"{'Cl':>8}  {'Cd':>10}  {'Cm':>9}  {'L/D':>7}  {'t(s)':>6}")
        print(f"  {'-'*8}  {'-'*8}  {'-'*4}  "
              f"{'-'*8}  {'-'*10}  {'-'*9}  {'-'*7}  {'-'*6}")
        for r in ok:
            ld = r['Cl']/r['Cd'] if r['Cd'] else float('nan')
            print(f"  {r['label']:<8}  {r['mesh_size_min']:>8.3f}c  "
                  f"{r['mesh_num_layers']:>4}  "
                  f"{r['Cl']:>8.4f}  {r['Cd']:>10.5f}  "
                  f"{r['Cm']:>9.4f}  {ld:>7.2f}  {r['wall_time_s']:>6.1f}")
    if err:
        print("\n  Casos fallidos:")
        for r in err:
            print(f"  ❌ {r['label']}: {r['status']} — {r['error'][:80]}")
    print(f"{'═'*64}\n")
