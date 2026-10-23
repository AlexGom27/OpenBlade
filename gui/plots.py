import matplotlib
matplotlib.use('QtAgg')
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:
    # Fallback para matplotlib < 3.5
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from typing import Optional, List, Dict
import csv
import os
import numpy as np
from qtpy.QtWidgets import QWidget, QVBoxLayout, QPushButton, QHBoxLayout, QFileDialog, QLabel

class ResidualPlot(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.fig = Figure(figsize=(4, 2.5), dpi=80)
        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)

        # Panel de avance junto a la grafica: tiempo simulado, porcentaje,
        # ETA y ritmo. Se rellena desde run.log, asi funciona tambien con
        # corridas lanzadas fuera de la GUI.
        self.progress_label = QLabel("Sin datos de avance.")
        self.progress_label.setWordWrap(True)
        self.progress_label.setStyleSheet(
            "background: #263238; color: #dbe9f4; padding: 8px; "
            "border-radius: 4px; font-family: Menlo, monospace; font-size: 10px;")
        layout.addWidget(self.progress_label)
        self._end_time = None
        
        self.ax = self.fig.add_subplot(111)
        self.ax.set_yscale('log')
        self.ax.set_title("Monitor de Convergencia (Residuos)", color='white', fontsize=12, pad=10)
        self.ax.set_xlabel("Iteración / Tiempo", color='white')
        self.ax.set_ylabel("Residuo Inicial (Log)", color='white')
        
        self.fig.patch.set_facecolor('#1e1e1e')
        self.ax.set_facecolor('#1e1e1e')
        self.ax.xaxis.label.set_color('white')
        self.ax.yaxis.label.set_color('white')
        self.ax.tick_params(colors='white', labelsize=8)
        self.ax.spines['bottom'].set_color('#555555')
        self.ax.spines['top'].set_color('#555555') 
        self.ax.spines['right'].set_color('#555555')
        self.ax.spines['left'].set_color('#555555')
        self.ax.grid(True, which="both", ls="--", alpha=0.3, color='#888888')
        self.fig.subplots_adjust(left=0.15, right=0.95, top=0.9, bottom=0.2)
        
        self.res_data = {}
        self.res_iters = []
        self.res_lines = {}
        self._pending_redraw = False
        
    def reset(self) -> None:
        self.res_data = {}
        self.res_iters = []
        for line in self.res_lines.values():
            line.remove()
        self.res_lines = {}
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw()
        
    def load_from_log(self, log_path: str, max_points: int = 400) -> int:
        """Rellena el gráfico con los residuales de un run.log de OpenFOAM.

        Permite ver la convergencia de una simulación YA lanzada (incluso si
        se abrió la app después de arrancarla), no sólo la que se lanza desde
        la propia GUI.

        OpenFOAM escribe por cada paso de tiempo:
            Time = <t>
            smoothSolver:  Solving for Ux, Initial residual = <r>, ...
            GAMG:          Solving for p,  Initial residual = <r>, ...

        Se toma el residuo INICIAL de cada ecuación y se usa `Time` como
        abscisa. Devuelve cuántos puntos se cargaron.
        """
        import re

        if not os.path.exists(log_path):
            return 0
        self._log_path = log_path
        try:
            self._log_ctime = os.stat(log_path).st_ctime
        except OSError:
            self._log_ctime = None

        eq_re = re.compile(
            r"Solving for (Ux|Uy|Uz|p|k|omega|epsilon|nuTilda),\s*"
            r"Initial residual = ([-+0-9.eE]+)")
        time_re = re.compile(r"^Time = ([-+0-9.eE]+)", re.M)

        try:
            with open(log_path, errors="replace") as f:
                lines = f.readlines()
        except OSError:
            return 0

        # Se recorre el log y se agrupa por bloque de tiempo.
        bloques = []
        actual = None
        for ln in lines:
            mt = time_re.match(ln)
            if mt:
                actual = {"t": float(mt.group(1)), "res": {}}
                bloques.append(actual)
                continue
            if actual is None:
                continue
            me = eq_re.search(ln)
            if me:
                campo, val = me.group(1), float(me.group(2))
                # primer valor del bloque = residuo inicial
                actual["res"].setdefault(campo, val)

        if not bloques:
            return 0

        # Submuestreo para no dibujar 100 000 puntos.
        if len(bloques) > max_points:
            paso = max(1, len(bloques) // max_points)
            bloques = bloques[::paso]

        self.res_iters = []
        self.res_data = {}
        self.res_lines = {}
        for b in bloques:
            self.res_iters.append(b["t"])
            for campo, val in b["res"].items():
                self.res_data.setdefault(campo, []).append(val)

        # Rellenar series incompletas para que todas tengan la misma longitud.
        n = len(self.res_iters)
        for campo in self.res_data:
            serie = self.res_data[campo]
            if len(serie) < n:
                serie.extend([serie[-1] if serie else 1.0] * (n - len(serie)))

        self._update_progress_label()
        self._pending_redraw = True
        return n

    def _update_progress_label(self) -> None:
        """Rellena el panel de avance con los datos ya cargados."""
        if not self.res_iters:
            self.progress_label.setText("Sin datos de avance.")
            return

        # El avance real se mide por el último directorio escrito, no por el
        # último Time del log: si el contenedor se reinició, el log empieza de
        # cero pero los tiempos guardados siguen siendo válidos.
        t_guardado = self._last_saved_time()
        t_now = t_guardado if t_guardado is not None else self.res_iters[-1]
        fin = self._end_time or self._read_end_time()
        self._end_time = fin
        n = len(self.res_iters)

        if not fin:
            self.progress_label.setText(f"t = {t_now:.4f} s   ({n} muestras)")
            return

        pct = 100.0 * t_now / fin
        if pct >= 99.95:
            self.progress_label.setText(
                f"✔ COMPLETADA   t = {t_now:.4f} de {fin:g} s   (100%)\n"
                f"Muestras: {n}")
            return

        # Ritmo: media entre el primer y el ultimo tiempo del log. Se usa el
        # propio log como reloj, no el reloj de pared, para que funcione igual
        # con una corrida ya terminada.
        ritmo = ""
        if n > 1:
            dt_sim = self.res_iters[-1] - self.res_iters[0]
            if dt_sim > 0:
                mtime = os.path.getmtime(getattr(self, "_log_path", "") or "")
                ctime = getattr(self, "_log_ctime", None)
                if ctime and mtime > ctime:
                    sp = (mtime - ctime) / max(n - 1, 1)
                    faltan = (fin - t_now) / (dt_sim / max(n - 1, 1))
                    eta_h = faltan * sp / 3600
                    eta = f"{eta_h:.1f} h" if eta_h >= 1 else f"{eta_h*60:.0f} min"
                    ritmo = f"\nRitmo: {sp:.2f} s/paso   ·   ETA ~{eta}"

        self.progress_label.setText(
            f"⏳ EN CURSO   t = {t_now:.4f} de {fin:g} s   ({pct:.1f}%)"
            f"\nMuestras: {n}{ritmo}")

    def _last_saved_time(self):
        """Último directorio de tiempo realmente escrito en el caso.

        Es más fiable que el `Time =` del run.log: si el contenedor se
        reinició, el log vuelve a empezar pero los directorios de tiempo ya
        escritos siguen ahí.
        """
        try:
            caso = getattr(self, "case_dir", None) or os.path.join(
                os.path.expanduser("~"), ".openblade", "openfoam_case")
            tiempos = []
            for nombre in os.listdir(caso):
                try:
                    t = float(nombre)
                except ValueError:
                    continue
                # sólo cuentan los que tienen campos
                if os.path.exists(os.path.join(caso, nombre, "U")):
                    tiempos.append(t)
            return max(tiempos) if tiempos else None
        except Exception:
            return None

    def _read_end_time(self):
        """Lee endTime del controlDict del caso."""
        try:
            import re as _re
            caso = getattr(self, "case_dir", None) or os.path.join(
                os.path.expanduser("~"), ".openblade", "openfoam_case")
            cd = os.path.join(caso, "system", "controlDict")
            m = _re.search(r"^endTime\s+([0-9.eE+-]+);",
                           open(cd, errors="replace").read(), _re.M)
            return float(m.group(1)) if m else None
        except Exception:
            return None

    def update_plot(self, field: str, value: float, time_val: float) -> None:
        if not self.res_iters or self.res_iters[-1] != time_val:
            self.res_iters.append(time_val)
            for f in self.res_data:
                while len(self.res_data[f]) < len(self.res_iters) - 1:
                    self.res_data[f].append(self.res_data[f][-1] if self.res_data[f] else 1.0)
                    
        if field not in self.res_data:
            self.res_data[field] = [1.0] * (len(self.res_iters) - 1)
            
        if len(self.res_data[field]) == len(self.res_iters):
            # Ya tenemos un valor para esta iteración (ej. sub-iteraciones de p), lo actualizamos
            self.res_data[field][-1] = value
        else:
            self.res_data[field].append(value)
            
        self._pending_redraw = True
        
    def redraw(self) -> None:
        if not self._pending_redraw:
            return
            
        for f, data in self.res_data.items():
            if len(data) != len(self.res_iters):
                continue
                
            if f not in self.res_lines:
                lw = 2.0 if f == 'p' else 1.2
                self.res_lines[f], = self.ax.plot(self.res_iters, data, label=f, linewidth=lw)
            else:
                self.res_lines[f].set_data(self.res_iters, data)
                
        if len(self.res_lines) > 0 and len(self.ax.get_legend_handles_labels()[1]) != len(self.res_lines):
            self.ax.legend(facecolor='#1e1e1e', edgecolor='#333333', labelcolor='white', fontsize=8, loc='upper right')
            
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle() 
        self._pending_redraw = False



class AeroPlot(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.fig = Figure(figsize=(5, 5), dpi=80)
        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)
        
        self.fig.patch.set_facecolor('#1e1e1e')
        self.ax_cl = self.fig.add_subplot(311)
        self.ax_cd = self.fig.add_subplot(312)
        self.ax_cm = self.fig.add_subplot(313)
        
        for ax in [self.ax_cl, self.ax_cd, self.ax_cm]:
            ax.set_facecolor('#1e1e1e')
            ax.xaxis.label.set_color('white')
            ax.yaxis.label.set_color('white')
            ax.tick_params(colors='white', labelsize=8)
            for spine in ax.spines.values():
                spine.set_color('#555555')
            ax.grid(True, ls="--", alpha=0.3, color='#888888')
            
        self.ax_cl.set_title("Coeficiente de Sustentación (Cl) vs AoA", color='white', fontsize=10)
        self.ax_cl.set_ylabel("Cl [-]", color='white')
        
        self.ax_cd.set_title("Coeficiente de Arrastre (Cd) vs AoA", color='white', fontsize=10)
        self.ax_cd.set_ylabel("Cd [-]", color='white')
        
        self.ax_cm.set_title("Coeficiente de Momento (Cm) vs AoA", color='white', fontsize=10)
        self.ax_cm.set_xlabel("Ángulo de Ataque (AoA) [°]", color='white')
        self.ax_cm.set_ylabel("Cm [-]", color='white')
        
        self.fig.subplots_adjust(hspace=0.6, bottom=0.15, top=0.9, left=0.15, right=0.95)
        
        self.line_cl, = self.ax_cl.plot([], [], 'o-', color='#4CAF50', linewidth=2, markersize=5)
        self.line_cd, = self.ax_cd.plot([], [], 'o-', color='#F44336', linewidth=2, markersize=5)
        self.line_cm, = self.ax_cm.plot([], [], 'o-', color='#FFC107', linewidth=2, markersize=5)
        
        self.aoas = []
        self.cls = []
        self.cds = []
        self.cms = []
        self._pending_redraw = False
        
        # Botón de exportación
        btn_layout = QHBoxLayout()
        self.btn_export = QPushButton("📤 Exportar resultados a CSV")
        self.btn_export.clicked.connect(self.export_to_csv)
        self.btn_export.setStyleSheet("""
            QPushButton {
                background-color: #2e7d32;
                color: white;
                font-weight: bold;
                padding: 10px;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #388e3c;
            }
        """)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_export)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
    def update_plots(self, aoas: List[float], cls: List[float], cds: List[float], cms: Optional[List[float]] = None) -> None:
        self.aoas = list(aoas)
        self.cls = list(cls)
        self.cds = list(cds)
        self.cms = list(cms) if cms is not None else [0.0] * len(aoas)
        # El dibujado real lo hace refresh_plots() cada 100 ms; así una simulación
        # que emite Cl/Cd en cada iteración no bloquea el hilo de la GUI.
        self._pending_redraw = True

    def redraw(self) -> None:
        if not self._pending_redraw:
            return
        self.line_cl.set_data(self.aoas, self.cls)
        self.ax_cl.relim()
        self.ax_cl.autoscale_view()

        self.line_cd.set_data(self.aoas, self.cds)
        self.ax_cd.relim()
        self.ax_cd.autoscale_view()

        self.line_cm.set_data(self.aoas, self.cms)
        self.ax_cm.relim()
        self.ax_cm.autoscale_view()

        self.canvas.draw_idle()
        self._pending_redraw = False

    def export_to_csv(self) -> None:
        if not self.aoas:
            return
            
        filename, _ = QFileDialog.getSaveFileName(self, "Exportar Resultados", "", "CSV Files (*.csv)")
        if filename:
            try:
                with open(filename, mode='w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["AoA [deg]", "Cl [-]", "Cd [-]", "Cm [-]", "L/D"])
                    for i in range(len(self.aoas)):
                        ld = self.cls[i] / self.cds[i] if self.cds[i] != 0 else 0
                        writer.writerow([self.aoas[i], self.cls[i], self.cds[i], self.cms[i], ld])
            except Exception as e:
                print(f"Error al exportar: {e}")

class PressurePlot(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.fig = Figure(figsize=(5, 4), dpi=80)
        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)
        
        self.fig.patch.set_facecolor('#1e1e1e')
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor('#1e1e1e')
        self.ax.xaxis.label.set_color('white')
        self.ax.yaxis.label.set_color('white')
        self.ax.tick_params(colors='white', labelsize=8)
        for spine in self.ax.spines.values():
            spine.set_color('#555555')
        self.ax.grid(True, ls="--", alpha=0.3, color='#888888')
        
        self.ax.set_title("Distribución de Presión (Cp)", color='white', fontsize=12)
        self.ax.set_xlabel("x/c", color='white')
        self.ax.set_ylabel("-Cp [-]", color='white')
        # Convención aerodinámica: se grafica -Cp (succión hacia arriba).
        
        self.line_upper, = self.ax.plot([], [], 'o-', color='#4CAF50', label='Extradós', markersize=3)
        self.line_lower, = self.ax.plot([], [], 'o-', color='#2196F3', label='Intradós', markersize=3)
        self.ax.legend(facecolor='#1e1e1e', edgecolor='#333333', labelcolor='white', fontsize=10)
        
    def update_cp(self, x_upper: np.ndarray, cp_upper: np.ndarray, x_lower: np.ndarray, cp_lower: np.ndarray) -> None:
        # Graficamos -Cp (convención aerodinámica): la succión queda arriba.
        self.line_upper.set_data(x_upper, -cp_upper)
        self.line_lower.set_data(x_lower, -cp_lower)
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw()
