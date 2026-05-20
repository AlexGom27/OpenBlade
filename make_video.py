"""
Genera video MP4 de simulación pimpleFoam NACA 0012 α=12°.
Usa malla ya convertida en openfoam_case/. Renderiza con PyVista offscreen.
"""
import os, sys, time, subprocess, shutil, glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.openfoam_setup import OpenFoamSetup
from core.solver import SolverRunner

HERE = os.path.dirname(os.path.abspath(__file__))
CASE_DIR = os.path.join(HERE, "openfoam_case")
VIDEO_OUT = os.path.join(HERE, "simulacion_pimplefoam.mp4")


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def step1_setup_transient():
    """Configura el caso para pimpleFoam con write interval razonable."""
    log("PASO 1/3 — Configurando caso pimpleFoam transitorio…")

    # Limpiar timesteps previos (excepto 0)
    for item in os.listdir(CASE_DIR):
        try:
            if float(item) > 0:
                shutil.rmtree(os.path.join(CASE_DIR, item), ignore_errors=True)
        except (ValueError, FileNotFoundError):
            pass
    shutil.rmtree(os.path.join(CASE_DIR, "postProcessing"), ignore_errors=True)

    # Reescribir con parámetros transitorios para video bonito
    setup = OpenFoamSetup(case_dir=CASE_DIR)
    setup.create_case(
        u_inlet=15.0,
        p_outlet=0.0,
        chord=1.0,
        transient=True,
        tolerance="1e-4",
        turbulence="k-Omega SST (RAS)",
        reynolds=2_000_000.0,
        delta_t="1e-3",            # 10× más grande
        end_time="0.02",           # corto pero suficiente
        write_interval="0.0005",   # 40 frames
        max_co=4.0,                # CFL más relajado
    )
    log("   pimpleFoam | endTime=0.02s | writeInterval=0.0005s | maxCo=4 | ~40 frames")


def step2_run_solver():
    """Corre pimpleFoam vía Docker."""
    log("PASO 2/3 — Ejecutando pimpleFoam…")
    runner = SolverRunner(case_dir=CASE_DIR)

    # create_case borra polyMesh: hay que re-convertir desde el .msh
    msh = os.path.join(CASE_DIR, "validacion_nasa.msh")
    if not os.path.exists(msh):
        log(f"   ❌ Malla {msh} no encontrada")
        return False
    log("   2a) gmshToFoam (re-convertir malla)…")
    runner.run_gmshToFoam(msh, log_callback=lambda m: None)

    log("   2b) potentialFoam (inicialización)…")
    pdone = {"ok": False}
    runner.run_potentialFoam(log_callback=lambda m: None,
                              done_callback=lambda c: pdone.update({"ok": True}))
    t0 = time.time()
    while not pdone["ok"] and time.time() - t0 < 120:
        time.sleep(1)

    log("   2c) pimpleFoam (solver transitorio)…")
    forces = {"Cd": None, "Cl": None}
    done = {"ok": False}

    runner.run_solver(
        algo_name="pimpleFoam",
        log_callback=lambda m: None,
        force_callback=lambda n, v: forces.__setitem__(n, v),
        residual_callback=lambda f, v, t: None,
        done_callback=lambda c: done.update({"ok": True, "code": c}),
    )

    # Esperar
    t0 = time.time()
    last = 0
    while not done["ok"] and time.time() - t0 < 1800:
        time.sleep(2)
        if time.time() - last > 20:
            n_steps = len([d for d in os.listdir(CASE_DIR)
                           if d != "0" and os.path.isdir(os.path.join(CASE_DIR, d))
                           and d.replace(".", "").replace("-", "").isdigit()])
            log(f"   … {int(time.time()-t0)}s  |  Cd={forces['Cd']} Cl={forces['Cl']}  |  timesteps escritos: {n_steps}")
            last = time.time()

    elapsed = time.time() - t0
    log(f"   pimpleFoam finalizó en {elapsed:.0f}s (código {done.get('code')})")
    return done["ok"]


