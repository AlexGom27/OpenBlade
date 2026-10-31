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
import warnings
import numpy as np
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QHBoxLayout, QFileDialog,
                            QLabel, QTabWidget)


# Las pestanas ocultas aun no tienen tamano: al mostrarse se vuelven a dibujar bien.
warnings.filterwarnings("ignore", message="constrained_layout not applied")


def new_chart(figsize=(5, 4), dpi=90):
    """Figura oscura con un solo eje que ocupa toda su pestana.

    layout="constrained" reajusta los margenes al cambiar de tamano, para que
    titulos y etiquetas no queden cortados.
    """
    fig = Figure(figsize=figsize, dpi=dpi, layout="constrained")
    fig.patch.set_facecolor('#1e1e1e')
    canvas = FigureCanvas(fig)
    ax = fig.add_subplot(111)
    style_axes(ax)
    return fig, canvas, ax


def style_axes(ax) -> None:
    ax.set_facecolor('#1e1e1e')
    ax.xaxis.label.set_color('white')
    ax.yaxis.label.set_color('white')
    ax.title.set_color('white')
    ax.tick_params(colors='white', labelsize=8)
    for spine in ax.spines.values():
        spine.set_color('#555555')
    ax.grid(True, which="both", ls="--", alpha=0.3, color='#888888')


