from qtpy.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QSplitter, QTextEdit, QLabel, QLineEdit, QScrollArea, QTabWidget, QFileDialog, 
    QMenuBar, QMenu, QAction, QMessageBox, QToolBar)
from qtpy.QtCore import Qt, Signal, QTimer, QCoreApplication, QMutex
from qtpy.QtGui import QCloseEvent, QTextCursor
from typing import Optional, Dict, Any
import json
import os
import pyvista as pv
import numpy as np
import gmsh

from .input_panel import InputPanel
from .results_panel import ResultsPanel
from .plots import ResidualPlot, AeroPlot, PressurePlot
from .workers import MeshWorker, SweepWorker

from core.geometry import NacaGeometry
from core.meshing import NacaMesher
import time

class MainWindow(QMainWindow):
    log_signal = Signal(str)

    def _ensure_workdir(self) -> str:
        """Garantiza un directorio de trabajo escribible.

        La app escribe mallas, JSONs temporales y el caso de OpenFOAM con rutas
        relativas. Al abrirla desde Finder, el CWD puede ser `/` (solo lectura)
        y el arranque fallaba con PermissionError.
        """
        if os.access(os.getcwd(), os.W_OK):
            return os.getcwd()
        fallback = os.path.join(os.path.expanduser("~"), "OpenBlade")
        os.makedirs(fallback, exist_ok=True)
        os.chdir(fallback)
        return fallback

    def _sync_sys_path(self) -> None:
        """Permite `import core.*` aunque el CWD no sea la raíz del repo."""
        import sys
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenBlade 2D CFD Workbench")
        self.resize(1400, 900)
        
        self._sync_sys_path()
        workdir = self._ensure_workdir()
        self.case_dir = os.path.join(workdir, "openfoam_case")
        os.makedirs(self.case_dir, exist_ok=True)
            
        self._has_unsaved_work = False
        self.mesh_worker = None
        self.sweep_worker = None
        self.sim_worker = None
        self._current_aoa = 0.0
        self._sim_running = False
        
        self.mesh_lock = QMutex()
        
        # Datos de fuerza para simulación en punto único
        self._last_cl = 0.0
        self._last_cd = 0.0
        self._last_cm = 0.0

        
        # Inicializar Solver
        from core.solver import SolverRunner
        self.solver_runner = SolverRunner(case_dir=self.case_dir)
        
        self.init_ui()
        # No se limpia al iniciar: borraría la malla y los resultados del usuario.
        # La limpieza de temporales ocurre al cerrar.
        self.log_signal.connect(self.log)
        
        # Temporizador para redibujado suave de gráficas (Evita saturación en Mac)
        self.plot_timer = QTimer(self)
        self.plot_timer.timeout.connect(self.refresh_plots)
        self.plot_timer.start(100) # 10 FPS es suficiente y seguro


    def init_ui(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&Archivo")
        
        open_action = QAction("Abrir Proyecto", self)
        open_action.triggered.connect(self.load_project)
        file_menu.addAction(open_action)
        
        save_action = QAction("Guardar Proyecto", self)
        save_action.triggered.connect(self.save_project)
        file_menu.addAction(save_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Salir", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        toolbar = self.addToolBar("Principal")
        btn_report = QAction("📝 Generar Informe PDF", self)
        btn_report.triggered.connect(self.generate_report)
        toolbar.addAction(btn_report)

        self.btn_fsi = QAction("🌊 Análisis FSI", self)
        self.btn_fsi.triggered.connect(self.on_run_fsi)
        toolbar.addAction(self.btn_fsi)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)

        splitter = QSplitter(Qt.Horizontal)
        
        self.input_panel = InputPanel()
        self.input_panel.setMinimumWidth(380)
        self.input_panel.setMaximumWidth(450)
        splitter.addWidget(self.input_panel)


        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        
        self.tabs = QTabWidget()
        self.results_panel = ResultsPanel(self.case_dir)
        self.results_panel.log_signal.connect(self.log)
        self.res_plot = ResidualPlot()
        self.aero_plot = AeroPlot()
        self.cp_plot = PressurePlot()
        
        self.tabs.addTab(self.results_panel, "Visualización 3D")
        self.tabs.addTab(self.res_plot, "Residuales")
        self.tabs.addTab(self.aero_plot, "Cl / Cd")
        self.tabs.addTab(self.cp_plot, "Presión (Cp)")
        
        right_layout.addWidget(self.tabs, 7)
        
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.document().setMaximumBlockCount(300) # Previene saturación nativamente
        self.log_console.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: 'Courier New';")
        right_layout.addWidget(self.log_console, 3)
        
        splitter.addWidget(right_widget)
        layout.addWidget(splitter)

        self.input_panel.btn_geom.clicked.connect(self.on_build_geom)
        self.input_panel.btn_mesh.clicked.connect(self.on_build_mesh)
        self.input_panel.btn_run.clicked.connect(self.on_run_sim)
        self.input_panel.btn_results.clicked.connect(self.on_results)
        self.input_panel.btn_stop_sweep.clicked.connect(self.on_stop_sweep)
        self.input_panel.btn_stop_sim.clicked.connect(self.on_stop_sim)
        self.input_panel.btn_pause_sim.clicked.connect(self.on_pause_sim)

    def log(self, text: str) -> None:
        self.log_console.append(text)
        self.log_console.moveCursor(QTextCursor.MoveOperation.End)


    def _safe_get_params(self) -> Optional[Dict[str, Any]]:
        try:
            return self.input_panel.get_params()
        except ValueError as e:
            QMessageBox.warning(self, "Error de Validación", str(e))
            return None
        except Exception as e:
            QMessageBox.critical(self, "Error Crítico", f"Error inesperado al leer parámetros: {e}")
            return None

    def on_build_geom(self) -> None:
        p = self._safe_get_params()
        if not p: return
        
        is_custom = "Custom" in p.get("profile_type", "")
        file_path = p.get("file_path", None) if is_custom else None
        naca_val = p["naca"] if not is_custom else "custom"
        
        self.log(f"Construyendo geometría (NACA {naca_val})...")
        
        try:
            # Usar subproceso para evitar conflictos de OpenGL/Gmsh en Mac
            # sys.executable garantiza el mismo intérprete (y sus paquetes) que la GUI
            import subprocess
            import sys
            cmd = [sys.executable, "-m", "core.geom_script", str(naca_val), str(p['chord']), str(p['aoa']), "temp_geom.vtk"]
            if is_custom and file_path:
                cmd.append(str(file_path))
            from .workers import subprocess_env
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace',
                                    env=subprocess_env())
            
            if result.returncode == 0:
                self.log("Geometría generada. Proyectando...")
                self._has_unsaved_work = True
                QTimer.singleShot(200, self._delayed_preview_update)
            else:
                self.log(f"Error en script: {result.stderr}")
        except Exception as e:
            self.log(f"Error generando geometría: {e}")


    def _delayed_preview_update(self) -> None:
        try:
            if os.path.exists("temp_geom.vtk"):
                mesh = pv.read("temp_geom.vtk")
                self.results_panel.update_visual_preview(mesh)
        except Exception as e:
            self.log(f"Error de visualización: {e}")

    def on_build_mesh(self) -> None:
        if self.mesh_worker is not None and self.mesh_worker.isRunning():
            self.log("⚠️ Ya hay un mallado en curso.")
            return

        p = self._safe_get_params()
        if not p: return
        
        # Para perfiles custom el nombre no puede salir de 'naca' ("custom")
        msh_file = f"perfil_{p['naca'] or 'custom'}.msh"
        self.log(f"Iniciando mallado de alta fidelidad...")
        
        self.input_panel.btn_mesh.setEnabled(False)
        self.mesh_worker = MeshWorker(p, msh_file, self.case_dir)
        self.mesh_worker.finished.connect(self.on_mesh_done)
        self.mesh_worker.error.connect(self._on_mesh_error)
        self.mesh_worker.log_msg.connect(self.log)
        self.mesh_worker.start()

    def _on_mesh_error(self, message: str) -> None:
        self.input_panel.btn_mesh.setEnabled(True)
        self.log(f"❌ Error de mallado: {message}")

    def on_mesh_done(self, msh_file: str, stl_file: str) -> None:
        self.input_panel.btn_mesh.setEnabled(True)
        if os.path.exists(msh_file):
            self._has_unsaved_work = True
            self.log(f"✅ Malla estructurada generada: {msh_file}")
            self.log("Cargando vista previa de la malla...")
            try:
                # Usar el STL para una vista más ligera de la superficie si existe, si no el VTK
                vtk_file = msh_file.replace(".msh", ".vtk")
                if os.path.exists(vtk_file):
                    import pyvista as pv
                    mesh = pv.read(vtk_file)
                    self.results_panel.update_visual_preview(mesh, show_edges=True)
                elif os.path.exists(stl_file):
                    import pyvista as pv
                    mesh = pv.read(stl_file)
                    self.results_panel.update_visual_preview(mesh, show_edges=True)
            except Exception as e:
                self.log(f"Aviso visualización: {e}")

    def on_run_sim(self) -> None:
        if self._sim_running:
            self.log("⚠️ Ya hay una simulación en curso. Deténla antes de lanzar otra.")
            return

        p = self._safe_get_params()
        if not p: return
        
        # Verificar si es modo barrido
        if "Barrido" in p.get("analysis_mode", ""):
            self._run_sweep(p)
            return
        
        msh_file = f"perfil_{p['naca']}.msh"
        if not os.path.exists(msh_file):
            self.log("❌ Error: Debes generar la malla antes de iniciar el análisis.")
            return

        self._has_unsaved_work = True
        self.log(f"Iniciando simulación CFD (Modo Rendimiento)...")
        if hasattr(self, 'res_plot'):
            self.res_plot.reset()

        from .workers import SimWorker
        self._current_aoa = float(p.get("aoa", 0.0))
        self._sim_running = True
        self.input_panel.btn_run.setEnabled(False)
        self.input_panel.btn_stop_sim.setVisible(True)
        self.input_panel.btn_stop_sim.setEnabled(True)
        self.input_panel.btn_pause_sim.setVisible(True)
        self.input_panel.btn_pause_sim.setEnabled(True)
        self.input_panel.btn_pause_sim.setText("⏸️ Pausar")
        self._paused = False
        self._sim_steps = 0
        self._last_t = -1.0
        self._sim_t0 = time.time()
        self._sim_end_time = float(p.get("end_time", 0.5))
        self.input_panel.progress_label.setVisible(True)
        self.input_panel.progress_label.setText("Iniciando...")
        self.sim_worker = SimWorker(self.solver_runner, p, msh_file)
        self.sim_worker.log_msg.connect(self.log)
        self.sim_worker.residual_data.connect(self.on_residual_data)
        self.sim_worker.force_data.connect(self.on_force_data)
        self.sim_worker.finished.connect(self.on_sim_done)
        self.sim_worker.error.connect(self.log)
        self.sim_worker.start_sim()
    
    def _run_sweep(self, p: Dict[str, Any]) -> None:
        """Ejecuta un barrido paramétrico de ángulos de ataque (polar)."""
        self._has_unsaved_work = True
        self._sim_running = True
        self.input_panel.btn_run.setEnabled(False)
        self.input_panel.btn_stop_sim.setVisible(False)
        self.log("📊 Iniciando barrido de ángulos...")
        self.input_panel.btn_stop_sweep.setVisible(True)
        self.input_panel.btn_stop_sweep.setEnabled(True)
        if hasattr(self, 'res_plot'):
            self.res_plot.reset()
        
        from .workers import SweepWorker
        self.sweep_worker = SweepWorker(p, self.case_dir)
        self.sweep_worker.log_msg.connect(self.log)
        self.sweep_worker.error.connect(self._on_sweep_error)
        self.sweep_worker.progress.connect(self._on_sweep_progress)
        self.sweep_worker.finished.connect(self._on_sweep_done)
        self.sweep_worker.mesh_generated.connect(self._on_sweep_mesh)
        self.sweep_worker.start()
    
    def _on_sweep_mesh(self, vtk_file: str) -> None:
        """Actualiza la vista 3D durante un barrido."""
        if os.path.exists(vtk_file):
            import pyvista as pv
            try:
                mesh = pv.read(vtk_file)
                self.results_panel.update_visual_preview(mesh, show_edges=True)
            except Exception:
                pass

    def on_run_fsi(self) -> None:
        """Lanza el acoplamiento fluido-estructura con preCICE."""
        from core.fsi_runner import FsiRunner, check_image

        if self._sim_running:
            self.log("⚠️ Ya hay una simulación en curso.")
            return

        if not check_image():
            QMessageBox.warning(
                self, "Imagen FSI no disponible",
                "Para FSI hace falta la imagen con preCICE.\n\n"
                "Construir con:\n"
                "docker build -f docker/Dockerfile.openblade-fsi -t openblade-fsi:dev ."
            )
            return

        p = self._safe_get_params()
        if not p:
            return
        if not p.get("fsi_enabled"):
            QMessageBox.information(
                self, "FSI desactivado",
                "Activa 'Acoplamiento FSI (preCICE)' en la sección FSI del panel."
            )
            return

        msh = f"perfil_{p.get('naca') or 'custom'}.msh"
        if not os.path.exists(msh):
            self.log("❌ Genera la malla antes de lanzar FSI.")
            return

        self._sim_running = True
        self.input_panel.btn_run.setEnabled(False)
        self.log("🌊 Iniciando acoplamiento FSI (preCICE)…")
        self.log(f"   E={p['fsi_E']:.3g} Pa, ν={p['fsi_nu']:.3f}, "
                 f"malla sólido {p['fsi_nx']}×{p['fsi_ny']}")
        self.log(f"   dt={p['fsi_dt']} s, t_final={p['fsi_end_time']} s, "
                 f"acople={p['fsi_coupling']}")

        try:
            runner = FsiRunner(self.case_dir, p, log=self.log)
            result = runner.run()
        except Exception as e:  # noqa: BLE001
            self.log(f"❌ Error FSI: {e}")
            self._reset_run_state()
            return

        if result.ok:
            self.log(f"✅ FSI completado: {result.time_windows} ventanas de tiempo")
            self.log(f"   Desplazamiento máximo: {result.displacement_max:.6e} m")
        else:
            self.log(f"❌ FSI falló (fluido rc={result.exit_fluid}, "
                     f"sólido rc={result.exit_solid})")
            if result.error:
                self.log(f"   {result.error}")
            if result.log_solid:
                for line in result.log_solid.strip().splitlines()[-6:]:
                    self.log(f"   │ {line}")

        self._reset_run_state()

    def on_pause_sim(self) -> None:
        """Pausa o reanuda el contenedor del solver sin perder el estado.

        Se usa `docker pause` / `docker unpause`, que envían SIGSTOP/SIGCONT
        al proceso dentro del contenedor. A diferencia de detener, conserva el
        campo de flujo y los ficheros de tiempo ya escritos: reanudar continúa
        desde donde iba.
        """
        import subprocess as sp

        if getattr(self, "_paused", False):
            action, label = "unpause", "⏸️ Pausar"
            self.log("▶️ Reanudando simulación...")
        else:
            action, label = "pause", "▶️ Reanudar"
            self.log("⏸️ Pausando simulación...")

        try:
            ids = sp.run(["docker", "ps", "-q", "--filter",
                          "ancestor=opencfd/openfoam-default"],
                         capture_output=True, text=True, timeout=15).stdout.split()
            for cid in ids:
                sp.run(["docker", action, cid], capture_output=True,
                       text=True, timeout=15)
            self._paused = not getattr(self, "_paused", False)
            self.input_panel.btn_pause_sim.setText(label)
            self.log(f"   {'Pausada' if self._paused else 'En marcha'} "
                     f"({len(ids)} contenedor(es)).")
        except Exception as e:  # noqa: BLE001
            self.log(f"⚠️ No se pudo {'pausar' if action == 'pause' else 'reanudar'}: {e}")

    def _update_progress(self, t_current: float, n_steps: int = 0) -> None:
        """Rellena el panel de progreso con tiempo, porcentaje y ritmo.

        Los datos salen del propio solver: `t_current` es el tiempo simulado
        que llega con cada RESIDUAL_DATA, y `n_steps` el número de muestras
        vistas. El ritmo se calcula con el reloj de pared.
        """
        lbl = self.input_panel.progress_label
        # No se comprueba isVisible(): con la ventana aún no mostrada (o en
        # tests offscreen) devuelve False aunque el widget esté habilitado, y
        # el panel se quedaba vacío.
        if lbl is None:
            return

        t0 = getattr(self, "_sim_t0", None)
        if t0 is None:
            return
        elapsed_min = (time.time() - t0) / 60.0
        end = getattr(self, "_sim_end_time", 0.5) or 0.5
        pct = 100.0 * t_current / end if end > 0 else 0.0

        if n_steps > 0 and elapsed_min > 0:
            per_step = elapsed_min / n_steps
            restante = (end - t_current) / max(t_current / n_steps, 1e-9)
            eta = restante / 60.0
            eta_txt = (f"{eta:.0f} h" if eta > 90 else f"{eta:.0f} min")
            ritmo = f"{n_steps} pasos en {elapsed_min:.0f} min → {per_step:.1f} min/paso"
        else:
            eta_txt, ritmo = "—", "—"

        ahora = time.strftime("%H:%M")
        inicio = time.strftime("%H:%M", time.localtime(t0))
        estado = "⏸ PAUSADA" if getattr(self, "_paused", False) else "▶ en marcha"

        lbl.setText(
            f"{estado}   {inicio} → {ahora}  ({elapsed_min:.0f} min)\n"
            f"Progreso:  t = {t_current:.4g} de {end:g} s   ({pct:.1f}%)\n"
            f"Falta:     {100 - pct:.1f}%   ·   ETA ~{eta_txt}\n"
            f"Ritmo:     {ritmo}"
        )

    def on_stop_sim(self) -> None:
        """Detiene una simulación de punto único en curso."""
        if self.sim_worker is None:
            return
        self.log("⏳ Deteniendo simulación...")
        self.sim_worker.stop()
        self.solver_runner.stop()
        self.input_panel.btn_stop_sim.setEnabled(False)

    def on_stop_sweep(self) -> None:
        if hasattr(self, 'sweep_worker') and self.sweep_worker:
            self.sweep_worker.request_stop()
            self.log("⏳ Solicitando detención del barrido...")
            self.input_panel.btn_stop_sweep.setEnabled(False)
    
    def _on_sweep_progress(self, current: int, total: int) -> None:
        self.log(f"  Progreso: {current}/{total}")
    
    def _on_sweep_error(self, message: str) -> None:
        """Un barrido fallido también debe liberar la UI."""
        self.log(f"❌ Error en barrido: {message}")
        self._reset_run_state()

    def _reset_run_state(self) -> None:
        self._sim_running = False
        self.input_panel.btn_run.setEnabled(True)
        self.input_panel.btn_stop_sweep.setVisible(False)
        self.input_panel.btn_stop_sweep.setEnabled(True)
        self.input_panel.btn_stop_sim.setVisible(False)
        self.input_panel.btn_stop_sim.setEnabled(True)

    def _on_sweep_done(self, aoa_list, cl_list, cd_list, cm_list) -> None:
        self.log(f"✅ Barrido completado: {len(aoa_list)} puntos")
        self._reset_run_state()
        if hasattr(self, 'aero_plot') and aoa_list:
            self.aero_plot.update_plots(aoa_list, cl_list, cd_list, cm_list)
            self.tabs.setCurrentWidget(self.aero_plot)
            self.log("📈 Gráfica polar actualizada en pestaña Cl/Cd.")

    def on_sim_done(self, code: int) -> None:
        self.log(f"🏁 Simulación finalizada (Código {code})")
        self._reset_run_state()
        self.results_panel.setEnabled(True)
        if code != 0:
            self.log("❌ El solver terminó con error. Revisa el log antes de interpretar resultados.")
            return
        # Sugerir cargar resultados
        self.log("💡 Puedes pulsar 'Ver Resultados' para visualizar el flujo.")
        self._refresh_cp_plot()



    def on_residual_data(self, field: str, val: float, time: float) -> None:
        """Actualiza la gráfica de residuales y el panel de progreso.

        `time` es el tiempo simulado que reporta OpenFOAM en esa iteración;
        se usa tanto para el eje X de la gráfica como para calcular el avance.
        """
        if hasattr(self, 'res_plot'):
            try:
                self.res_plot.update_plot(field, val, time)
            except Exception as e:
                print(f"Error plot residual: {e}")

        # Contar pasos distintos: cada iteración puede reportar varias
        # ecuaciones (Ux, Uy, p, k, omega) con el mismo tiempo.
        if not hasattr(self, "_sim_steps"):
            self._sim_steps = 0
            self._last_t = -1.0
        if time > getattr(self, "_last_t", -1.0):
            self._sim_steps += 1
            self._last_t = time
        self._update_progress(time, self._sim_steps)

    def refresh_plots(self) -> None:
        # Solo redibujar si hay cambios pendientes y no estamos saturando
        try:
            if hasattr(self, 'res_plot') and self.res_plot._pending_redraw:
                self.res_plot.redraw()
            if hasattr(self, 'aero_plot') and self.aero_plot._pending_redraw:
                self.aero_plot.redraw()
        except Exception as e:
            # Silenciar errores asíncronos de matplotlib (como desajuste de dimensiones temporal)
            pass




    def on_force_data(self, name: str, val: str) -> None:
        try:
            v_float = float(val)
            name_lower = name.lower()
            # Comparar nombres normalizados: "cl" es subcadena de "clock"/"incl",
            # y el orden importa para no asignar Cm a Cl.
            if name_lower.startswith("cl"):
                self._last_cl = v_float
            elif name_lower.startswith("cd"):
                self._last_cd = v_float
            elif name_lower.startswith("cm"):
                self._last_cm = v_float
            
            # Actualizar gráfica Cl/Cd en tiempo real (punto único).
            # Se usa el AoA capturado al lanzar la simulación: leer el panel aquí
            # podría abrir un QMessageBox en cada iteración del solver.
            if hasattr(self, 'aero_plot'):
                self.aero_plot.update_plots(
                    [self._current_aoa], [self._last_cl], [self._last_cd], [self._last_cm]
                )
        except (ValueError, TypeError):
            pass

    def _refresh_cp_plot(self) -> None:
        """Calcula y dibuja la distribución de Cp sobre el perfil."""
        try:
            from core.postprocessing import PostProcessor
            p = self.input_panel.get_params()
            pp = PostProcessor(self.case_dir)
            data = pp.get_cp_on_surface(u_inf=float(p.get("u_inlet", 15.0)))
            if not data:
                self.log("ℹ️ Cp no disponible: aún no hay resultados o falta el patch 'airfoil'.")
                return
            self.cp_plot.update_cp(*data)
            self.log("📉 Distribución de Cp actualizada.")
        except Exception as e:
            self.log(f"⚠️ No se pudo calcular Cp: {e}")

    def on_results(self) -> None:
        p = self._safe_get_params()
        is_transient = False
        if p and "Transitorio" in p.get("regime", ""):
            is_transient = True
        if self.results_panel.load_results(is_transient=is_transient):
            self._refresh_cp_plot()

    def generate_report(self) -> None:
        p = self._safe_get_params()
        if not p: return
        
        from core.report_generator import generate_pdf_report
        
        self.log("Generando informe PDF...")
        
        images = {}
        # Save plots
        try:
            if hasattr(self, 'res_plot'):
                self.res_plot.fig.savefig("temp_res.png", dpi=150, bbox_inches='tight')
                images["Gráfica de Residuos"] = "temp_res.png"
            if hasattr(self, 'aero_plot'):
                self.aero_plot.fig.savefig("temp_aero.png", dpi=150, bbox_inches='tight')
                images["Curvas Polares"] = "temp_aero.png"
            if hasattr(self, 'cp_plot'):
                self.cp_plot.fig.savefig("temp_cp.png", dpi=150, bbox_inches='tight')
                images["Distribución de Cp"] = "temp_cp.png"
            if self.results_panel.plotter:
                self.results_panel.plotter.screenshot("temp_mesh.png")
                images["Dominio y Malla / Resultados"] = "temp_mesh.png"
        except Exception as e:
            self.log(f"Aviso al guardar imágenes para informe: {e}")
            
        results = {
            "Cl": self._last_cl,
            "Cd": self._last_cd,
            "Cm": self._last_cm
        }
        
        filename, _ = QFileDialog.getSaveFileName(self, "Guardar Informe", "informe_cfd.pdf", "PDF Files (*.pdf)")
        if filename:
            if not filename.endswith(".pdf"):
                filename += ".pdf"
            try:
                generate_pdf_report(filename, p, results, images)
                self.log(f"✅ Informe PDF generado exitosamente en {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Fallo al generar PDF: {e}")
                self.log(f"❌ Error PDF: {e}")
        else:
            self.log("Generación de informe cancelada.")
        
        # Limpiar temporales
        for img in images.values():
            if os.path.exists(img):
                try:
                    os.remove(img)
                except:
                    pass

    def save_project(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, "Guardar Proyecto", "", "OpenBlade (*.obp)")
        if not filename:
            return
        if not filename.endswith(".obp"):
            filename += ".obp"
        try:
            p = self._safe_get_params()
            if p is None:
                return
            project_data = {
                "version": "2.0",
                "app": "OpenBlade 2D",
                "params": p,
                "case_dir": self.case_dir
            }
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(project_data, f, indent=2, ensure_ascii=False)
            self._has_unsaved_work = False
            self.log(f"✅ Proyecto guardado en {filename}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo guardar el proyecto:\n{e}")

    def load_project(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Abrir Proyecto", "", "OpenBlade (*.obp)")
        if not filename:
            return
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            
            params = project_data.get("params", {})
            if params:
                self.input_panel.set_params(params)
                self.log(f"✅ Proyecto cargado desde {filename}")
                self._has_unsaved_work = False
            else:
                self.log("⚠️ El archivo no contiene parámetros válidos.")
        except json.JSONDecodeError:
            QMessageBox.critical(self, "Error", "El archivo no es un proyecto OpenBlade válido.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo abrir el proyecto:\n{e}")

    def cleanup(self) -> None:
        """Limpieza de archivos temporales y resultados residuales.

        Importante: NO borra `perfil_*.msh|vtk|stl`. El usuario puede tener una
        malla generada que tarda minutos; al abrir la app se destruía sin aviso.
        """
        import shutil
        temp_files = [
            "temp_params_mesh.json", "temp_params_solve.json", "temp_params_sweep.json",
            "temp_geom.vtk", "debug.msh", "debug.vtk", "vtk_errors.log", "debug_gmsh.log",
            "temp_geom.stl"
        ]
        for f in temp_files:
            if os.path.exists(f):
                try: os.remove(f)
                except: pass

        # Solo se limpian mallas temporales del barrido (nombre reservado).
        for f in os.listdir("."):
            if f.startswith("perfil_") and (f.endswith("_sweep.msh") or f.endswith("_sweep.vtk")):
                try: os.remove(f)
                except: pass

        # Limpiar resultados de OpenFOAM previos
        if os.path.exists(self.case_dir):
            for item in os.listdir(self.case_dir):
                item_path = os.path.join(self.case_dir, item)
                # Borrar carpetas de tiempo (números) y postProcessing
                if (item.replace(".", "").isdigit() and item != "0") or item == "postProcessing":
                    try: 
                        if os.path.isdir(item_path): shutil.rmtree(item_path)
                        else: os.remove(item_path)
                    except: pass

    def closeEvent(self, event: QCloseEvent) -> None:
        """Asegura que no queden procesos o archivos bloqueados al cerrar."""
        if self._has_unsaved_work:
            reply = QMessageBox.question(
                self, "Confirmar Salida",
                "Hay trabajo sin guardar. ¿Deseas guardar antes de salir?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save
            )
            if reply == QMessageBox.Save:
                self.save_project()
            elif reply == QMessageBox.Cancel:
                event.ignore()
                return

        self.log("🛑 Cerrando aplicación...")
        # Detener todo lo que pueda quedar vivo: QProcess del solver, hilos y Docker.
        if self.sim_worker is not None:
            try:
                self.sim_worker.stop()
            except Exception:
                pass
        if self.solver_runner:
            self.solver_runner.stop()
        for worker in (self.mesh_worker, self.sweep_worker):
            if worker is not None:
                try:
                    # Cortar primero el subproceso: wait() solo no lo mata.
                    if hasattr(worker, "cancel"):
                        worker.cancel()
                    else:
                        worker.request_stop()
                    worker.wait(5000)
                except Exception:
                    pass
        self.cleanup()
        event.accept()