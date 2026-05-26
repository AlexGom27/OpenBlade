"""Caso piloto rápido: AoA=5°, NACA 2412 — verifica que el pipeline funciona."""
import sys, os, json, time, subprocess
sys.path.insert(0, os.path.dirname(__file__))

OF_BIN = "/Volumes/OpenFOAM-v2512/platforms/darwin64ClangDPInt32Opt/bin"
OF_LIB = "/Volumes/OpenFOAM-v2512/platforms/darwin64ClangDPInt32Opt/lib"
os.environ["PATH"] = OF_BIN + os.pathsep + os.environ.get("PATH", "")
os.environ["DYLD_LIBRARY_PATH"] = OF_LIB + os.pathsep + os.environ.get("DYLD_LIBRARY_PATH", "")
os.environ["WM_PROJECT_DIR"] = "/Volumes/OpenFOAM-v2512"

PYTHON = sys.executable
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CASE_DIR = os.path.join(BASE_DIR, "openfoam_case")

from core.openfoam_setup import OpenFoamSetup
from core.solver import SolverRunner

def log(msg): print(f"  {msg}")

def extract_coefficients(case_dir):
    coeff_dir = os.path.join(case_dir, "postProcessing", "forceCoeffs")
    if not os.path.exists(coeff_dir): return None
    time_dirs = sorted([d for d in os.listdir(coeff_dir)
                        if os.path.isdir(os.path.join(coeff_dir, d))],
                       key=lambda x: float(x) if x.replace('.','').isdigit() else 0)
    if not time_dirs: return None
    coeff_file = os.path.join(coeff_dir, time_dirs[-1], "coefficient.dat")
    if not os.path.exists(coeff_file):
        coeff_file = os.path.join(coeff_dir, time_dirs[-1], "forceCoeffs.dat")
    if not os.path.exists(coeff_file): return None
    with open(coeff_file) as f:
        lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]
    if lines:
        parts = lines[-1].split()
        if len(parts) >= 4:
            return {"Cm": float(parts[1]), "Cd": float(parts[2]), "Cl": float(parts[3])}
    return None

print("="*60)
print("PILOTO: NACA 2412, AoA=5°, Re=1M, k-Omega SST, Estacionario")
print("="*60)

naca    = "2412"
chord   = 1.0
aoa     = 5.0
u_inlet = 15.0
reynolds = 1_000_000

# ── 1. Generar malla via mesh_script.py ──────────────────────────────────────
print("\n[1/5] Generando malla (mesh_script.py)...")
mesh_params = {
    "naca": naca, "chord": chord, "aoa": aoa,
    "mesh_size_min": 0.02, "mesh_size_max": 1.0,
    "bl_dist_min": 0.001, "mesh_num_layers": 5, "mesh_growth_rate": 1.15,
    "mesh_nb_points": 100, "wake_length": 5.0, "profile_type": "NACA"
}
json_path = os.path.join(BASE_DIR, "temp_params_mesh.json")
msh_path  = os.path.join(CASE_DIR, f"perfil_{naca}.msh")
os.makedirs(CASE_DIR, exist_ok=True)

with open(json_path, "w") as f:
    json.dump(mesh_params, f)

result = subprocess.run(
    [PYTHON, "-m", "core.mesh_script", json_path, msh_path],
    capture_output=True, text=True, cwd=BASE_DIR
)
print(result.stdout[-2000:] if result.stdout else "(sin salida)")
if result.returncode != 0:
    print(f"STDERR: {result.stderr[-1000:]}")
    sys.exit(f"❌ mesh_script falló con código {result.returncode}")
print(f"  ✅ Malla OK → {msh_path}")

# ── 2. Setup OpenFOAM ────────────────────────────────────────────────────────
print("\n[2/5] Configurando caso OpenFOAM...")
setup = OpenFoamSetup(case_dir=CASE_DIR)
setup.create_case(u_inlet=u_inlet, chord=chord, transient=False,
                  tolerance="1e-5", turbulence="k-Omega SST (RAS)",
                  reynolds=reynolds)
print("  ✅ Setup OK")

# ── 3. gmshToFoam ────────────────────────────────────────────────────────────
print("\n[3/5] Convirtiendo malla (gmshToFoam)...")
solver = SolverRunner(case_dir=CASE_DIR, native=True)
solver.run_gmshToFoam(msh_path, log_callback=log)
print("  ✅ gmshToFoam OK")

# ── 4. potentialFoam ─────────────────────────────────────────────────────────
print("\n[4/5] Inicializando campo potencial (potentialFoam)...")
done = {"rc": None}
solver.run_potentialFoam(log_callback=log, done_callback=lambda rc: done.update({"rc": rc}))
t0 = time.time()
while done["rc"] is None and time.time()-t0 < 120: time.sleep(1)
log(f"potentialFoam → código {done['rc']}")

# ── 5. simpleFoam ────────────────────────────────────────────────────────────
print("\n[5/5] Ejecutando simpleFoam...")
done2 = {"rc": None}
solver.run_solver(algo_name="simpleFoam", log_callback=log,
                  done_callback=lambda rc: done2.update({"rc": rc}))
t0 = time.time()
while done2["rc"] is None and time.time()-t0 < 600: time.sleep(5)
print(f"\n  Solver terminó con código: {done2['rc']}")

# ── Resultados ───────────────────────────────────────────────────────────────
coeffs = extract_coefficients(CASE_DIR)
if coeffs:
    print(f"\n✅ RESULTADO PILOTO:")
    print(f"   Cl = {coeffs['Cl']:.4f}")
    print(f"   Cd = {coeffs['Cd']:.4f}")
    print(f"   Cm = {coeffs['Cm']:.4f}")
else:
    print("\n⚠️ No se encontraron coeficientes en postProcessing")
    # Mostrar qué hay en postProcessing para debug
    pp = os.path.join(CASE_DIR, "postProcessing")
    if os.path.exists(pp):
        for root, dirs, files in os.walk(pp):
            for f in files:
                print(f"  {os.path.join(root, f)}")
    else:
        print("  postProcessing no existe")
