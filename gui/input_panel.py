from qtpy.QtWidgets import (QWidget, QFormLayout, QLineEdit, QDoubleSpinBox, 
    QVBoxLayout, QGroupBox, QComboBox, QPushButton, QFileDialog, QHBoxLayout,
    QToolButton, QSizePolicy, QFrame, QLayout, QDialog, QDialogButtonBox, QCheckBox, QSpinBox)
from qtpy.QtCore import Qt, QPropertyAnimation, QParallelAnimationGroup
from typing import Optional, Dict, Any


class CollapsibleBox(QWidget):
    """Sección colapsable con título clickeable y animación suave."""
    def __init__(self, title: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        
        self.toggle_button = QToolButton(text=title, checkable=True, checked=True)
        self.toggle_button.setObjectName("collapsibleToggle")
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.DownArrow)
        self.toggle_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toggle_button.clicked.connect(self._toggle)
        
        self.content_area = QWidget()
        self.content_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 4)
        main_layout.addWidget(self.toggle_button)
        main_layout.addWidget(self.content_area)
    
    def _toggle(self, checked: bool) -> None:
        self.toggle_button.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.content_area.setVisible(checked)
    
    def setContentLayout(self, layout: QLayout) -> None:
        self.content_area.setLayout(layout)


class InputPanel(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        from qtpy.QtWidgets import QScrollArea
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        
        self.scroll_content = QWidget()
        layout = QVBoxLayout(self.scroll_content)
        layout.setSpacing(6)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.scroll_area.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll_area, 1)

        
        # ═══════════════════════════════════════════
        # Sección 1: Geometría del Perfil (Colapsable)
        # ═══════════════════════════════════════════
        geom_box = CollapsibleBox("▸ Geometría del Perfil")
        geom_layout = QFormLayout()
        geom_layout.setContentsMargins(8, 8, 8, 8)
        
        self.profile_type = QComboBox()
        self.profile_type.addItems(["NACA 4-dígitos", "Archivo Custom (.txt, .csv)"])
        
        self.naca_input = QLineEdit("0012")
        
        self.file_picker_btn = QPushButton("Seleccionar Archivo...")
        self.file_path_label = QLineEdit("")
        self.file_path_label.setReadOnly(True)
        
        file_box = QHBoxLayout()
        file_box.addWidget(self.file_picker_btn)
        file_box.addWidget(self.file_path_label)
        file_box.setContentsMargins(0, 0, 0, 0)
        self.file_widget = QWidget()
        self.file_widget.setLayout(file_box)
        self.file_widget.setVisible(False)
        
        self.chord_input = QDoubleSpinBox()
        self.chord_input.setRange(0.01, 1000.0)
        self.chord_input.setValue(1.0)
        self.chord_input.setDecimals(3)
        self.chord_input.setSuffix(" m")
        
        self.aoa_input = QDoubleSpinBox()
        self.aoa_input.setRange(-45, 45)
        self.aoa_input.setValue(0.0)
        self.aoa_input.setSuffix(" °")

        # Modo de Análisis
        self.analysis_mode = QComboBox()
        self.analysis_mode.addItems(["Punto Único", "Barrido de Ángulos"])
        
        self.aoa_min = QDoubleSpinBox()
        self.aoa_min.setRange(-45, 45)
        self.aoa_min.setValue(-4.0)
        self.aoa_max = QDoubleSpinBox()
        self.aoa_max.setRange(-45, 45)
        self.aoa_max.setValue(24.0)
        self.aoa_step = QDoubleSpinBox()
        self.aoa_step.setRange(0.1, 45)
        self.aoa_step.setValue(2.0)
        
        self.sweep_widget = QWidget()
        sweep_layout = QHBoxLayout(self.sweep_widget)
        sweep_layout.setContentsMargins(0, 0, 0, 0)
        sweep_layout.addWidget(self.aoa_min)
        sweep_layout.addWidget(self.aoa_max)
        sweep_layout.addWidget(self.aoa_step)
        self.sweep_widget.setVisible(False)
        
        # UI Connections
        self.profile_type.currentIndexChanged.connect(self._toggle_profile_input)
        self.analysis_mode.currentIndexChanged.connect(self._toggle_analysis_mode)
        self.file_picker_btn.clicked.connect(self._pick_file)
        
        geom_layout.addRow("Tipo:", self.profile_type)
        geom_layout.addRow("Código NACA:", self.naca_input)
        geom_layout.addRow("Archivo:", self.file_widget)
        geom_layout.addRow("Cuerda (c):", self.chord_input)
        geom_layout.addRow("Análisis:", self.analysis_mode)
        self.aoa_row = geom_layout.addRow("Ángulo AoA:", self.aoa_input)
        self.sweep_row = geom_layout.addRow("Min/Máx/Paso:", self.sweep_widget)
        
        self.btn_stop_sweep = QPushButton("🛑 Detener Barrido")
        self.btn_stop_sweep.setVisible(False)
        self.btn_stop_sweep.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold; padding: 6px;")
        geom_layout.addRow(self.btn_stop_sweep)
        
        geom_box.setContentLayout(geom_layout)
        
        # ═══════════════════════════════════════════
        # Sección 2: Control de Malla (Colapsable)
        # ═══════════════════════════════════════════
        mesh_box = CollapsibleBox("▸ Control de Malla")
        mesh_box.toggle_button.setChecked(False)
        mesh_box.content_area.setVisible(False)
        mesh_box.toggle_button.setArrowType(Qt.RightArrow)
        mesh_layout = QFormLayout()
        mesh_layout.setContentsMargins(8, 8, 8, 8)
        
        self.element_type = QComboBox()
        self.element_type.addItems(["Quads (Gmsh)", "Hexaedros (Gmsh)", "Tetraedros (Gmsh)", "Automático (Mixto)", "Estructurada (O-Grid blockMesh)"])

        
        self.mesh_size_min = QDoubleSpinBox()
        self.mesh_size_min.setRange(0.001, 1.0)
        self.mesh_size_min.setValue(0.02) # Más grueso para cálculo rápido
        self.mesh_size_min.setDecimals(4)
        self.mesh_size_min.setSingleStep(0.001)
        self.mesh_size_min.setSuffix(" c")
        self.mesh_size_min.setToolTip("En fracciones de cuerda")
        
        self.mesh_size_max = QDoubleSpinBox()
        self.mesh_size_max.setRange(0.01, 10.0)
        self.mesh_size_max.setValue(1.0) # Más grueso para cálculo rápido
        self.mesh_size_max.setDecimals(3)
        self.mesh_size_max.setSuffix(" c")
        
        self.bl_dist_min = QDoubleSpinBox()
        self.bl_dist_min.setRange(0.00001, 1.0)
        self.bl_dist_min.setValue(0.05) # Capa límite más gruesa
        self.bl_dist_min.setDecimals(5)
        self.bl_dist_min.setSingleStep(0.001)
        self.bl_dist_min.setSuffix(" c")
        
        self.mesh_num_layers = QSpinBox()
        self.mesh_num_layers.setRange(1, 100)
        self.mesh_num_layers.setValue(5) # Menos capas para cálculo rápido

        
        self.mesh_growth_rate = QDoubleSpinBox()
        self.mesh_growth_rate.setRange(1.01, 2.0)
        self.mesh_growth_rate.setValue(1.15)
        self.mesh_growth_rate.setSingleStep(0.05)
        
        self.mesh_curvature = QSpinBox()
        self.mesh_curvature.setRange(0, 500)
        self.mesh_curvature.setValue(100)
        self.mesh_curvature.setSuffix(" p")
        self.mesh_curvature.setToolTip("Número de puntos por círculo completo (curvatura).")
        
        self.mesh_nb_points = QSpinBox()
        self.mesh_nb_points.setRange(50, 2000)
        self.mesh_nb_points.setValue(100)
        self.mesh_nb_points.setSingleStep(50)
        self.mesh_nb_points.setSuffix(" pts")
        self.mesh_nb_points.setToolTip("Puntos en el contorno del perfil (mayor valor = líneas más ortogonales)")
        
        self.btn_yplus = QPushButton("🧮 Evaluar y+")
        self.btn_yplus.setToolTip("Estima la altura inicial basándose en el Re y modelo turbulento.")
        self.btn_yplus.clicked.connect(self._show_yplus_calculator)
        
        bl_min_layout = QHBoxLayout()
        bl_min_layout.addWidget(self.bl_dist_min)
        bl_min_layout.addWidget(self.btn_yplus)
        
        self.wake_length = QDoubleSpinBox()
        self.wake_length.setRange(1.0, 30.0)
        self.wake_length.setValue(5.0)
        self.wake_length.setDecimals(1)
        self.wake_length.setSuffix(" c")
        
        self.wake_refine = QDoubleSpinBox()
        self.wake_refine.setRange(0.5, 5.0)
        self.wake_refine.setValue(1.0)
        self.wake_refine.setDecimals(1)
        self.wake_refine.setToolTip("Multiplicador del tamaño mínimo en la estela (1.0 = 3x cl_min)")
        
        mesh_layout.addRow("Tipo Elemento:", self.element_type)
        mesh_layout.addRow("Resolución Contorno:", self.mesh_nb_points)
        mesh_layout.addRow("Tamaño Mín Elemento:", self.mesh_size_min)
        mesh_layout.addRow("Tamaño Máx Elemento:", self.mesh_size_max)
        mesh_layout.addRow("Capa Límite (dist mín):", bl_min_layout)
        mesh_layout.addRow("Número de Capas:", self.mesh_num_layers)
        mesh_layout.addRow("Tasa Crecimiento:", self.mesh_growth_rate)
        mesh_layout.addRow("Ref. Curvatura:", self.mesh_curvature)
        mesh_layout.addRow("Longitud Estela:", self.wake_length)
        mesh_layout.addRow("Factor Refin. Estela:", self.wake_refine)
        mesh_box.setContentLayout(mesh_layout)
        
        # ═══════════════════════════════════════════
        # Sección 3: Condiciones de Frontera (Colapsable)
        # ═══════════════════════════════════════════
        cf_box = CollapsibleBox("▸ Condiciones de Frontera")
        cf_layout = QFormLayout()
        cf_layout.setContentsMargins(8, 8, 8, 8)
        
        self.vel_input = QDoubleSpinBox()
        self.vel_input.setRange(0.1, 500)
        self.vel_input.setValue(15.0)
        self.vel_input.setSuffix(" m/s")
        self.pres_input = QDoubleSpinBox()
        self.pres_input.setRange(-100000, 100000)
        self.pres_input.setValue(0.0)
        self.pres_input.setSuffix(" Pa")
        
        self.reynolds_input = QDoubleSpinBox()
        self.reynolds_input.setRange(100, 50000000)
        self.reynolds_input.setValue(1000000)
        self.reynolds_input.setDecimals(0)
        self.reynolds_input.setSingleStep(100000)
        self.reynolds_input.setGroupSeparatorShown(True)
        
        self.regime_selector = QComboBox()
        self.regime_selector.addItems(["Estacionario (simpleFoam)", "Transitorio (pimpleFoam)"])
        
        # Parámetros de Estacionario (visibles solo en modo simpleFoam)
        self.steady_widget = QWidget()
        steady_layout = QFormLayout(self.steady_widget)
        steady_layout.setContentsMargins(0, 0, 0, 0)
        self.max_iters_input = QSpinBox()
        self.max_iters_input.setRange(10, 100000)
        self.max_iters_input.setValue(500)
        self.max_iters_input.setSingleStep(50)
        steady_layout.addRow("Iteraciones Máximas:", self.max_iters_input)

        # Parámetros de Transitorio (visibles solo en modo pimpleFoam)
        self.transient_widget = QWidget()
        trans_layout = QFormLayout(self.transient_widget)
        trans_layout.setContentsMargins(0, 0, 0, 0)
        
        self.delta_t_input = QLineEdit("1e-3")
        self.end_time_input = QLineEdit("0.5")
        self.write_interval_input = QLineEdit("0.01")
        self.max_co_input = QDoubleSpinBox()
        self.max_co_input.setRange(0.1, 10.0)
        self.max_co_input.setValue(2.0)
        self.max_co_input.setDecimals(1)
        
        trans_layout.addRow("Paso de Tiempo (Δt):", self.delta_t_input)
        trans_layout.addRow("Tiempo Final (s):", self.end_time_input)
        trans_layout.addRow("Intervalo Escritura (s):", self.write_interval_input)
        trans_layout.addRow("Courant Máximo:", self.max_co_input)
        self.transient_widget.setVisible(False)
        
        self.regime_selector.currentIndexChanged.connect(self._toggle_transient)
        
        self.turbulence_model = QComboBox()
        self.turbulence_model.addItems([
            "Laminar", 
            "k-Omega SST (RAS)",
            "k-Omega SST-LM Transición (RAS)",
            "gamma-ReTheta Transición (RAS)",
            "k-Epsilon (RAS)", 
            "k-Omega (RAS)", 
            "Spalart-Allmaras (RAS)"
        ])
        self.turbulence_model.setCurrentText("k-Omega SST (RAS)")
        
        self.tol_input = QLineEdit("1e-4")
        
        self.native_foam_cb = QCheckBox("Usar OpenFOAM Nativo (Sin Docker)")
        self.native_foam_cb.setChecked(False)
        self.native_foam_cb.setToolTip("Habilita esto si tienes 'simpleFoam' etc. instalados en el sistema principal y no quieres usar Docker.")
        
        cf_layout.addRow("Régimen de Flujo:", self.regime_selector)
        cf_layout.addRow("", self.steady_widget)
        cf_layout.addRow("", self.transient_widget)
        cf_layout.addRow("Modelo Turbulencia:", self.turbulence_model)
        cf_layout.addRow("Nº de Reynolds:", self.reynolds_input)
        cf_layout.addRow("Velocidad de Entrada:", self.vel_input)
        cf_layout.addRow("Presión de Salida:", self.pres_input)
        cf_layout.addRow("Tolerancia Residual:", self.tol_input)
        cf_layout.addRow("", self.native_foam_cb)
        cf_box.setContentLayout(cf_layout)
        
        layout.addWidget(geom_box)
        layout.addWidget(mesh_box)
        layout.addWidget(cf_box)
        layout.addStretch()
        
        # Botones de Acción (Fijos en la parte inferior fuera del scroll)
        btn_layout = QVBoxLayout()
        btn_layout.setContentsMargins(8, 8, 8, 8)
        
        self.btn_geom = QPushButton("📐 Generar Geometría")
        self.btn_mesh = QPushButton("🕸️ Generar Malla")
        self.btn_run = QPushButton("🚀 Iniciar Análisis")
        self.btn_run.setObjectName("runButton")
        self.btn_results = QPushButton("📊 Ver Resultados")
        
        btn_layout.addWidget(self.btn_geom)
        btn_layout.addWidget(self.btn_mesh)
        btn_layout.addWidget(self.btn_run)
        btn_layout.addWidget(self.btn_results)
        
        main_layout.addLayout(btn_layout)



    def _toggle_profile_input(self) -> None:
        is_custom = self.profile_type.currentIndex() == 1
        self.naca_input.setVisible(not is_custom)
        self.file_widget.setVisible(is_custom)
        
    def _toggle_analysis_mode(self) -> None:
        is_sweep = self.analysis_mode.currentIndex() == 1
        self.aoa_input.setVisible(not is_sweep)
        self.sweep_widget.setVisible(is_sweep)

    def _toggle_transient(self) -> None:
        is_transient = self.regime_selector.currentIndex() == 1
        self.transient_widget.setVisible(is_transient)
        self.steady_widget.setVisible(not is_transient)
    def _show_yplus_calculator(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Calculadora y+")
        layout = QFormLayout(dialog)
        
        re_spin = QDoubleSpinBox()
        re_spin.setRange(1e4, 1e9)
        re_spin.setValue(self.reynolds_input.value())
        re_spin.setDecimals(0)
        
        yplus_target = QDoubleSpinBox()
        yplus_target.setRange(0.1, 500)
        yplus_target.setValue(1.0 if "SST" in self.turbulence_model.currentText() else 30.0)
        
        chord_spin = QDoubleSpinBox()
        chord_spin.setValue(self.chord_input.value())
        
        layout.addRow("Número de Reynolds:", re_spin)
        layout.addRow("Cuerda (m):", chord_spin)
        layout.addRow("y+ Objetivo:", yplus_target)
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        layout.addRow(btn_box)
        
        if dialog.exec_() == QDialog.Accepted:
            re = re_spin.value()
            c = chord_spin.value()
            yp = yplus_target.value()
            # Empirical flat plate Cf
            cf = 0.026 / (re ** (1/7))
            # tau_w approx = 0.5 * rho * U^2 * Cf -> U* = U * sqrt(Cf / 2)
            # U = Re * nu / c. Re = U*c/nu -> U/nu = Re/c
            # delta_s = y+ * nu / U* = y+ * nu / (U * sqrt(Cf/2)) 
            # delta_s / c = y+ / (Re * sqrt(Cf/2))
            
            delta_s_c = yp / (re * ((cf / 2) ** 0.5))
            # limit delta_s_c to avoid weird spinbox rounding error out of bounds
            self.bl_dist_min.setValue(max(0.00001, min(delta_s_c, 1.0)))

    def _pick_file(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(self, "Seleccionar Perfil 2D", "", "Text Files (*.txt *.csv);;All Files (*)")
        if file_name:
            self.file_path_label.setText(file_name)

    def get_params(self) -> Dict[str, Any]:
        p_type = self.profile_type.currentText()
        naca = self.naca_input.text().strip()
        if "Custom" not in p_type:
            if not naca.isdigit():
                raise ValueError(f"El código NACA debe contener solo dígitos numéricos.\nValor incorrecto: '{naca}'")
            if len(naca) == 4:
                # NACA 4-dígitos: MPXX
                # M = máxima curvatura (0-9 → 0%-9% del chord)
                # P = posición de la curvatura (0-9 → 0%-90% del chord)
                # XX = espesor máximo (01-40 → 1%-40% del chord)
                thickness = int(naca[2:])
                camber = int(naca[0])
                camber_pos = int(naca[1])
                if thickness < 1 or thickness > 40:
                    raise ValueError(f"El espesor NACA (últimos 2 dígitos) debe estar entre 01 y 40.\nValor: '{naca[2:]}' → {thickness}% del chord.")
                if camber > 0 and camber_pos == 0:
                    raise ValueError(f"Si la curvatura máxima (1er dígito) es > 0, la posición (2do dígito) no puede ser 0.\nCódigo: '{naca}'")
            elif len(naca) == 5:
                # NACA 5-dígitos: validación básica
                cl_design = int(naca[0])
                if cl_design < 1 or cl_design > 6:
                    raise ValueError(f"Para NACA 5-dígitos, el primer dígito (Cl diseño) debe estar entre 1 y 6.\nValor: '{naca}'")
            else:
                raise ValueError(f"El código NACA debe tener 4 o 5 dígitos.\nValor incorrecto: '{naca}' ({len(naca)} dígitos)")
        else:
            # Validar que existe el archivo custom
            file_path = self.file_path_label.text().strip()
            if not file_path:
                raise ValueError("Debes seleccionar un archivo de perfil (.txt, .csv, .dat).")
            import os
            if not os.path.exists(file_path):
                raise ValueError(f"El archivo de perfil no existe:\n{file_path}")
                
        a_mode = self.analysis_mode.currentText()
        if "Barrido" in a_mode:
            if self.aoa_min.value() >= self.aoa_max.value():
                raise ValueError("En 'Barrido de Ángulos', el valor mínimo de AoA debe ser menor al máximo.")
                
        if self.mesh_size_min.value() >= self.mesh_size_max.value():
            raise ValueError("El tamaño MÍNIMO de malla no puede ser mayor o igual al MÁXIMO.")


        return {
            "profile_type": self.profile_type.currentText(),
            "naca": self.naca_input.text(),
            "file_path": self.file_path_label.text(),
            "chord": self.chord_input.value(),
            "element_type": self.element_type.currentText(),
            "analysis_mode": self.analysis_mode.currentText(),
            "aoa": self.aoa_input.value(),
            "aoa_min": self.aoa_min.value(),
            "aoa_max": self.aoa_max.value(),
            "aoa_step": self.aoa_step.value(),
            "mesh_size_min": self.mesh_size_min.value(),
            "mesh_size_max": self.mesh_size_max.value(),
            "bl_dist_min": self.bl_dist_min.value(),
            "mesh_num_layers": self.mesh_num_layers.value(),
            "mesh_growth_rate": self.mesh_growth_rate.value(),
            "mesh_curvature": self.mesh_curvature.value(),
            "mesh_nb_points": self.mesh_nb_points.value(),
            "wake_length": self.wake_length.value(),
            "wake_refine": self.wake_refine.value(),
            "regime": self.regime_selector.currentText(),
            "reynolds": self.reynolds_input.value(),
            "u_inlet": self.vel_input.value(),
            "p_outlet": self.pres_input.value(),
            "tolerance": self.tol_input.text(),
            "turbulence": self.turbulence_model.currentText(),
            "delta_t": self.delta_t_input.text(),
            "end_time": self.end_time_input.text(),
            "write_interval": self.write_interval_input.text(),
            "max_co": self.max_co_input.value(),
            "max_iters": self.max_iters_input.value(),
            "native_foam": self.native_foam_cb.isChecked()
        }

    def set_params(self, p: Dict[str, Any]) -> None:
        """Restaurar todos los parámetros de la interfaz desde un diccionario."""
        if "profile_type" in p:
            idx = self.profile_type.findText(p["profile_type"])
            if idx >= 0: self.profile_type.setCurrentIndex(idx)
        if "naca" in p:
            self.naca_input.setText(str(p["naca"]))
        if "file_path" in p:
            self.file_path_label.setText(str(p["file_path"]))
        if "chord" in p:
            self.chord_input.setValue(float(p["chord"]))
        if "element_type" in p:
            idx = self.element_type.findText(p["element_type"])
            if idx >= 0: self.element_type.setCurrentIndex(idx)
        if "analysis_mode" in p:
            idx = self.analysis_mode.findText(p["analysis_mode"])
            if idx >= 0: self.analysis_mode.setCurrentIndex(idx)
        if "aoa" in p:
            self.aoa_input.setValue(float(p["aoa"]))
        if "aoa_min" in p:
            self.aoa_min.setValue(float(p["aoa_min"]))
        if "aoa_max" in p:
            self.aoa_max.setValue(float(p["aoa_max"]))
        if "aoa_step" in p:
            self.aoa_step.setValue(float(p["aoa_step"]))
        if "mesh_size_min" in p:
            self.mesh_size_min.setValue(float(p["mesh_size_min"]))
        if "mesh_size_max" in p:
            self.mesh_size_max.setValue(float(p["mesh_size_max"]))
        if "bl_dist_min" in p:
            self.bl_dist_min.setValue(float(p["bl_dist_min"]))
        if "mesh_num_layers" in p:
            self.mesh_num_layers.setValue(int(p["mesh_num_layers"]))
        if "mesh_growth_rate" in p:
            self.mesh_growth_rate.setValue(float(p["mesh_growth_rate"]))
        if "mesh_curvature" in p:
            self.mesh_curvature.setValue(int(p["mesh_curvature"]))
        if "wake_length" in p:
            self.wake_length.setValue(float(p["wake_length"]))
        if "wake_refine" in p:
            self.wake_refine.setValue(float(p["wake_refine"]))
        if "regime" in p:
            idx = self.regime_selector.findText(p["regime"])
            if idx >= 0: self.regime_selector.setCurrentIndex(idx)
        if "reynolds" in p:
            self.reynolds_input.setValue(float(p["reynolds"]))
        if "u_inlet" in p:
            self.vel_input.setValue(float(p["u_inlet"]))
        if "p_outlet" in p:
            self.pres_input.setValue(float(p["p_outlet"]))
        if "tolerance" in p:
            self.tol_input.setText(str(p["tolerance"]))
        if "turbulence" in p:
            idx = self.turbulence_model.findText(p["turbulence"])
            if idx >= 0: self.turbulence_model.setCurrentIndex(idx)
        if "delta_t" in p:
            self.delta_t_input.setText(str(p["delta_t"]))
        if "end_time" in p:
            self.end_time_input.setText(str(p["end_time"]))
        if "write_interval" in p:
            self.write_interval_input.setText(str(p["write_interval"]))
        if "max_co" in p:
            self.max_co_input.setValue(float(p["max_co"]))
        if "max_iters" in p:
            self.max_iters_input.setValue(int(p["max_iters"]))
        if "native_foam" in p:
            self.native_foam_cb.setChecked(bool(p["native_foam"]))
