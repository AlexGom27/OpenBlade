"""
Script de pruebas headless para OpenBlade — sin GUI.
Ejecuta simulaciones completas (geometría → malla → OpenFOAM → resultados)
y registra Cl, Cd, errores en un CSV.
"""
import sys, os, json, csv, time, shutil
sys.path.insert(0, os.path.dirname(__file__))

# ── Añadir OpenFOAM al PATH ──────────────────────────────────────────────────
OF_BIN = "/Volumes/OpenFOAM-v2512/platforms/darwin64ClangDPInt32Opt/bin"
OF_LIB = "/Volumes/OpenFOAM-v2512/platforms/darwin64ClangDPInt32Opt/lib"
os.environ["PATH"] = OF_BIN + os.pathsep + os.environ.get("PATH", "")
os.environ["LD_LIBRARY_PATH"] = OF_LIB + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")
os.environ["DYLD_LIBRARY_PATH"] = OF_LIB + os.pathsep + os.environ.get("DYLD_LIBRARY_PATH", "")
os.environ["WM_PROJECT_DIR"] = "/Volumes/OpenFOAM-v2512"
# ────────────────────────────────────────────────────────────────────────────

import gmsh
from core.geometry import NacaGeometry
from core.meshing import NacaMesher
from core.openfoam_setup import OpenFoamSetup
from core.solver import SolverRunner
def extract_force_coefficients(case_dir):
    """Extrae Cl, Cd, Cm del directorio postProcessing de OpenFOAM."""
    try:
        coeff_dir = os.path.join(case_dir, "postProcessing", "forceCoeffs")
        if not os.path.exists(coeff_dir):
            return None
        time_dirs = sorted(
            [d for d in os.listdir(coeff_dir) if os.path.isdir(os.path.join(coeff_dir, d))],
            key=lambda x: float(x) if x.replace('.','').isdigit() else 0
        )
        if not time_dirs:
            return None
        coeff_file = os.path.join(coeff_dir, time_dirs[-1], "coefficient.dat")
        if not os.path.exists(coeff_file):
            coeff_file = os.path.join(coeff_dir, time_dirs[-1], "forceCoeffs.dat")
        if not os.path.exists(coeff_file):
            return None
        with open(coeff_file) as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]
        if lines:
            parts = lines[-1].split()
            if len(parts) >= 4:
                return {"Cm": float(parts[1]), "Cd": float(parts[2]), "Cl": float(parts[3])}
    except Exception as e:
        print(f"  ⚠️ Error leyendo postProcessing: {e}")
    return None

CASE_DIR = os.path.join(os.path.dirname(__file__), "openfoam_case")
RESULTS_FILE = os.path.join(os.path.dirname(__file__), "test_results.csv")

def log(msg):
    print(f"  {msg}")