def step3_render_video():
    """Renderiza video con PyVista offscreen leyendo cada timestep."""
    log("PASO 3/3 — Renderizando video con PyVista…")
    import pyvista as pv
    import numpy as np

    # Tocar archivo .foam para que el reader lo encuentre
    foam_file = os.path.join(CASE_DIR, "case.foam")
    if not os.path.exists(foam_file):
        open(foam_file, "w").close()

    reader = pv.POpenFOAMReader(foam_file)
    times = sorted(reader.time_values)
    log(f"   Encontrados {len(times)} timesteps: {times[0]:.4f}…{times[-1]:.4f}s")

    if len(times) < 3:
        log("   ⚠️ Muy pocos timesteps. ¿pimpleFoam falló?")
        return False

    # Configurar plotter offscreen
    plotter = pv.Plotter(off_screen=True, window_size=(1280, 720))
    plotter.open_movie(VIDEO_OUT, framerate=15, quality=7)
    plotter.set_background("white")

    # Configurar cámara basada en bounds del primer mesh
    reader.set_active_time_value(times[0])
    mesh_first = reader.read()["internalMesh"]
    plotter.add_mesh(mesh_first, color="white", show_edges=False, opacity=0.01)
    plotter.view_xy()
    plotter.camera.zoom(1.0)
    plotter.clear()

    # Calcular rango de velocidad global para escala consistente
    U_max_global = 0.0
    for t in times:
        reader.set_active_time_value(t)
        mesh_data = reader.read()
        internal = mesh_data["internalMesh"]
        if "U" in internal.point_data:
            U = np.asarray(internal.point_data["U"])
            U_mag = np.linalg.norm(U, axis=1)
            U_max_global = max(U_max_global, U_mag.max())
        elif "U" in internal.cell_data:
            U = np.asarray(internal.cell_data["U"])
            U_mag = np.linalg.norm(U, axis=1)
            U_max_global = max(U_max_global, U_mag.max())

    clim = [0, U_max_global * 1.1]
    log(f"   Rango velocidad global: 0 a {U_max_global:.2f} m/s")

    for i, t in enumerate(times):
        reader.set_active_time_value(t)
        mesh_data = reader.read()
        internal = mesh_data["internalMesh"]

        # Calcular magnitud de velocidad
        if "U" in internal.point_data:
            U = np.asarray(internal.point_data["U"])
            mag = np.linalg.norm(U, axis=1)
            internal["U_mag"] = mag
        elif "U" in internal.cell_data:
            U = np.asarray(internal.cell_data["U"])
            mag = np.linalg.norm(U, axis=1)
            internal["U_mag"] = mag

        plotter.clear()
        plotter.add_mesh(internal, scalars="U_mag", cmap="jet", clim=clim,
                          show_edges=False, show_scalar_bar=True,
                          scalar_bar_args={"title": "|U| [m/s]", "color": "black"})

        # Texto de tiempo
        plotter.add_text(f"NACA 0012 @ α=12° (Re=2×10⁶) — t = {t:.4f} s",
                          position="upper_left", color="black", font_size=10)
        plotter.add_text(f"frame {i+1}/{len(times)}",
                          position="lower_right", color="black", font_size=8)

        plotter.write_frame()
        if (i + 1) % 10 == 0 or i == len(times) - 1:
            log(f"   Renderizado frame {i+1}/{len(times)}")

    plotter.close()
    size_kb = os.path.getsize(VIDEO_OUT) // 1024
    log(f"✅ Video generado: {VIDEO_OUT} ({size_kb} KB)")
    return True


if __name__ == "__main__":
    t0 = time.time()
    try:
        step1_setup_transient()
        if step2_run_solver():
            step3_render_video()
        log(f"✅ Completo — {int(time.time()-t0)}s total")
    except Exception as e:
        log(f"❌ Error: {e}")
        import traceback; traceback.print_exc()
