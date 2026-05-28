import sys
import os
import json
import time
from core.solver import SolverRunner
from core.openfoam_setup import OpenFoamSetup

def main():
    if len(sys.argv) < 3:
        print("Uso: python3 solve_script.py params.json mesh_file.msh")
        sys.exit(1)
        
    json_path = sys.argv[1]
    msh_file = sys.argv[2]
    
    with open(json_path, 'r') as f:
        p = json.load(f)
        
    case_dir = "openfoam_case"
    
    try:
        # 1. Configuración del caso
        print(f"DEBUG: Iniciando solución para AoA = {p.get('aoa', 0.0)} deg")
        print("📝 Configurando túnel de viento...")
        setup = OpenFoamSetup(case_dir)
        is_transient = "pimpleFoam" in p.get("regime", "")
        setup.create_case(
            u_inlet=p["u_inlet"],
            p_outlet=p["p_outlet"],
            chord=p["chord"],
            transient=is_transient,
            tolerance=p.get("tolerance", "1e-4"),
            turbulence=p.get("turbulence", "kEpsilon"),
            max_iters=p.get("max_iters", 500)
        )
        
        # 2. Inicialización del Solver
        solver = SolverRunner(case_dir=case_dir)
        
        # 3. gmshToFoam
        print("🔄 Convirtiendo malla...")
        solver.run_gmshToFoam(msh_file, log_callback=print)
        
        # 3.5. Inicialización de flujo potencial
        import threading
        pf_event = threading.Event()
        solver.run_potentialFoam(log_callback=print, done_callback=lambda c: pf_event.set())
        pf_event.wait()
        
        # 4. Ejecución del Solver principal
        algo = "pimpleFoam" if is_transient else "simpleFoam"
        print(f"🚀 Iniciando solucionador {algo}...")
        
        solver.run_solver(
            algo_name=algo,
            log_callback=print,
            force_callback=lambda f, v: print(f"FORCE_DATA|{f}|{v}"),
            residual_callback=lambda f, v, t: print(f"RESIDUAL_DATA|{f}|{v}|{t}"),
            done_callback=lambda c: print(f"SIM_DONE|{c}")
        )
        
        # Espera activa y segura a que el proceso arranque y termine
        time.sleep(1.0) # Margen inicial
        
        # Esperar a que el proceso se asigne
        max_wait = 10
        waited = 0
        while solver.process is None and waited < max_wait:
            time.sleep(0.5)
            waited += 1
            
        if solver.process is None:
            print("ERROR: El proceso del solucionador no arrancó en el tiempo esperado.")
            sys.exit(1)

        # Monitorizar ejecución
        while solver.process and solver.process.poll() is None:
            time.sleep(0.5)
            
        print(f"✅ Simulación finalizada (Código {solver.process.returncode}).")
        
    except Exception as e:
        print(f"ERROR_CRITICAL: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
