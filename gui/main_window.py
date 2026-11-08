from qtpy.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QSplitter, QTextEdit, QLabel, QLineEdit, QScrollArea, QTabWidget, QFileDialog, 
    QMenuBar, QMenu, QAction, QMessageBox, QToolBar)
from qtpy.QtCore import Qt, Signal, QTimer, QCoreApplication, QMutex
from qtpy.QtGui import QCloseEvent, QTextCursor
from typing import Optional, Dict, Any
import json
import os
import threading
import pyvista as pv
import numpy as np
import gmsh

from .input_panel import InputPanel
from .results_panel import ResultsPanel
from .plots import ResidualPlot, AeroPlot, PressurePlot
from .workers import MeshWorker
from .jobs_panel import JobsPanel

from core import owner, paths
from core.geometry import NacaGeometry
from core.jobs import (ACTIVOS, CORRIENDO, DETENIDO, Dispatcher, Events, FINALES, FALLIDO, LOCAL,
                       PENDIENTE, ensure_mesh, load_jobs, new_job, profile_name)
from core.meshing import NacaMesher
import time


class _EventosVentana(Events):
    """Pasa lo que cuentan los trabajos al hilo de la interfaz."""

    def __init__(self, ventana: "MainWindow") -> None:
        self.ventana = ventana

    def state(self, job) -> None:
        self.ventana._job_changed.emit(job.id)

    def log(self, job, texto) -> None:
        self.ventana._job_log.emit(job.id, texto)

    def residual(self, job, campo, valor, t) -> None:
        self.ventana._job_residual.emit(job.id, campo, valor, t)

    def force(self, job, nombre, valor) -> None:
        self.ventana._job_force.emit(job.id, nombre, valor)


