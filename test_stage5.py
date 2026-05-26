"""
ETAPA 5 — Régimen Estacionario vs Transitorio
Perfil: NACA 2412 | Cuerda: 1.0 m | AoA=10° | Re=1M | k-Omega SST
Casos: simpleFoam (estacionario) vs pimpleFoam (transitorio)
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
RESULTS_CSV = os.path.join(BASE_DIR, "etapa5_resultados.csv")

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
    # Formato: Time  Cd  Cd(f)  Cd(r)  Cl  Cl(f)  Cl(r)  CmPitch ...
    parts = lines[-1].split()
    if len(parts) >= 8:
        return {"Cd": float(parts[1]), "Cl": float(parts[4]), "Cm": float(parts[7])}
    return None


def run_case(label, transient,
             naca="2412", chord=1.0, aoa=10.0,
             u_inlet=15.0, reynolds=1_000_000,
             turbulence="k-Omega SST (RAS)",
             delta_t="1e-3", end_time="0.5",
             write_interval="0.01", max_co=2.0):

    algo = "pimpleFoam" if transient else "simpleFoam"
    sep = "=" * 64
    print(f"\n{sep}")
    print(f"  CASO: {label}  →  {algo}")
    print(f"  NACA {naca}  |  AoA={aoa}°  |  Re={reynolds:,.0f}  |  Turb={turbulence}")
    if transient:
        print(f"  Δt={delta_t}  |  t_end={end_time}s  |  MaxCo={max_co}")
    print(sep)

    result = {
        "label": label, "naca": naca, "aoa": aoa,
        "u_inlet": u_inlet, "reynolds": reynolds,
        "turbulence": turbulence, "transient": transient,
        "solver": algo,
        "Cl": None, "Cd": None, "Cm": None,
        "status": "PENDING", "error": "", "wall_time_s": 0,
    }
    t_start = time.time()

    try:
        # 1 — Malla (misma geometría para ambos casos)
        print("\n  [1/4] Generando malla...")
        mesh_params = {
            "naca": naca, "chord": chord, "aoa": aoa,
            "mesh_size_min": 0.02, "mesh_size_max": 1.0,
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
            raise RuntimeError(f"mesh_script falló ({r.returncode}): {r.stderr[-300:]}")
        log("✅ Malla OK")

        # 2 — Setup OpenFOAM
        print("\n  [2/4] Configurando caso OpenFOAM...")
        setup = OpenFoamSetup(case_dir=CASE_DIR)
        # Para transitorio usamos tolerancia más relajada (más rápido)
        tol = "1e-3" if transient else "1e-5"
        setup.create_case(
            u_inlet=u_inlet, chord=chord, transient=transient,
            tolerance=tol, turbulence=turbulence, reynolds=reynolds,
            delta_t=delta_t, end_time=end_time,
            write_interval=write_interval, max_co=max_co,
        )

        # Para transitorio: reducir nOuterCorrectors 20→3 para acelerar
        if transient:
            fvsol_path = os.path.join(CASE_DIR, "system", "fvSolution")
            with open(fvsol_path) as f:
                content = f.read()
            content = content.replace("nOuterCorrectors 20;", "nOuterCorrectors 3;")
            with open(fvsol_path, "w") as f:
                f.write(content)
            log("⚡ nOuterCorrectors reducido a 3 para cálculo rápido")

        log(f"✅ Setup OK  (solver={algo})")

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

        # 4 — Solver principal
        print(f"\n  [4/4] Ejecutando {algo}...")
        # pimpleFoam puede tardar más — timeout 30 min
        timeout = 1200 if transient else 900
        done_sol = {"rc": None}
        solver.run_solver(
            algo_name=algo, log_callback=log,
            done_callback=lambda rc: done_sol.update({"rc": rc}),
        )
        t0 = time.time()
        while done_sol["rc"] is None and time.time()-t0 < timeout:
            time.sleep(5)
        if done_sol["rc"] is None:
            solver.stop()
            raise TimeoutError(f"{algo} superó {timeout}s")
        if done_sol["rc"] != 0:
            raise RuntimeError(f"{algo} terminó con código {done_sol['rc']}")

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
              "transient","solver","Cl","Cd","Cm","status","error","wall_time_s"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
    print(f"\n📄 Resultados → {path}")


STAGE5_CASES = [
    {
        "label": "Transitorio",
        "transient": True,
        "delta_t": "5e-3",
        "end_time": "0.05",
        "write_interval": "0.01",
        "max_co": 2.0,
    },
]

# Resultado estacionario previo (ya ejecutado)
STEADY_RESULT = {
    "label": "Estacionario", "naca": "2412", "aoa": 10.0,
    "u_inlet": 15.0, "reynolds": 1_000_000, "turbulence": "k-Omega SST (RAS)",
    "transient": False, "solver": "simpleFoam",
    "Cl": 1.181768, "Cd": 0.06890671, "Cm": -0.05915358,
    "status": "OK", "error": "", "wall_time_s": 14.8,
}

if __name__ == "__main__":
    print("\n" + "█"*64)
    print(" ETAPA 5 — Estacionario vs Transitorio")
    print(" Perfil: NACA 2412  |  AoA=10°  |  Re=1M  |  k-ω SST")
    print("█"*64)

    results = [STEADY_RESULT]   # incluir resultado estacionario previo
    for case in STAGE5_CASES:
        r = run_case(**case)
        results.append(r)
        save_csv(results, RESULTS_CSV)

    ok  = [r for r in results if r["status"] == "OK"]
    err = [r for r in results if r["status"] != "OK"]

    print(f"\n{'═'*64}")
    print(f" RESUMEN ETAPA 5: {len(ok)}/{len(results)} casos exitosos")
    if ok:
        print(f"\n  {'Régimen':<14}  {'Solver':<12}  "
              f"{'Cl':>8}  {'Cd':>10}  {'Cm':>9}  {'L/D':>7}  {'t(s)':>7}")
        print(f"  {'-'*14}  {'-'*12}  "
              f"{'-'*8}  {'-'*10}  {'-'*9}  {'-'*7}  {'-'*7}")
        for r in ok:
            ld = r['Cl']/r['Cd'] if r['Cd'] else float('nan')
            print(f"  {r['label']:<14}  {r['solver']:<12}  "
                  f"{r['Cl']:>8.4f}  {r['Cd']:>10.5f}  "
                  f"{r['Cm']:>9.4f}  {ld:>7.2f}  {r['wall_time_s']:>7.1f}")
    if err:
        print("\n  Casos fallidos:")
        for r in err:
            print(f"  ❌ {r['label']}: {r['status']} — {r['error'][:80]}")
    print(f"{'═'*64}\n")
