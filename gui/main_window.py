from qtpy.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QSplitter, QTextEdit, QLabel, QLineEdit, QScrollArea, QTabWidget, QFileDialog, 
    QMenuBar, QMenu, QAction, QMessageBox, QToolBar)
from qtpy.QtCore import Qt, Signal, QTimer, QCoreApplication, QMutex
from qtpy.QtGui import QCloseEvent
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

class MainWindow(QMainWindow):
    log_signal = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenBlade 2D CFD Workbench")
        self.resize(1400, 900)
        
        self.case_dir = os.path.join(os.getcwd(), "openfoam_case")
        if not os.path.exists(self.case_dir):
            os.makedirs(self.case_dir)
            
        self._has_unsaved_work = False
        self.mesh_worker = None
        self.sweep_worker = None
        
        self.mesh_lock = QMutex()
        
        # Datos de fuerza para simulación en punto único
        self._last_cl = 0.0
        self._last_cd = 0.0
        self._last_cm = 0.0

        
        # Inicializar Solver
        from core.solver import SolverRunner
        self.solver_runner = SolverRunner(case_dir=self.case_dir)
        
        self.init_ui()
        self.cleanup() # Limpieza al iniciar
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

    def log(self, text: str) -> None:
        self.log_console.append(text)
        from PySide6.QtGui import QTextCursor
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
            import subprocess
            cmd = ["python3", "-m", "core.geom_script", str(naca_val), str(p['chord']), str(p['aoa']), "temp_geom.vtk"]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
            
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
        p = self._safe_get_params()
        if not p: return
        
        msh_file = f"perfil_{p['naca']}.msh"
        self.log(f"Iniciando mallado de alta fidelidad...")
        
        self.mesh_worker = MeshWorker(p, msh_file, self.case_dir)
        self.mesh_worker.finished.connect(self.on_mesh_done)
        self.mesh_worker.error.connect(self.log)
        self.mesh_worker.log_msg.connect(self.log)
        self.mesh_worker.start()

    def on_mesh_done(self, msh_file: str, stl_file: str) -> None:
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
        self.log("📊 Iniciando barrido de ángulos...")
        self.input_panel.btn_stop_sweep.setVisible(True)
        if hasattr(self, 'res_plot'):
            self.res_plot.reset()
        
        from .workers import SweepWorker
        self.sweep_worker = SweepWorker(p, self.case_dir)
        self.sweep_worker.log_msg.connect(self.log)
        self.sweep_worker.error.connect(self.log)
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

    def on_stop_sweep(self) -> None:
        if hasattr(self, 'sweep_worker') and self.sweep_worker:
            self.sweep_worker.request_stop()
            self.log("⏳ Solicitando detención del barrido...")
            self.input_panel.btn_stop_sweep.setEnabled(False)
    
    def _on_sweep_progress(self, current: int, total: int) -> None:
        self.log(f"  Progreso: {current}/{total}")
    
    def _on_sweep_done(self, aoa_list, cl_list, cd_list, cm_list) -> None:
        self.log(f"✅ Barrido completado: {len(aoa_list)} puntos")
        self.input_panel.btn_stop_sweep.setVisible(False)
        self.input_panel.btn_stop_sweep.setEnabled(True)
        if hasattr(self, 'aero_plot') and aoa_list:
            self.aero_plot.update_plots(aoa_list, cl_list, cd_list, cm_list)
            self.tabs.setCurrentWidget(self.aero_plot)
            self.log("📈 Gráfica polar actualizada en pestaña Cl/Cd.")

    def on_sim_done(self, code: int) -> None:
        self.log(f"🏁 Simulación finalizada (Código {code})")
        self.results_panel.setEnabled(True)
        # Sugerir cargar resultados
        self.log("💡 Puedes pulsar 'Ver Resultados' para visualizar el flujo.")



    def on_residual_data(self, field: str, val: float, time: float) -> None:
        if hasattr(self, 'res_plot'):
            try:
                self.res_plot.update_plot(field, val, time)
            except Exception as e:
                print(f"Error plot residual: {e}")

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
            if "cl" in name_lower:
                self._last_cl = v_float
            elif "cd" in name_lower:
                self._last_cd = v_float
            elif "cm" in name_lower:
                self._last_cm = v_float
            
            # Actualizar gráfica Cl/Cd en tiempo real (punto único)
            if hasattr(self, 'aero_plot'):
                p = self._safe_get_params()
                aoa = p.get("aoa", 0.0) if p else 0.0
                self.aero_plot.update_plots(
                    [aoa], [self._last_cl], [self._last_cd], [self._last_cm]
                )
        except (ValueError, TypeError):
            pass

    def on_results(self) -> None:
        p = self._safe_get_params()
        is_transient = False
        if p and "Transitorio" in p.get("regime", ""):
            is_transient = True
        self.results_panel.load_results(is_transient=is_transient)

    def generate_report(self) -> None:
        p = self._safe_get_params()
        if not p: return
        
        from core.report_generator import generate_pdf_report
        
        self.log("Generando informe PDF...")
        
        images = {}
        # Save plots
        try:
            if hasattr(self, 'res_plot'):
                self.res_plot.figure.savefig("temp_res.png", dpi=150, bbox_inches='tight')
                images["Gráfica de Residuos"] = "temp_res.png"
            if hasattr(self, 'aero_plot'):
                self.aero_plot.figure.savefig("temp_aero.png", dpi=150, bbox_inches='tight')
                images["Curvas Polares"] = "temp_aero.png"
            if hasattr(self, 'cp_plot'):
                self.cp_plot.figure.savefig("temp_cp.png", dpi=150, bbox_inches='tight')
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
        """Limpieza profunda de archivos temporales y residuales."""
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
        
        # Limpiar archivos de malla generados en la raíz
        for f in os.listdir("."):
            if f.startswith("perfil_") and (f.endswith(".msh") or f.endswith(".vtk") or f.endswith(".stl")):
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

        self.log("🛑 Cerrando aplicación y limpiando workspace...")
        if self.solver_runner:
            self.solver_runner.stop()
        self.cleanup()
        event.accept()