class MainWindow(QMainWindow):
    # Señal para devolver al hilo de la GUI los datos leídos en segundo plano.
    _conv_ready = Signal(object)
    _job_changed = Signal(str)
    _job_log = Signal(str, str)
    _job_residual = Signal(str, str, float, float)
    _job_force = Signal(str, str, str)

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

        # Los datos generados viven FUERA del repositorio. Ver core/paths.py.
        # Antes se escribían en el CWD, que al lanzar desde la raíz del repo
        # ensuciaba el árbol y hacía que Google Drive sincronizara cientos de
        # MB de resultados en cada simulación.
        from core import paths
        self._data_root = paths.data_root()
        self.case_dir = paths.case_dir()
            
        self._has_unsaved_work = False
        self.mesh_worker = None
        self._current_aoa = 0.0
        self._sim_running = False
        self.dispatcher = Dispatcher(_EventosVentana(self))
        self.current_job = None
        # Historia en vivo de cada trabajo, para verlo aunque se seleccione despues.
        self._vivo: Dict[str, Dict[str, Any]] = {}
        
        self.mesh_lock = QMutex()
        
        # Datos de fuerza para simulación en punto único
        self._last_cl = 0.0
        self._last_cd = 0.0
        self._last_cm = 0.0

        
        self.init_ui()
        # No se limpia al iniciar: borraría la malla y los resultados del usuario.
        # La limpieza de temporales ocurre al cerrar.
        self.log_signal.connect(self.log)
        self._restore_jobs()
        
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
        
        ficha_action = QAction("Ver ficha del caso", self)
        ficha_action.triggered.connect(self.show_ficha)
        file_menu.addAction(ficha_action)

        file_menu.addSeparator()
        
        exit_action = QAction("Salir", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        toolbar = self.addToolBar("Principal")
        btn_report = QAction("📝 Generar Informe PDF", self)
        btn_report.triggered.connect(self.generate_report)
        toolbar.addAction(btn_report)

        btn_banco = QAction("🧪 Banco de Validación", self)
        btn_banco.setToolTip("NACA 0012 a Re = 6e6 frente a NASA TMR y Ladson, por el mismo camino "
                             "que cualquier caso. Usa las máquinas marcadas en la pestaña Trabajos.")
        btn_banco.triggered.connect(self.on_run_bench)
        toolbar.addAction(btn_banco)

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

        # Lo que el programa afirma del ultimo resultado, siempre a la vista.
        self.verdict_banner = QLabel("")
        self.verdict_banner.setWordWrap(True)
        self.verdict_banner.setVisible(False)
        right_layout.addWidget(self.verdict_banner)
        self._job_changed.connect(self._on_job_changed)
        self._job_log.connect(self._on_job_log)
        self._job_residual.connect(self._on_job_residual)
        self._job_force.connect(self._on_job_force)
        
        self.tabs = QTabWidget()
        self.tabs.setElideMode(Qt.ElideNone)
        self.results_panel = ResultsPanel(self.case_dir)
        self.results_panel.log_signal.connect(self.log)
        self.res_plot = ResidualPlot()
        self.aero_plot = AeroPlot()
        self.cp_plot = PressurePlot()
        
        self.tabs.addTab(self.results_panel, "Visualización 3D")
        self.tabs.addTab(self.res_plot, "Residuales")
        self.tabs.addTab(self.aero_plot, "Cl / Cd")
        self.tabs.addTab(self.cp_plot, "Presión (Cp)")
        self.jobs_panel = JobsPanel()
        self.jobs_panel.job_selected.connect(self._select_job)
        self.jobs_panel.stop_requested.connect(self._stop_job)
        self.jobs_panel.remove_requested.connect(self._remove_job)
        self.jobs_panel.machines_changed.connect(self._sync_machines)
        self.tabs.addTab(self.jobs_panel, "Trabajos")

        # Panel de monitorización remota: estado de la simulación y carga del
        # servidor. Requiere una clave SSH sin contraseña al equipo remoto;
        # si no la hay, el panel lo indica y no interfiere con el resto.
        try:
            from .remote_monitor import RemoteMonitorPanel
            self.remote_panel = RemoteMonitorPanel(
                remote=os.environ.get("OPENBLADE_REMOTE", ""),
                case=os.environ.get("OPENBLADE_REMOTE_CASE", "openfoam_case"))
            self.tabs.addTab(self.remote_panel, "Servidor")
        except Exception as e:  # noqa: BLE001
            self.remote_panel = None
            print(f"Panel remoto no disponible: {e}")

        # Cargar la convergencia de una corrida existente y refrescarla
        # periódicamente. La lectura del run.log corre en un hilo aparte: un
        # log de decenas de MB leído en el hilo de la interfaz congelaba la
        # ventana (se observó al 17% de CPU sin responder).
        from qtpy.QtCore import QTimer
        self._conv_ready.connect(self._apply_convergence)
        self._conv_timer = QTimer(self)
        self._conv_timer.timeout.connect(self._refresh_convergence)
        self._conv_timer.start(15000)
        self._refresh_convergence()

        # Solo se refresca mientras la pestaña de Residuales está visible.
        self.tabs.currentChanged.connect(self._on_tab_changed)
        
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
        """Añade una línea a la consola. Seguro durante el arranque temprano."""
        console = getattr(self, "log_console", None)
        if console is None:
            print(text)
            return
        console.append(text)
        try:
            console.moveCursor(QTextCursor.MoveOperation.End)
            console.ensureCursorVisible()
        except Exception:
            pass
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
            geom_out = paths.temp_path("temp_geom.vtk")
            cmd = [sys.executable, "-m", "core.geom_script", str(naca_val), str(p['chord']), str(p['aoa']), geom_out]
            if is_custom and file_path:
                cmd.append(str(file_path))
            from .workers import subprocess_env
            # stdin=DEVNULL es obligatorio: al lanzar la GUI con nohup/desacoplada,
            # el descriptor de entrada está cerrado y el hijo hereda un fd
            # inválido. Python aborta al arrancar con
            # "init_sys_streams: can't initialize sys standard streams".
            # Los tres descriptores se fijan explícitamente.
            #
            # Al lanzar la GUI con nohup/disown, los fds 0, 1 y 2 pueden no ser
            # válidos en el momento de crear el hijo. Python aborta entonces
            # con:
            #   Fatal Python error: init_sys_streams: can't initialize sys
            #   standard streams / OSError: [Errno 9] Bad file descriptor
            # capture_output ya redirige stdout/stderr; stdin se fija a DEVNULL.
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace',
                                    stdin=subprocess.DEVNULL,
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
            _g = paths.temp_path("temp_geom.vtk")
            if os.path.exists(_g):
                mesh = pv.read(_g)
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
        msh_file = paths.mesh_path(p['naca'] or "custom")
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

    def _airfoil_extent(self) -> tuple:
        """Donde esta el perfil en la vista previa de la malla, que no lleva sus patches."""
        c = float((self._safe_get_params() or {}).get("chord", 1.0))
        return (0.0, c, -0.1 * c, 0.1 * c)

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
                    self.results_panel.update_visual_preview(mesh, show_edges=True, perfil=self._airfoil_extent())
                elif os.path.exists(stl_file):
                    import pyvista as pv
                    mesh = pv.read(stl_file)
                    self.results_panel.update_visual_preview(mesh, show_edges=True)
            except Exception as e:
                self.log(f"Aviso visualización: {e}")

    def on_run_sim(self) -> None:
        """Envia un paquete. Cada clic es un trabajo nuevo con su propia carpeta."""
        p = self._safe_get_params()
        if not p: return

        destino = self._destino(p)
        if destino is None:
            return
        if "Barrido" in p.get("analysis_mode", ""):
            self._run_sweep(p, destino)
            return
        if "Estudio" in p.get("analysis_mode", ""):
            self._run_grid_study(p, destino)
            return
        self._lanzar(new_job(p, *destino))

    def _destino(self, p: Dict[str, Any]):
        """(maquina, procesos) del paquete; None si no se puede enviar."""
        modo = p.get("exec_mode")
        if modo == "server":
            if not self._check_server(p):
                return None
            self.jobs_panel.add_machine(p["server_host"], int(p.get("server_nproc", 4)))
            return p["server_host"], int(p.get("server_nproc", 4))
        if modo == "repartir":
            if not self.jobs_panel.machines():
                self.log("❌ Marca al menos una máquina en la pestaña Trabajos.")
                self.tabs.setCurrentWidget(self.jobs_panel)
                return None
            return "", 0
        return LOCAL, int(p.get("server_nproc", 4))

    def _sync_machines(self) -> None:
        self.dispatcher.set_machines(self.jobs_panel.all_machines())
        if getattr(self, "remote_panel", None) is not None:
            self.remote_panel.set_hosts([m.host for m in self.jobs_panel.all_machines()])

    def _lanzar(self, job) -> None:
        self._has_unsaved_work = True
        self.jobs_panel.add_job(job)
        self._sync_machines()
        self.dispatcher.jobs[job.id] = job
        self._select_job(job.id)
        self.dispatcher.submit(job)

    def _restore_jobs(self) -> None:
        """Al abrir: lista lo anterior y retoma solo lo que no lleva otro proceso.

        La linea de comandos usa el mismo directorio de trabajos. Si la ventana
        reenviara lo que ya esta en su cola, el paquete saldria dos veces.
        """
        ultimo = None
        reenviar = []
        ajenos = []
        sin_dueno = []
        # Un trabajo anterior a esto no tiene archivo de dueno. Si hay una campana en la
        # linea de ordenes, reenviarlo podria duplicar el paquete: se avisa y no se toca.
        otro_cli = owner.hay_cli_vivo()
        for job in load_jobs()[-200:]:
            self.dispatcher.jobs[job.id] = job
            self.jobs_panel.add_job(job)
            ultimo = job
            if job.state in FINALES:
                continue
            dueno = owner.de_otro(job)
            if dueno is not None:
                # No se toca: se muestra quien lo lleva y se deja en paz.
                ajenos.append((job, dueno))
                continue
            if job.state == PENDIENTE or (job.state in ACTIVOS and not job.remote_dir):
                if otro_cli and owner.leer(job) is None:
                    sin_dueno.append(job)
                    continue
                # Se cerro la ventana antes de que saliera de esta maquina: vuelve a la cola.
                job.state, job.step = PENDIENTE, ""
                job.save()
                reenviar.append(job)
            elif job.state in ACTIVOS:
                self.log(f"🔌 {job.label} seguía en {job.host}: se vuelve a seguir.")
                self.dispatcher.attach(job)
        self._sync_machines()
        if ajenos:
            self.log(f"⏸️ {len(ajenos)} trabajos los lleva otro proceso: no se tocan. "
                     f"Se pueden ver, pero para detenerlos hay que usar el proceso que los lanzó.")
            for job, dueno in ajenos:
                self.log(f"   {job.label}: {owner.describir(dueno)}")
        if sin_dueno:
            self.log(f"⏸️ Hay una campaña viva en la línea de órdenes y {len(sin_dueno)} paquete(s) "
                     f"antiguos sin dueño anotado: no se reenvían, por si son suyos. Ciérrala o "
                     f"espera a que acabe, y vuelve a abrir la ventana.")
            for job in sin_dueno:
                self.log(f"   {job.label}: {job.state}")
        if reenviar:
            self.log(f"📤 {len(reenviar)} paquetes no habían salido de esta computadora: vuelven a la cola.")
        for job in reenviar:
            self.dispatcher.submit(job)
        if ultimo is not None:
            self._select_job(ultimo.id)

    def _select_job(self, job_id: str) -> None:
        """Lo que muestra la ventana pasa a ser este trabajo."""
        job = self.dispatcher.jobs.get(job_id)
        if job is None:
            return
        self.current_job = job
        self.case_dir = job.case_dir
        os.makedirs(self.case_dir, exist_ok=True)
        self.results_panel.case_dir = self.case_dir
        self.jobs_panel.select_row(job_id)
        self._watch_on_server(job)
        self._current_aoa = float(job.params.get("aoa", 0.0))
        self._sim_transient = job.transient
        self._sim_end_time = (float(job.params.get("end_time", 0.5)) if job.transient
                              else float(job.params.get("max_iters", 500)))
        self._sim_t0 = job.started or time.time()
        self._sim_steps = 0
        self._last_t = -1.0
        self._paused = False
        self.res_plot.reset()
        self.res_plot.case_dir = self.case_dir
        self.res_plot._end_time = None
        self.res_plot.estacionario = not job.transient
        vivo = self._vivo.get(job_id, {})
        for campo, valor, t in vivo.get("residuales", ()):
            self.res_plot.update_plot(campo, valor, t)
        if job.state in FINALES and job.analysis:
            self._show_analysis((job.analysis, job.rc or 0))
        elif job.state in FINALES:
            self._set_banner("SIN DATOS", f"❓ {job.state}: {job.error or 'sin resultados'}")
        else:
            self.verdict_banner.setVisible(False)
            self._last_cl = self._last_cd = self._last_cm = 0.0
            self.aero_plot.update_plots([], [], [], [], [])
            if job.group:
                self._update_group(job.group)
        self._refresh_run_controls()

    def _watch_on_server(self, job) -> None:
        """La pestaña Servidor muestra el trabajo a la vista, si corre en un servidor."""
        if self.remote_panel is not None and job.remote_dir and job.host != LOCAL:
            self.remote_panel.watch(job.host, "~/" + job.remote_dir)

    def _refresh_run_controls(self) -> None:
        job = self.current_job
        activo = job is not None and (job.state in ACTIVOS or job.state == PENDIENTE)
        corriendo = job is not None and job.state == CORRIENDO
        panel = self.input_panel
        panel.btn_stop_sim.setVisible(activo)
        panel.btn_stop_sim.setEnabled(activo)
        panel.btn_pause_sim.setVisible(corriendo)
        panel.btn_pause_sim.setText("▶️ Reanudar" if getattr(self, "_paused", False) else "⏸️ Pausar")
        grupo = job.group if job is not None else ""
        panel.btn_stop_sweep.setVisible(any(
            j.group == grupo and j.state not in FINALES for j in self.dispatcher.jobs.values())
            if grupo else False)
        panel.progress_label.setVisible(activo)
        if activo and job.state != CORRIENDO:
            panel.progress_label.setText(f"{job.label}: {job.state}")

    def _on_job_changed(self, job_id: str) -> None:
        job = self.dispatcher.jobs.get(job_id)
        if job is None:
            return
        self.jobs_panel.update_job(job)
        if job.group and job.state in FINALES:
            # Un grupo se presenta completo, no como su ultimo trabajo.
            self._update_group(job.group)
        if job is self.current_job:
            self._sim_t0 = job.started or self._sim_t0
            if job.state in FINALES and not job.group:
                if job.analysis:
                    self._show_analysis((job.analysis, job.rc or 0))
                else:
                    self._set_banner("SIN DATOS", f"❓ {job.state}: {job.error or 'sin resultados'}")
            self._refresh_run_controls()
            if job.state == CORRIENDO and job.step:
                self.log(f"🖥️ {job.label}: {job.step}")
                if job.step in ("verificando", "inicio"):
                    self._watch_on_server(job)

    def _on_job_log(self, job_id: str, texto: str) -> None:
        job = self.dispatcher.jobs.get(job_id)
        if job is not None:
            self.log(f"[{job.label}] {texto}")

    def _on_job_residual(self, job_id: str, campo: str, valor: float, t: float) -> None:
        serie = self._vivo.setdefault(job_id, {}).setdefault("residuales", [])
        serie.append((campo, valor, t))
        if len(serie) > 40000:
            del serie[:len(serie) - 40000]
        if self.current_job is not None and job_id == self.current_job.id:
            self.on_residual_data(campo, valor, t)

    def _on_job_force(self, job_id: str, nombre: str, valor: str) -> None:
        if self.current_job is not None and job_id == self.current_job.id:
            self.on_force_data(nombre, valor)

    def _stop_job(self, job_id: str) -> None:
        def trabajo():
            try:
                self.dispatcher.stop(job_id)
            except Exception as e:  # noqa: BLE001
                self.log_signal.emit(f"⚠️ No se pudo detener: {e}")

        threading.Thread(target=trabajo, daemon=True).start()

    def _remove_job(self, job_id: str) -> None:
        job = self.dispatcher.jobs.get(job_id)
        if job is None:
            return
        if job.state not in FINALES:
            self.log("⚠️ Ese trabajo sigue activo: deténlo antes de borrarlo.")
            return
        boton = QMessageBox.question(self, "Borrar trabajo",
                                     f"¿Borrar la carpeta local de {job.label}?\n{job.folder}")
        if boton != QMessageBox.Yes:
            return
        self.jobs_panel.remove_job(job_id)
        self.dispatcher.remove_local(job_id)
        if job is self.current_job:
            self.current_job = None

    def _check_server(self, p: Dict[str, Any]) -> bool:
        from core.remote_runner import RemoteError, validar_host
        try:
            validar_host(p.get("server_host", ""))
        except RemoteError as e:
            self.log(f"❌ {e}")
            return False
        self.input_panel.remember_server(p["server_host"])
        return True

    def _run_sweep(self, p: Dict[str, Any], destino) -> None:
        """Un paquete por angulo: se reparten y la polar se completa al terminar cada uno."""
        import secrets
        angulos, a = [], float(p.get("aoa_min", -4.0))
        while a <= float(p.get("aoa_max", 24.0)) + 1e-6:
            angulos.append(round(a, 2))
            a += float(p.get("aoa_step", 2.0))
        grupo = f"polar_{secrets.token_hex(3)}"
        self.log(f"📊 Barrido: {len(angulos)} paquetes, de {angulos[0]}° a {angulos[-1]}°")
        self.aero_plot.update_plots([], [], [], [], [])
        for angulo in angulos:
            q = dict(p, aoa=angulo, regime="Estacionario (simpleFoam)")
            self._lanzar(new_job(q, *destino, group=grupo))

    def _run_grid_study(self, p: Dict[str, Any], destino) -> None:
        """Tres niveles anidados del mismo caso; al terminar, el GCI de Cl y Cd."""
        import secrets
        from core.campaign import chain_levels, grid_study_cases
        grupo = f"malla_{secrets.token_hex(3)}"
        self.log(f"📐 Estudio de malla a α = {p.get('aoa', 0)}°: 225×65, 449×129 y 897×257, "
                 "cada una desde la solución de la anterior")
        trabajos = [new_job(q, *destino, group=grupo, label=f"{profile_name(q)}_a{q.get('aoa', 0)}_Re{float(q.get('reynolds', 1e6)) / 1e6:g}e6_malla_n{q['grid_level']}")
                    for q in grid_study_cases(dict(p, analysis_mode="Punto Único"))]
        chain_levels(trabajos)
        for trabajo in trabajos:
            self._lanzar(trabajo)

    def on_run_bench(self) -> None:
        """Lanza el banco de validacion con las maquinas marcadas."""
        import secrets
        from core.bench import case_parameters, default_cases
        if not self.jobs_panel.machines():
            self.log("❌ Marca al menos una máquina en la pestaña Trabajos.")
            self.tabs.setCurrentWidget(self.jobs_panel)
            return
        casos = default_cases()
        if QMessageBox.question(self, "Banco de validación",
                                f"Se lanzan {len(casos)} paquetes en las máquinas marcadas. ¿Continuar?"
                                ) != QMessageBox.Yes:
            return
        grupo = f"banco_{secrets.token_hex(3)}"
        for c in casos:
            self._lanzar(new_job(case_parameters(c), group=grupo, label=c.etiqueta))

    def _update_group(self, grupo: str) -> None:
        if grupo.startswith("banco_"):
            self._update_bench(grupo)
        elif grupo.startswith("malla_"):
            self._update_grid_study(grupo)
        else:
            self._update_polar(grupo)

    def _trabajos_del_grupo(self, grupo: str):
        trabajos = [j for j in self.dispatcher.jobs.values() if j.group == grupo]
        return trabajos, [j for j in trabajos if j.state in FINALES]

    def _update_grid_study(self, grupo: str) -> None:
        from core.campaign import grid_study_result, grid_study_text
        from core.verdict import CONVERGIDO, NO_CONVERGIDO
        trabajos, hechos = self._trabajos_del_grupo(grupo)
        if len(hechos) < len(trabajos):
            self._set_banner("EN CURSO", f"📐 Estudio de malla: {len(hechos)} de {len(trabajos)} niveles terminados.")
            return
        r = grid_study_result(trabajos)
        self._set_banner(NO_CONVERGIDO if "motivo" in r else CONVERGIDO, f"📐 {grid_study_text(r)}")
        self.log(f"📐 {grid_study_text(r)}")

    def _update_bench(self, grupo: str) -> None:
        from core.bench import case_of_job, summarize, write_report
        from core.verdict import CONVERGIDO, NO_CONVERGIDO
        trabajos, hechos = self._trabajos_del_grupo(grupo)
        if len(hechos) < len(trabajos):
            self._set_banner("EN CURSO", f"🧪 Banco: {len(hechos)} de {len(trabajos)} paquetes terminados.")
            return
        r = summarize([case_of_job(j) for j in trabajos], trabajos)
        ruta = write_report(r, os.path.join(paths.results_dir(), grupo))
        bien = r["cumplidas"] == r["total"] and not r["sin_converger"]
        self._set_banner(CONVERGIDO if bien else NO_CONVERGIDO,
                         f"🧪 Banco: {r['cumplidas']} de {r['total']} comprobaciones cumplidas"
                         + (f"; sin converger: {', '.join(r['sin_converger'])}" if r["sin_converger"] else "")
                         + f".\nInforme: {ruta}")
        self.log(f"🧪 Informe del banco: {ruta}")

    def _update_polar(self, grupo: str) -> None:
        """La polar con lo que ya termino, cada punto con su veredicto."""
        from collections import Counter
        from core.verdict import CONVERGIDO, DIVERGIDO, NO_CONVERGIDO, SIN_DATOS
        trabajos = sorted((j for j in self.dispatcher.jobs.values() if j.group == grupo),
                          key=lambda j: float(j.params.get("aoa", 0.0)))
        hechos = [j for j in trabajos if j.state in FINALES]
        aoa, cl, cd, cm, estados = [], [], [], [], []
        for j in hechos:
            v = (j.analysis or {}).get("verdict") or {}
            estado = v.get("state", SIN_DATOS)
            valido = estado in (CONVERGIDO, NO_CONVERGIDO) and v.get("cl") is not None
            aoa.append(float(j.params.get("aoa", 0.0)))
            estados.append(estado)
            cl.append(v["cl"] if valido else None)
            cd.append(v["cd"] if valido else None)
            cm.append(v["cm"] if valido else None)
        self.aero_plot.update_plots(aoa, cl, cd, cm, estados)
        cuenta = Counter(estados)
        resumen = ", ".join(f"{cuenta[e]} {e}" for e in
                            (CONVERGIDO, NO_CONVERGIDO, DIVERGIDO, SIN_DATOS) if cuenta[e])
        faltan = len(trabajos) - len(hechos)
        if faltan:
            self._set_banner("EN CURSO", f"📊 Barrido: {resumen or 'sin resultados aún'}; "
                                         f"faltan {faltan} de {len(trabajos)}.")
            return
        malos = len(estados) - cuenta[CONVERGIDO]
        self._set_banner(CONVERGIDO if not malos else NO_CONVERGIDO,
                         f"📊 Barrido: {resumen}."
                         + (" Los puntos huecos no convergieron y los divergidos no se dibujan."
                            if malos else ""))
        self.log(f"📊 Barrido terminado: {resumen}")
        self.tabs.setCurrentWidget(self.aero_plot)

    def _on_sweep_mesh(self, vtk_file: str) -> None:
        """Actualiza la vista 3D durante un barrido."""
        if os.path.exists(vtk_file):
            import pyvista as pv
            try:
                mesh = pv.read(vtk_file)
                self.results_panel.update_visual_preview(mesh, show_edges=True, perfil=self._airfoil_extent())
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

        msh = paths.mesh_path(p.get('naca') or 'custom')
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
            # Carpeta propia: FsiRunner reescribe el caso que recibe.
            trabajo = new_job(p, LOCAL, label="fsi")
            os.makedirs(trabajo.case_dir, exist_ok=True)
            runner = FsiRunner(trabajo.case_dir, dict(p, msh_file=msh), log=self.log)
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
        """Pausa o reanuda el trabajo a la vista sin perder su estado."""
        job = self.current_job
        if job is None:
            return
        pausar = not getattr(self, "_paused", False)
        try:
            self.dispatcher.set_paused(job.id, pausar)
        except Exception as e:  # noqa: BLE001
            self.log(f"⚠️ No se pudo cambiar la pausa: {e}")
            return
        self._paused = pausar
        self.input_panel.btn_pause_sim.setText("▶️ Reanudar" if pausar else "⏸️ Pausar")
        self.log("⏸️ Pausada." if pausar else "▶️ Reanudada.")

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
        pct = min(100.0, 100.0 * t_current / end)
        transitorio = getattr(self, "_sim_transient", False)

        if n_steps > 0 and t_current > 0:
            min_por_avance = elapsed_min / t_current
            eta = max(0.0, end - t_current) * min_por_avance
            eta_txt = f"{eta / 60:.1f} h" if eta > 90 else f"{eta:.0f} min"
            ritmo = (f"{n_steps} pasos en {elapsed_min:.0f} min" if transitorio else
                     f"{60 * t_current / max(elapsed_min * 60, 1e-6):.0f} iter/min")
        else:
            eta_txt, ritmo = "—", "—"

        ahora = time.strftime("%H:%M")
        inicio = time.strftime("%H:%M", time.localtime(t0))
        estado = "⏸ PAUSADA" if getattr(self, "_paused", False) else "▶ en marcha"
        avance = (f"t = {t_current:.4g} de {end:g} s" if transitorio
                  else f"iteración {t_current:.0f} de {end:.0f}")

        lbl.setText(
            f"{estado}   {inicio} → {ahora}  ({elapsed_min:.0f} min)\n"
            f"Progreso:  {avance}   ({pct:.1f}%)\n"
            f"Falta:     {100 - pct:.1f}%   ·   ETA ~{eta_txt}\n"
            f"Ritmo:     {ritmo}"
        )

    def on_stop_sim(self) -> None:
        """Detiene el trabajo a la vista."""
        if self.current_job is None:
            return
        self.log(f"⏳ Deteniendo {self.current_job.label}...")
        self.input_panel.btn_stop_sim.setEnabled(False)
        self._stop_job(self.current_job.id)

    def on_stop_sweep(self) -> None:
        """Detiene todos los paquetes del barrido a la vista."""
        grupo = self.current_job.group if self.current_job else ""
        self.log("⏳ Deteniendo el barrido...")
        self.input_panel.btn_stop_sweep.setEnabled(False)
        for job in list(self.dispatcher.jobs.values()):
            if grupo and job.group == grupo and job.state not in FINALES:
                self._stop_job(job.id)

    def _reset_run_state(self) -> None:
        self._sim_running = False
        self.input_panel.btn_run.setEnabled(True)
        self.input_panel.btn_stop_sweep.setVisible(False)
        self.input_panel.btn_stop_sweep.setEnabled(True)
        self.input_panel.btn_stop_sim.setVisible(False)
        self.input_panel.btn_stop_sim.setEnabled(True)
        self.input_panel.btn_pause_sim.setVisible(False)

    def _set_banner(self, estado: str, texto: str) -> None:
        from core.verdict import CONVERGIDO, DIVERGIDO, NO_CONVERGIDO
        fondo = {CONVERGIDO: "#1b5e20", NO_CONVERGIDO: "#b26a00",
                 DIVERGIDO: "#b71c1c"}.get(estado, "#37474f")
        self.verdict_banner.setStyleSheet(
            f"background: {fondo}; color: white; padding: 8px; border-radius: 4px; "
            "font-size: 12px;")
        self.verdict_banner.setText(texto)
        self.verdict_banner.setVisible(True)

    def _show_analysis(self, datos) -> None:
        """Presenta el veredicto; ningun coeficiente sale sin el."""
        from core.verdict import CONVERGIDO, DIVERGIDO, NO_CONVERGIDO, Verdict
        analisis, code = datos
        self._last_code = code
        v = Verdict(**analisis["verdict"])
        icono = {CONVERGIDO: "✅", NO_CONVERGIDO: "⚠️", DIVERGIDO: "💥"}.get(v.state, "❓")
        self.log(f"{icono} {v.state}: {v.reason}")
        self.log(f"   {v.coefficients_text()}")
        lineas = [f"{icono} {v.state}: {v.reason}", v.coefficients_text()]
        if v.state in (CONVERGIDO, NO_CONVERGIDO) and v.cl is not None:
            self._last_cl, self._last_cd, self._last_cm = v.cl, v.cd, v.cm
            self.aero_plot.update_plots([self._current_aoa], [v.cl], [v.cd], [v.cm], [v.state])
        else:
            self._last_cl = self._last_cd = self._last_cm = 0.0
            self.aero_plot.update_plots([], [], [], [], [])
        aviso = analisis.get("yplus_notice")
        if aviso:
            marca = {"ok": "✅", "aviso": "⚠️", "mal": "❌"}.get(aviso["level"], "ℹ️")
            self.log(f"{marca} {aviso['text']}")
            lineas.append(f"{marca} {aviso['text']}")
        from core.surface import surface_text
        sup = surface_text(analisis.get("superficie"), v.cd)
        if sup:
            self.log(f"ℹ️ {sup}")
            lineas.append(f"ℹ️ {sup}")
        malla = analisis.get("mesh_notice")
        if malla:
            marca = {"ok": "✅", "aviso": "⚠️", "mal": "❌"}.get(malla["level"], "ℹ️")
            self.log(f"{marca} {malla['text']}")
            if malla["level"] != "ok":
                lineas.append(f"{marca} {malla['text']}")
        self._set_banner(v.state, "\n".join(lineas))
        if code == 0:
            self.log("💡 Puedes pulsar 'Ver Resultados' para visualizar el flujo.")
            self._refresh_cp_plot()



    def _on_tab_changed(self, index: int) -> None:
        """Activa el refresco sólo cuando se mira la pestaña de Residuales."""
        try:
            activo = self.tabs.widget(index) is self.res_plot
            if activo:
                if not self._conv_timer.isActive():
                    self._conv_timer.start(15000)
                self._refresh_convergence()
            else:
                self._conv_timer.stop()
        except Exception:
            pass

    def _refresh_convergence(self) -> None:
        """Lanza la lectura del log en un hilo, sin bloquear la interfaz."""
        try:
            if getattr(self, "_conv_busy", False):
                return
            log_path = os.path.join(self.case_dir, "run.log")
            if not os.path.exists(log_path):
                return

            self._conv_busy = True

            def trabajo():
                try:
                    datos = self._parse_log(log_path)
                except Exception as e:  # noqa: BLE001
                    datos = ("error", str(e))
                # Señal en lugar de invokeMethod con Q_ARG: Qt no sabe
                # serializar una tupla de Python ("Unable to find a QMetaType
                # for object"), pero una Signal(object) la pasa sin problema.
                self._conv_ready.emit(datos)

            threading.Thread(target=trabajo, daemon=True).start()
        except Exception as e:  # noqa: BLE001
            self._conv_busy = False
            self.log(f"⚠️ No se pudo refrescar la convergencia: {e}")

    def _parse_log(self, log_path: str):
        """Parsea el log fuera del hilo principal. Devuelve datos serializables."""
        import re
        eq_re = re.compile(
            r"Solving for (Ux|Uy|Uz|p|k|omega|epsilon|nuTilda),\s*"
            r"Initial residual = ([-+0-9.eE]+)")
        time_re = re.compile(r"^Time = ([-+0-9.eE]+)")

        bloques = []
        actual = None
        with open(log_path, errors="replace") as fh:
            for ln in fh:
                mt = time_re.match(ln)
                if mt:
                    actual = {"t": float(mt.group(1)), "res": {}}
                    bloques.append(actual)
                elif actual is not None:
                    me = eq_re.search(ln)
                    if me:
                        actual["res"].setdefault(me.group(1), float(me.group(2)))

        # Submuestreo para no dibujar decenas de miles de puntos
        if len(bloques) > 400:
            paso = max(1, len(bloques) // 400)
            bloques = bloques[::paso]
        return ("ok", bloques)

    def _apply_convergence(self, datos) -> None:
        """Aplica en el hilo de la GUI lo que devolvió el hilo de lectura."""
        self._conv_busy = False
        try:
            estado, payload = datos
            if estado == "error":
                self.log(f"⚠️ Error leyendo run.log: {payload}")
                return
            if payload:
                self.res_plot.set_log_path(os.path.join(self.case_dir, "run.log"))
                self.res_plot.set_series(payload)
                self.res_plot.redraw()
        except Exception as e:  # noqa: BLE001
            self.log(f"⚠️ Error aplicando convergencia: {e}")

    def load_convergence_from_log(self) -> None:
        """Carga la curva de residuales de una corrida ya existente.

        Se llama al abrir la app y al refrescar: permite ver la convergencia
        de una simulación lanzada desde fuera (por ejemplo, el caso que corre
        en segundo plano), no sólo la que arranca esta ventana.
        """
        try:
            log_path = os.path.join(self.case_dir, "run.log")
            if not os.path.exists(log_path):
                return
            n = self.res_plot.load_from_log(log_path)
            if n:
                self.res_plot.redraw()
                self.log(f"📈 Convergencia cargada desde run.log ({n} puntos).")
        except Exception as e:  # noqa: BLE001
            self.log(f"⚠️ No se pudo leer run.log: {e}")

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
            p = self.current_job.params if self.current_job else self.input_panel.get_params()
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
        is_transient = self.current_job.transient if self.current_job else False
        if self.results_panel.load_results(is_transient=is_transient):
            self._refresh_cp_plot()

    def generate_report(self) -> None:
        job = self.current_job
        p = job.params if job is not None else self._safe_get_params()
        if not p: return
        
        from core.report_generator import generate_pdf_report
        
        self.log("Generando informe PDF...")
        
        images = {}
        # Save plots
        try:
            if hasattr(self, 'res_plot'):
                images["Gráfica de Residuos"] = paths.temp_path("temp_res.png")
                self.res_plot.fig.savefig(images["Gráfica de Residuos"], dpi=150, bbox_inches='tight')
            if hasattr(self, 'aero_plot'):
                images["Curvas Polares"] = paths.temp_path("temp_aero.png")
                self.aero_plot.fig.savefig(images["Curvas Polares"], dpi=150, bbox_inches='tight')
            if hasattr(self, 'cp_plot'):
                images["Distribución de Cp"] = paths.temp_path("temp_cp.png")
                self.cp_plot.fig.savefig(images["Distribución de Cp"], dpi=150, bbox_inches='tight')
            if self.results_panel.plotter:
                images["Dominio y Malla / Resultados"] = paths.temp_path("temp_mesh.png")
                self.results_panel.plotter.screenshot(images["Dominio y Malla / Resultados"])
        except Exception as e:
            self.log(f"Aviso al guardar imágenes para informe: {e}")
            
        from core.verdict import analyze_case
        analisis = (job.analysis if job is not None and job.analysis else
                    analyze_case(self.case_dir, "pimpleFoam" in p.get("regime", ""),
                                 getattr(self, "_last_code", 0)))
        
        filename, _ = QFileDialog.getSaveFileName(self, "Guardar Informe", "informe_cfd.pdf", "PDF Files (*.pdf)")
        if filename:
            if not filename.endswith(".pdf"):
                filename += ".pdf"
            try:
                from core.package import read_ficha
                generate_pdf_report(filename, p, analisis, images, read_ficha(self.case_dir))
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

    def show_ficha(self) -> None:
        """La ficha del caso: huellas, versiones, parametros, ejecucion y resultado."""
        from qtpy.QtWidgets import QDialog
        from core.package import read_ficha
        ficha = read_ficha(self.case_dir)
        if ficha is None:
            QMessageBox.information(self, "Ficha del caso",
                                    "Este caso aún no tiene ficha: se crea al enviarlo a calcular.")
            return
        dialogo = QDialog(self)
        dialogo.setWindowTitle("Ficha del caso")
        dialogo.resize(760, 640)
        lay = QVBoxLayout(dialogo)
        texto = QTextEdit()
        texto.setReadOnly(True)
        texto.setPlainText(json.dumps(ficha, indent=2, ensure_ascii=False, sort_keys=True))
        lay.addWidget(texto)
        dialogo.exec()

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
        if filename:
            self.load_project_file(filename)

    def load_project_file(self, filename: str) -> None:
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
        """Limpieza de archivos temporales.

        NO borra mallas ni resultados. Antes vaciaba postProcessing y los tiempos
        del caso al cerrar: cerrar la ventana perdia la corrida.
        """
        temp_files = [
            "temp_params_mesh.json", "temp_params_solve.json", "temp_params_sweep.json",
            "temp_geom.vtk", "debug.msh", "debug.vtk", "vtk_errors.log", "debug_gmsh.log",
            "temp_geom.stl"
        ]
        # Solo en la carpeta temporal del programa: nunca donde se abrio la ventana.
        for f in temp_files:
            f = paths.temp_path(f)
            if os.path.exists(f):
                try: os.remove(f)
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
        # Los trabajos siguen en su maquina; al abrir de nuevo se retoman.
        self.dispatcher.detach_all()
        if self.mesh_worker is not None:
            try:
                # Cortar primero el subproceso: wait() solo no lo mata.
                self.mesh_worker.cancel()
                self.mesh_worker.wait(5000)
            except Exception:
                pass
        self.cleanup()
        event.accept()