class ResidualPlot(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.fig, self.canvas, self.ax = new_chart()
        layout.addWidget(self.canvas, 1)

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
        
        self.ax.set_yscale('log')
        self.ax.set_title("Monitor de Convergencia (Residuos)", color='white', fontsize=12, pad=10)
        self.ax.set_xlabel("Iteración / Tiempo", color='white')
        self.ax.set_ylabel("Residuo Inicial (Log)", color='white')

        self.res_data = {}
        self.res_iters = []
        self.res_lines = {}
        self._pending_redraw = False
        
    def _clear_lines(self) -> None:
        # Vaciar solo el diccionario dejaria las curvas viejas en el eje.
        for line in self.res_lines.values():
            line.remove()
        self.res_lines = {}

    def set_log_path(self, log_path: str) -> None:
        self._log_path = log_path

    def reset(self) -> None:
        self.res_data = {}
        self.res_iters = []
        self._clear_lines()
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

        # No releer si el fichero no ha cambiado.
        #
        # El temporizador llama cada 10 s y el run.log de una corrida larga
        # pesa decenas de MB (27 MB en el caso de alpha=12). Releerlo entero
        # cada vez bloqueaba el hilo de la interfaz: la app se quedaba
        # congelada al 17% de CPU. Con (mtime, tamaño) se evita el trabajo
        # cuando nada ha cambiado.
        try:
            st = os.stat(log_path)
            firma = (st.st_mtime, st.st_size)
        except OSError:
            firma = None
        if firma is not None and firma == getattr(self, "_log_firma", None):
            return getattr(self, "_log_n", 0)
        self._log_firma = firma
        try:
            self._log_ctime = os.stat(log_path).st_ctime
        except OSError:
            self._log_ctime = None

        eq_re = re.compile(
            r"Solving for (Ux|Uy|Uz|p|k|omega|epsilon|nuTilda),\s*"
            r"Initial residual = ([-+0-9.eE]+)")
        time_re = re.compile(r"^Time = ([-+0-9.eE]+)", re.M)

        # Se itera el fichero línea a línea en lugar de leerlo entero: un log
        # de 27 MB como lista de strings ocupa cientos de MB y provoca
        # pausas largas del recolector.
        bloques = []
        actual = None
        try:
            fh = open(log_path, errors="replace")
        except OSError:
            return 0
        with fh:
            for ln in fh:
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
        self._clear_lines()
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

        self._log_n = n
        self._update_progress_label()
        self._pending_redraw = True
        return n

    def set_series(self, bloques) -> None:
        """Coloca en el gráfico una lista de bloques ya parseados.

        Lo llama MainWindow desde el hilo de la GUI, con los datos que preparó
        el hilo de lectura. Evita que ResidualPlot toque el fichero.
        """
        if not bloques:
            return
        self.res_iters = [b["t"] for b in bloques]
        self.res_data = {}
        self._clear_lines()
        for b in bloques:
            for campo, val in b["res"].items():
                self.res_data.setdefault(campo, []).append(val)
        # Rellenar series incompletas hasta la misma longitud
        n = len(self.res_iters)
        for campo in self.res_data:
            serie = self.res_data[campo]
            if len(serie) < n:
                serie.extend([serie[-1] if serie else 1.0] * (n - len(serie)))
        self._update_progress_label()
        self._pending_redraw = True

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
                log_path = getattr(self, "_log_path", "")
                mtime = os.path.getmtime(log_path) if log_path and os.path.exists(log_path) else 0
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
                
        leyenda = self.ax.get_legend()
        if self.res_lines and (leyenda is None or len(leyenda.get_texts()) != len(self.res_lines)):
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
        
        # Una subpestaña por coeficiente, cada una con toda el área disponible.
        self.subtabs = QTabWidget()
        self.subtabs.setElideMode(Qt.ElideNone)
        layout.addWidget(self.subtabs, 1)

        self._charts = {}
        self._dudosos = {}
        for clave, titulo, ylabel, color in (
                ("cl", "Coeficiente de Sustentación (Cl) vs AoA", "Cl [-]", '#4CAF50'),
                ("cd", "Coeficiente de Arrastre (Cd) vs AoA", "Cd [-]", '#F44336'),
                ("cm", "Coeficiente de Momento (Cm) vs AoA", "Cm [-]", '#FFC107')):
            fig, canvas, ax = new_chart()
            ax.set_title(titulo, color='white', fontsize=11)
            ax.set_xlabel("Ángulo de Ataque (AoA) [°]", color='white')
            ax.set_ylabel(ylabel, color='white')
            line, = ax.plot([], [], 'o-', color=color, linewidth=2, markersize=5)
            # Encima, en hueco, los puntos que no convergieron.
            dudosos, = ax.plot([], [], 'o', markerfacecolor='#1e1e1e', markeredgecolor=color,
                               markeredgewidth=1.5, markersize=8, linestyle='none')
            self._charts[clave] = (fig, canvas, ax, line)
            self._dudosos[clave] = dudosos
            self.subtabs.addTab(canvas, ylabel.split()[0])
        self.subtabs.currentChanged.connect(lambda _i: self._draw_visible())

        self.aoas = []
        self.cls = []
        self.cds = []
        self.cms = []
        self.estados = []
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
        
    def update_plots(self, aoas: List[float], cls: List[float], cds: List[float],
                     cms: Optional[List[float]] = None,
                     estados: Optional[List[str]] = None) -> None:
        """Sin estados los valores son en vivo; un Cl en None no se dibuja."""
        self.aoas = list(aoas)
        self.cls = list(cls)
        self.cds = list(cds)
        self.cms = list(cms) if cms is not None else [0.0] * len(aoas)
        self.estados = list(estados) if estados is not None else [""] * len(aoas)
        # El dibujado real lo hace refresh_plots() cada 100 ms; así una simulación
        # que emite Cl/Cd en cada iteración no bloquea el hilo de la GUI.
        self._pending_redraw = True

    def redraw(self) -> None:
        if not self._pending_redraw:
            return
        for clave, datos in (("cl", self.cls), ("cd", self.cds), ("cm", self.cms)):
            _, _, ax, line = self._charts[clave]
            validos = [(a, d, e) for a, d, e in zip(self.aoas, datos, self.estados)
                       if d is not None]
            line.set_data([a for a, _, _ in validos], [d for _, d, _ in validos])
            self._dudosos[clave].set_data(
                [a for a, _, e in validos if e == "NO CONVERGIDO"],
                [d for _, d, e in validos if e == "NO CONVERGIDO"])
            ax.relim()
            ax.autoscale_view()
        self._draw_visible()
        self._pending_redraw = False

    def _draw_visible(self) -> None:
        """Solo se pinta la subpestaña a la vista; las otras al seleccionarlas."""
        for fig, canvas, _, _ in self._charts.values():
            if canvas is self.subtabs.currentWidget():
                canvas.draw_idle()

    @property
    def fig(self) -> Figure:
        """Los tres coeficientes en una sola figura, para el informe PDF."""
        compuesta = Figure(figsize=(6, 7), dpi=100, layout="constrained")
        compuesta.patch.set_facecolor('#1e1e1e')
        for i, (clave, datos) in enumerate((("cl", self.cls), ("cd", self.cds),
                                            ("cm", self.cms)), start=1):
            _, _, origen, line = self._charts[clave]
            ax = compuesta.add_subplot(3, 1, i)
            style_axes(ax)
            validos = [(a, d, e) for a, d, e in zip(self.aoas, datos, self.estados)
                       if d is not None]
            ax.plot([a for a, _, _ in validos], [d for _, d, _ in validos], 'o-',
                    color=line.get_color(), linewidth=2, markersize=5)
            ax.plot([a for a, _, e in validos if e == "NO CONVERGIDO"],
                    [d for _, d, e in validos if e == "NO CONVERGIDO"], 'o',
                    markerfacecolor='#1e1e1e', markeredgecolor=line.get_color(),
                    markeredgewidth=1.5, markersize=8, linestyle='none')
            ax.set_title(origen.get_title(), color='white', fontsize=10)
            ax.set_ylabel(origen.get_ylabel(), color='white')
        ax.set_xlabel("Ángulo de Ataque (AoA) [°]", color='white')
        return compuesta

    def export_to_csv(self) -> None:
        if not self.aoas:
            return
            
        filename, _ = QFileDialog.getSaveFileName(self, "Exportar Resultados", "", "CSV Files (*.csv)")
        if filename:
            try:
                with open(filename, mode='w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["AoA [deg]", "Cl [-]", "Cd [-]", "Cm [-]", "L/D", "Veredicto"])
                    for i in range(len(self.aoas)):
                        if self.cds[i] is None:
                            writer.writerow([self.aoas[i], "", "", "", "", self.estados[i]])
                            continue
                        ld = self.cls[i] / self.cds[i] if self.cds[i] != 0 else 0
                        writer.writerow([self.aoas[i], self.cls[i], self.cds[i], self.cms[i], ld,
                                         self.estados[i]])
            except Exception as e:
                print(f"Error al exportar: {e}")

class PressurePlot(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.fig, self.canvas, self.ax = new_chart()
        layout.addWidget(self.canvas, 1)

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
