from qtpy.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox, QSlider, QDoubleSpinBox
from qtpy.QtCore import Qt, QTimer, Signal
import pyvista as pv
try:
    from pyvistaqt import QtInteractor
except ImportError:
    QtInteractor = None
from core import paths
from core.postprocessing import PostProcessor
from typing import Optional, Any
import os

# En el orden del selector de campos
CAMPOS = ("U", "p", "k", "nut", "omega", "epsilon", "nuTilda")
TITULOS = {"U": "Velocidad (m/s)", "p": "Presion relativa (m2/s2)", "k": "k (m2/s2)", "nut": "nut (m2/s)",
           "omega": "omega (1/s, escala log)", "epsilon": "epsilon (m2/s3)", "nuTilda": "nuTilda (m2/s)"}
# En la pared omega es del orden de 1e9: en escala lineal todo el dominio saldria de un color.
ESCALA_LOG = ("omega",)
BARRA = {"color": "white", "fmt": "%.3g", "title_font_size": 16, "label_font_size": 14}


class ResultsPanel(QWidget):
    log_signal = Signal(str)

    def __init__(self, case_dir: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        
        # Redirigir errores de VTK a un archivo usando PyVista nativo (sin importar vtk directo que causa SIGKILL en Mac)
        pv.set_error_output_file(paths.temp_path("vtk_errors.log"))
        
        self.case_dir = case_dir
        self.post_processor = None
        self.time_values = []
        self.current_time_idx = 0
        
        main_layout = QVBoxLayout(self)
        
        # --- Top Controls Toolbar ---
        controls_layout = QHBoxLayout()
        
        self.lbl_var = QLabel("Campo mostrado:")
        self.lbl_var.setStyleSheet("font-weight: bold; color: white;")
        self.var_selector = QComboBox()
        self.var_selector.addItems([
            "Velocidad (U) [m/s]", 
            "Presión Relativa (p) [Pa/kg/m³]", 
            "Turbulencia (k)", 
            "Viscosidad Turbulenta (nut)", 
            "Tasa Disipación (omega)",
            "Disipación (epsilon)",
            "Viscosidad Spalart (nuTilda)"
        ])
        self.var_selector.currentIndexChanged.connect(self.update_results_plot)
        self.var_selector.setEnabled(False)
        
        self.btn_screenshot = QPushButton("📸 Guardar Imagen")
        self.btn_screenshot.setStyleSheet("background-color: #3b3b3b; color: white; border-radius: 4px; padding: 6px;")
        self.btn_screenshot.clicked.connect(self.take_screenshot)
        
        self.btn_video = QPushButton("🎥 Guardar Video")
        self.btn_video.setStyleSheet("background-color: #3b3b3b; color: white; border-radius: 4px; padding: 6px;")
        self.btn_video.clicked.connect(self.record_video)
        
        controls_layout.addWidget(self.lbl_var)
        controls_layout.addWidget(self.var_selector)
        controls_layout.addStretch()
        controls_layout.addWidget(self.btn_screenshot)
        controls_layout.addWidget(self.btn_video)
        
        main_layout.addLayout(controls_layout)
        
        # --- PyVista 3D View ---
        self.view_container = QWidget()
        view_layout = QVBoxLayout(self.view_container)
        view_layout.setContentsMargins(0, 0, 0, 0)
        
        # Sin servidor gráfico real, VTK crea un vtkCocoaRenderWindow y provoca
        # SIGSEGV (no es una excepción capturable). En CI/headless se desactiva.
        headless = os.environ.get("QT_QPA_PLATFORM", "").lower() in ("offscreen", "minimal")

        if QtInteractor is not None and not headless:
            try:
                self.plotter = QtInteractor(self.view_container)
                self.plotter.set_background('#121212')
                self.plotter.enable_parallel_projection()
                self.plotter.view_xy()
                view_layout.addWidget(self.plotter)
                self.add_watermark()
            except Exception as e:
                self.plotter = None
                view_layout.addWidget(QLabel(f"Error al iniciar motor 3D: {e}"))
        else:
            self.plotter = None
            reason = "modo headless" if QtInteractor is not None else "PyVista no disponible"
            view_layout.addWidget(QLabel(f"Vista 3D desactivada ({reason})"))
            
        main_layout.addWidget(self.view_container, stretch=1)
        
        # --- Bottom Transient Player ---
        self.player_widget = QWidget()
        player_layout = QHBoxLayout(self.player_widget)
        player_layout.setContentsMargins(0, 5, 0, 0)
        
        self.lbl_player = QLabel("Reproductor Transitorio:")
        self.lbl_player.setStyleSheet("font-weight: bold; color: white;")
        
        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setMinimum(0)
        self.time_slider.setMaximum(0)
        self.time_slider.setEnabled(False)
        self.time_slider.valueChanged.connect(self.on_slider_changed)
        
        self.lbl_time = QLabel("t = 0.00s")
        self.lbl_time.setMinimumWidth(80)
        self.lbl_time.setAlignment(Qt.AlignCenter)
        self.lbl_time.setStyleSheet("color: white;")
        
        self.btn_first = QPushButton("⏮")
        self.btn_prev = QPushButton("⏪")
        self.btn_play = QPushButton("▶")
        self.btn_next = QPushButton("⏩")
        self.btn_last = QPushButton("⏭")
        
        self.btn_first.clicked.connect(self.on_play_first)
        self.btn_prev.clicked.connect(self.on_play_prev)
        self.btn_play.clicked.connect(self.on_play_toggle)
        self.btn_next.clicked.connect(self.on_play_next)
        self.btn_last.clicked.connect(self.on_play_last)
        
        for b in [self.btn_first, self.btn_prev, self.btn_play, self.btn_next, self.btn_last]:
            b.setStyleSheet("background-color: #3b3b3b; color: white; border-radius: 4px; padding: 4px; font-size: 14px;")
            player_layout.addWidget(b)
            
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.1, 10.0)
        self.speed_spin.setValue(1.0)
        self.speed_spin.setSingleStep(0.5)
        self.speed_spin.setPrefix("x")
        self.speed_spin.setMaximumWidth(60)
        self.speed_spin.setStyleSheet("background-color: #2d2d2d; color: white;")
        self.speed_spin.valueChanged.connect(self.update_timer_speed)
        
        player_layout.insertWidget(0, self.lbl_player)
        player_layout.insertWidget(1, self.time_slider)
        player_layout.insertWidget(2, self.lbl_time)
        player_layout.insertWidget(8, self.speed_spin)
        
        self.player_widget.setVisible(False)
        main_layout.addWidget(self.player_widget)
        
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self.on_play_next)

    def log(self, text: str) -> None:
        self.log_signal.emit(text)

    def add_watermark(self) -> None:
        if isinstance(self.plotter, QtInteractor):
            self.plotter.add_text("OpenBlade 2D | ITVE-TecNM", 
                                 position='upper_left', 
                                 font_size=10, 
                                 color='#555555', 
                                 name='watermark')

    def _detect_available_fields(self):
        """Campos que existen en el último tiempo con datos del caso."""
        caso = getattr(self.post_processor, 'case_dir', self.case_dir)
        if not os.path.isdir(caso):
            return None
        # Directorio de tiempo más reciente que contenga U
        candidatos = []
        for name in os.listdir(caso):
            try:
                t = float(name)
            except ValueError:
                continue
            if os.path.exists(os.path.join(caso, name, "U")):
                candidatos.append((t, name))
        if not candidatos:
            return None
        d = os.path.join(caso, max(candidatos)[1])
        conocidos = ("U", "p", "k", "nut", "omega", "epsilon", "nuTilda")
        return {f for f in conocidos if os.path.exists(os.path.join(d, f))}

    def load_results(self, is_transient: bool = False) -> bool:
        try:
            self.post_processor = PostProcessor(self.case_dir)
            
            if is_transient:
                times = self.post_processor.get_time_values()
                if not times:
                    self.log("⚠️ No se encontraron tiempos transitorios en la malla.")
                    return False
                
                self.time_values = times
                self.time_slider.setMaximum(len(times) - 1)
                self.time_slider.setValue(len(times) - 1)
                self.time_slider.setEnabled(True)
                self.player_widget.setVisible(True)
                self.current_time_idx = len(times) - 1
            else:
                self.player_widget.setVisible(False)
                self.time_slider.setEnabled(False)
                self.time_values = [0]
                self.current_time_idx = 0
                
            # Detectar qué campos existen realmente en el caso. Con k-omega SST
            # no hay epsilon ni nuTilda; sin esta lista el selector permite
            # elegirlos y el visor pinta la malla gris como respaldo.
            try:
                self._available_fields = self._detect_available_fields()
            except Exception as e:  # noqa: BLE001
                self.log(f"⚠️ No se pudieron detectar los campos: {e}")
                self._available_fields = None

            self._limit_selector()
            self.var_selector.setEnabled(True)
            self._is_first_plot = True
            self.update_results_plot()
            return True
            
        except Exception as e:
            self.log(f"❌ Error al cargar resultados: {e}")
            return False

    def _limit_selector(self) -> None:
        """Con k-omega SST no hay epsilon ni nuTilda: esos campos no se ofrecen."""
        disponibles = getattr(self, '_available_fields', None) or set(CAMPOS)
        modelo = self.var_selector.model()
        for i, campo in enumerate(CAMPOS):
            modelo.item(i).setEnabled(campo in disponibles)
        if CAMPOS[self.var_selector.currentIndex()] not in disponibles:
            primero = next((i for i, c in enumerate(CAMPOS) if c in disponibles), 0)
            self.var_selector.blockSignals(True)
            self.var_selector.setCurrentIndex(primero)
            self.var_selector.blockSignals(False)

    def _frame(self, perfil: Optional[tuple]) -> None:
        """El dominio llega a cientos de cuerdas: la vista inicial enmarca el perfil."""
        self.plotter.view_xy()
        if not perfil:
            return
        xmin, xmax, ymin, ymax = perfil
        cuerda = xmax - xmin
        ancho, alto = self.plotter.window_size
        camara = self.plotter.camera
        cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
        camara.focal_point = (cx, cy, camara.focal_point[2])
        camara.position = (cx, cy, camara.position[2])
        camara.parallel_scale = max(0.7 * cuerda * alto / max(ancho, 1), 0.3 * cuerda)
        self.plotter.renderer.ResetCameraClippingRange()

    def update_visual_preview(self, mesh: Any, show_edges: bool = False, perfil: Optional[tuple] = None) -> None:
        if self.plotter:
            self.plotter.clear()
            self.plotter.add_mesh(mesh, color='#a0a0a0', show_edges=show_edges, edge_color='#333333')
            self._frame(perfil)
            self.add_watermark()

    def update_results_plot(self) -> None:
        if not self.post_processor or not self.plotter:
            return
            
        field_name = CAMPOS[self.var_selector.currentIndex()]

        time_repr = "latestTime"
        if self.player_widget.isVisible() and self.time_values:
            time_repr = str(self.time_values[self.current_time_idx])
            
        try:
            if self.player_widget.isVisible():
                mesh = self.post_processor.get_mesh_at_index(self.current_time_idx)
            else:
                mesh = self.post_processor.get_latest_mesh()
                
            # Verificar si estamos en el estado inicial (Time=0 o sin resultados)
            times = self.post_processor.get_time_values()
            is_initial = len(times) <= 1 or (len(times) == 1 and times[0] == 0)
                
            if mesh:
                cam_pos = self.plotter.camera_position if hasattr(self.plotter, 'camera_position') else None
                self.plotter.clear()
                
                if is_initial:
                    # MODO PREVISUALIZACIÓN DE MALLA (Sólido Gris + Bordes)
                    self.plotter.add_mesh(mesh, color='#a0a0a0', show_edges=True, edge_color='#444444')
                    self.log("ℹ️ Mostrando previsualización de malla (Resultados no disponibles aún).")
                elif field_name == 'U':
                    # Intentar obtener velocidad de point_data o cell_data
                    velocity = mesh.point_data.get('U')
                    if velocity is None:
                        velocity = mesh.cell_data.get('U')
                        if velocity is not None:
                            # Convertir cell_data a point_data
                            mesh = mesh.cell_data_to_point_data()
                            velocity = mesh.point_data.get('U')
                    
                    if velocity is not None:
                        try:
                            # Calcular magnitud con numpy (más robusto que pv.mag)
                            import numpy as np
                            if velocity.ndim == 2 and velocity.shape[1] >= 3:
                                mag_U = np.sqrt(velocity[:, 0]**2 + velocity[:, 1]**2 + velocity[:, 2]**2)
                            elif velocity.ndim == 2 and velocity.shape[1] == 2:
                                mag_U = np.sqrt(velocity[:, 0]**2 + velocity[:, 1]**2)
                            else:
                                mag_U = np.abs(velocity)
                            
                            mesh.point_data['U_mag'] = mag_U
                            self.plotter.add_mesh(mesh, scalars='U_mag', cmap='jet', 
                                                  show_edges=False,
                                                  opacity=1.0,
                                                  show_scalar_bar=True, 
                                                  scalar_bar_args={'title': TITULOS['U'], **BARRA})
                        except Exception as e_mag:
                            self.log(f"⚠️ Error calculando magnitud de velocidad: {e_mag}")
                            self.plotter.add_mesh(mesh, color='#a0a0a0', show_edges=True)
                    else:
                        self.log("⚠️ Campo 'U' no encontrado en los resultados.")
                        self.plotter.add_mesh(mesh, color='#a0a0a0', show_edges=True)
                else:
                    # Para campos escalares (p, k, nut, omega, epsilon, nuTilda)
                    scalar_data = mesh.point_data.get(field_name)
                    if scalar_data is None:
                        scalar_data = mesh.cell_data.get(field_name)
                        if scalar_data is not None:
                            mesh = mesh.cell_data_to_point_data()
                    
                    if field_name in mesh.point_data:
                        self.plotter.add_mesh(mesh, scalars=field_name, cmap='jet', 
                                              show_edges=False,
                                              log_scale=field_name in ESCALA_LOG,
                                              show_scalar_bar=True, 
                                              scalar_bar_args={'title': TITULOS[field_name], **BARRA})
                    else:
                        self.log(f"⚠️ Campo '{field_name}' no encontrado.")
                        self.plotter.add_mesh(mesh, color='#a0a0a0', show_edges=True)
                        
                if getattr(self, '_is_first_plot', True):
                    self._frame(self.post_processor.airfoil_bounds())
                    self._is_first_plot = False
                elif cam_pos:
                    self.plotter.camera_position = cam_pos
                self.add_watermark()
        except Exception as e:
            self.log(f"⚠️ Error visualizando campo en t={time_repr}: {e}")
            import traceback
            traceback.print_exc()

    def on_slider_changed(self, value: int) -> None:
        if 0 <= value < len(self.time_values):
            self.current_time_idx = value
            t_val = self.time_values[value]
            self.lbl_time.setText(f"t = {t_val}s")
            # Update plot only if not playing rapidly (debouncing in real app, but direct here)
            self.update_results_plot()

    def on_play_first(self) -> None:
        self.time_slider.setValue(0)

    def on_play_prev(self) -> None:
        val = self.time_slider.value()
        if val > 0: self.time_slider.setValue(val - 1)

    def on_play_next(self) -> None:
        val = self.time_slider.value()
        if val < self.time_slider.maximum():
            self.time_slider.setValue(val + 1)
        else:
            if self.play_timer.isActive():
                self.play_timer.stop()
                self.btn_play.setText("▶")

    def on_play_last(self) -> None:
        self.time_slider.setValue(self.time_slider.maximum())

    def on_play_toggle(self) -> None:
        if self.play_timer.isActive():
            self.play_timer.stop()
            self.btn_play.setText("▶")
        else:
            if self.time_slider.value() == self.time_slider.maximum():
                self.time_slider.setValue(0)
            self.play_timer.start(int(500 / self.speed_spin.value()))
            self.btn_play.setText("⏸")

    def update_timer_speed(self) -> None:
        if self.play_timer.isActive():
            self.play_timer.setInterval(int(500 / self.speed_spin.value()))

    def take_screenshot(self) -> None:
        if not self.plotter: return
        from qtpy.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getSaveFileName(self, "Guardar Imagen", "resultados.png", "Imagen PNG (*.png)")
        if not filename:
            return
        if not filename.endswith(".png"):
            filename += ".png"
        try:
            self.plotter.screenshot(filename, window_size=(1920, 1080))
            self.log(f"✅ Captura guardada en {filename} (1920x1080).")
        except Exception as e:
            self.log(f"Error al guardar captura: {e}")

    def _frame_has_field(self, t: float) -> bool:
        """¿Existe el campo activo en el directorio de este tiempo?"""
        try:
            case_dir = getattr(self.post_processor, 'case_dir', None)
            if not case_dir:
                from core import paths
                case_dir = paths.case_dir()
            name = CAMPOS[self.var_selector.currentIndex()]
            if abs(t) < 1e-12:
                return True
            for cand in (f"{t:g}", f"{t:.6f}", repr(t)):
                d = os.path.join(case_dir, cand)
                if os.path.isdir(d):
                    return os.path.exists(os.path.join(d, name))
            return False
        except Exception:
            return True   # ante la duda, no omitir

    def record_video(self) -> None:
        if not self.plotter or not self.time_values:
            return
            
        from qtpy.QtWidgets import QFileDialog, QMessageBox
        filename, _ = QFileDialog.getSaveFileName(self, "Guardar Video", "simulacion.mp4", "Video Files (*.mp4)")
        if not filename: return
        
        if not filename.endswith(".mp4"):
            filename += ".mp4"
            
        self.log(f"Iniciando grabación de video en {filename}...")
        try:
            was_playing = self.play_timer.isActive()
            if was_playing:
                self.play_timer.stop()
                self.btn_play.setText("▶")
            
            orig_idx = self.current_time_idx
            orig_cam = self.plotter.camera_position if hasattr(self.plotter, 'camera_position') else None
            
            # The framerate scales with the speed spinbox
            fps = int(10 * self.speed_spin.value())
            if fps < 1: fps = 1
            self.plotter.open_movie(filename, framerate=fps, quality=5)
            
            from qtpy.QtWidgets import QApplication
            omitidos = 0
            for i in range(len(self.time_values)):
                self.current_time_idx = i
                t_val = self.time_values[i]
                self.lbl_time.setText(f"t = {t_val}s")

                # Se comprueba que el campo exista antes de capturar: si falta,
                # el fotograma saldría con la malla gris y rompería la
                # continuidad del vídeo.
                if not self._frame_has_field(t_val):
                    omitidos += 1
                    continue

                self.update_results_plot()
                
                # Procesar eventos de Qt para forzar el repintado del buffer antes de capturar el frame
                QApplication.processEvents()
                
                if hasattr(self.plotter, 'render'):
                    self.plotter.render()
                self.plotter.write_frame()
                
            if hasattr(self.plotter, 'mwriter'):
                self.plotter.mwriter.close()
            if omitidos:
                self.log(f"ℹ️ {omitidos} fotograma(s) omitido(s) por no tener "
                         f"campos guardados en ese tiempo.")
            self.log(f"✅ Video guardado exitosamente: {filename}")
            
            self.current_time_idx = orig_idx
            self.lbl_time.setText(f"t = {self.time_values[orig_idx]}s")
            self.update_results_plot()
            if orig_cam:
                self.plotter.camera_position = orig_cam
                
        except Exception as e:
            self.log(f"❌ Error al guardar video: {e}")
