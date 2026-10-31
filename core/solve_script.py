import sys
import os
import json
import time
from core.solver import SolverRunner
from core.openfoam_setup import OpenFoamSetup

def angle_by_flow(p):
    """El angulo lo da el flujo, no la malla: una malla importada no se puede girar."""
    return bool(p.get("mesh_file")) or p.get("mesher") == "cgrid" or p.get("alpha_mode") == "flujo"


def first_cell_height(p):
    """Altura de la primera celda, en cuerdas: de ella depende la condicion de pared."""
    if p.get("mesher") == "cgrid":
        from core.cgrid import first_cell_at_level
        return first_cell_at_level(p)
    return p.get("bl_dist_min", 2e-5)


def configure_case(case_dir, p):
    """Escribe el caso de OpenFOAM. Lo comparten la corrida local y la de servidor."""
    setup = OpenFoamSetup(case_dir)
    is_transient = "pimpleFoam" in p.get("regime", "")
    setup.create_case(
        u_inlet=p["u_inlet"],
        p_outlet=p["p_outlet"],
        chord=p["chord"],
        transient=is_transient,
        tolerance=p.get("tolerance", "1e-4"),
        turbulence=p.get("turbulence", "kEpsilon"),
        reynolds=p.get("reynolds", 1000000.0),
        delta_t=p.get("delta_t", "1e-3"),
        end_time=p.get("end_time", "0.5"),
        write_interval=p.get("write_interval", "0.01"),
        max_co=p.get("max_co", 2.0),
        max_iters=p.get("max_iters", 500),
        momentum_scheme=p.get("momentum_scheme", "limitedLinearV"),
        # La malla se extruye `depth` cuerdas: Aref debe usar la misma profundidad.
        depth=float(p.get("depth", 0.1)) * float(p["chord"]),
        bl_dist_min=first_cell_height(p),
        turb_intensity=float(p.get("turb_intensity", 0.052)) / 100.0,
        viscosity_ratio=p.get("viscosity_ratio", 0.009),
        aoa_flow=float(p.get("aoa", 0.0)) if angle_by_flow(p) else 0.0,
        bc_type=p.get("bc_type", "entrada_salida"),
        turb_scheme=p.get("turb_scheme", "upwind"),
        grad_scheme=p.get("grad_scheme", "cellMDLimited Gauss linear 1"),
        lap_correction=p.get("lap_correction", "limited corrected 0.5"),
        relax_p=p.get("relax_p", 0.2),
        relax_eq=p.get("relax_eq", 0.5),
    )
    return is_transient


def main():
    if len(sys.argv) < 3:
        print("Uso: python3 solve_script.py params.json mesh_file.msh")
        sys.exit(1)
        
    json_path = sys.argv[1]
    msh_file = sys.argv[2]
    
    with open(json_path, 'r') as f:
        p = json.load(f)
        
    # El caso vive fuera del repositorio (ver core/paths.py).
    from core import paths
    case_dir = paths.case_dir()
    
    try:
        # 1. Configuración del caso
        print(f"DEBUG: Iniciando solución para AoA = {p.get('aoa', 0.0)} deg")
        print("📝 Configurando túnel de viento...")
        is_transient = configure_case(case_dir, p)

        # 2. Inicialización del Solver
        solver = SolverRunner(case_dir=case_dir, native=p.get("native_foam", False))
        
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
            
        rc = solver.process.returncode
        print(f"✅ Simulación finalizada (Código {rc}).")
        # Propagar el código de salida para que barridos/GUI detecten fallos reales
        sys.exit(rc if rc else 0)

    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR_CRITICAL: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