def run_case(label, naca="2412", chord=1.0, aoa=0.0,
             u_inlet=15.0, reynolds=1_000_000,
             turbulence="k-Omega SST (RAS)", transient=False,
             mesh_size_min=0.005, mesh_size_max=0.1,
             mesh_num_layers=15, mesh_growth_rate=1.2):
    """Ejecuta una simulación completa y devuelve dict con resultados."""
    print(f"\n{'='*60}")
    print(f"CASO: {label}")
    print(f"  NACA={naca}, AoA={aoa}°, Re={reynolds:.0f}, turb={turbulence}")
    print(f"{'='*60}")
    result = {"label": label, "naca": naca, "aoa": aoa,
              "u_inlet": u_inlet, "reynolds": reynolds,
              "turbulence": turbulence, "transient": transient,
              "Cl": None, "Cd": None, "Cm": None,
              "status": "PENDING", "error": ""}

    try:
        # ── 1. Geometría ──────────────────────────────────────────────────
        log("Generando geometría...")
        geom = NacaGeometry(naca_code=naca, chord=chord, aoa=aoa)
        gmsh.initialize()
        gmsh.option.setNumber("General.Verbosity", 0)
        gmsh.model.add("airfoil")
        geom.build_geometry()

        # ── 2. Mallado ────────────────────────────────────────────────────
        log("Generando malla...")
        mesh_params = {
            "chord": chord,
            "mesh_size_min": mesh_size_min,
            "mesh_size_max": mesh_size_max,
            "bl_dist_min": 0.001,
            "mesh_num_layers": mesh_num_layers,
            "mesh_growth_rate": mesh_growth_rate,
        }
        mesher = NacaMesher(mesh_params)
        mesher.generate_mesh()
        msh_path = os.path.join(CASE_DIR, "airfoil.msh")
        os.makedirs(CASE_DIR, exist_ok=True)
        gmsh.write(msh_path)
        gmsh.finalize()
        log(f"Malla guardada: {msh_path}")

        # ── 3. Setup OpenFOAM ─────────────────────────────────────────────
        log("Configurando caso OpenFOAM...")
        setup = OpenFoamSetup(case_dir=CASE_DIR)
        setup.create_case(
            u_inlet=u_inlet, chord=chord, transient=transient,
            tolerance="1e-5", turbulence=turbulence,
            reynolds=reynolds,
        )

        # ── 4. Convertir malla ────────────────────────────────────────────
        log("Convirtiendo malla (gmshToFoam)...")
        solver = SolverRunner(case_dir=CASE_DIR, native=True)
        solver.run_gmshToFoam(msh_path, log_callback=log)

        # ── 5. potentialFoam (inicialización) ─────────────────────────────
        log("Inicializando campo potencial...")
        done_event = {"rc": None}
        def on_pot_done(rc): done_event["rc"] = rc
        solver.run_potentialFoam(log_callback=log, done_callback=on_pot_done)
        t0 = time.time()
        while done_event["rc"] is None and time.time() - t0 < 120:
            time.sleep(1)
        if done_event["rc"] not in (0, None):
            log(f"⚠️ potentialFoam terminó con código {done_event['rc']} — continuando")

        # ── 6. Solver ─────────────────────────────────────────────────────
        algo = "pimpleFoam" if transient else "simpleFoam"
        log(f"Ejecutando {algo}...")
        done_event2 = {"rc": None}
        def on_done(rc): done_event2["rc"] = rc
        solver.run_solver(algo_name=algo, log_callback=log, done_callback=on_done)
        t0 = time.time()
        timeout = 600  # 10 min max por caso
        while done_event2["rc"] is None and time.time() - t0 < timeout:
            time.sleep(5)
        if done_event2["rc"] is None:
            solver.stop()
            raise TimeoutError(f"Solver excedió {timeout}s")

        rc = done_event2["rc"]
        log(f"Solver terminó con código {rc}")
        if rc != 0:
            raise RuntimeError(f"Solver falló con código {rc}")

        # ── 7. Postprocesamiento ──────────────────────────────────────────
        log("Leyendo coeficientes...")
        coeffs = extract_force_coefficients(CASE_DIR)
        if coeffs:
            result.update({"Cl": coeffs.get("Cl"), "Cd": coeffs.get("Cd"),
                           "Cm": coeffs.get("Cm"), "status": "OK"})
            log(f"✅ Cl={result['Cl']:.4f}  Cd={result['Cd']:.4f}  Cm={result.get('Cm', 'N/A')}")
        else:
            result["status"] = "NO_RESULTS"
            log("⚠️ No se encontraron coeficientes en postProcessing")

    except Exception as e:
        result["status"] = "ERROR"
        result["error"] = str(e)
        log(f"❌ ERROR: {e}")
        try:
            gmsh.finalize()
        except Exception:
            pass

    return result


def save_results(results):
    fields = ["label", "naca", "aoa", "u_inlet", "reynolds",
              "turbulence", "transient", "Cl", "Cd", "Cm", "status", "error"]
    with open(RESULTS_FILE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
    print(f"\n📄 Resultados guardados en: {RESULTS_FILE}")


# ════════════════════════════════════════════════════════════════════════════
# ETAPA 1 — Barrido de Ángulo de Ataque (AoA)
# Perfil: NACA 2412 | Re=1M | k-Omega SST | Estacionario
# ════════════════════════════════════════════════════════════════════════════
STAGE_1_CASES = [
    {"label": "AoA_-4",  "aoa": -4.0},
    {"label": "AoA_0",   "aoa":  0.0},
    {"label": "AoA_5",   "aoa":  5.0},
    {"label": "AoA_10",  "aoa": 10.0},
    {"label": "AoA_15",  "aoa": 15.0},
    {"label": "AoA_20",  "aoa": 20.0},
]

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, default=1, help="Etapa a ejecutar (1-5)")
    args = parser.parse_args()

    results = []

    if args.stage == 1:
        print("\n🔬 ETAPA 1: Barrido de Ángulo de Ataque — NACA 2412, Re=1M, k-ω SST")
        for c in STAGE_1_CASES:
            r = run_case(**c, naca="2412", reynolds=1_000_000,
                         turbulence="k-Omega SST (RAS)", transient=False)
            results.append(r)

    save_results(results)
    errors = [r for r in results if r["status"] != "OK"]
    print(f"\n{'='*60}")
    print(f"RESUMEN ETAPA {args.stage}: {len(results)-len(errors)}/{len(results)} casos exitosos")
    if errors:
        print("Casos con problemas:")
        for e in errors:
            print(f"  ❌ {e['label']}: {e['status']} — {e['error'][:80]}")
    print(f"{'='*60}\n")
