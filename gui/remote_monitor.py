#!/usr/bin/env python3
"""Panel de monitorización remota para la GUI de OpenBlade.

Muestra en vivo, desde la propia ventana:
  * estado y porcentaje de avance de la simulación
  * residuales de cada ecuación (gráfica log)
  * Cl y Cd
  * CPU, RAM y disco del servidor

Los datos se piden por SSH al servidor, que ejecuta `validation/monitor.py
--json`. Se usa una clave SSH sin contraseña; si no está configurada, el panel
lo indica en lugar de fallar.

Configuración
-------------
Variable de entorno (o atributo) con el destino SSH:
    OPENBLADE_REMOTE=alejandro@100.85.66.123
OPENBLADE_REMOTE_CASE admite varios casos separados por comas: el primero se
abre al iniciar y el resto queda en el selector.

Si no se define, el panel queda inactivo y lo dice.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading

from qtpy.QtCore import Qt, QTimer, Signal
from qtpy.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit,
                            QPushButton, QVBoxLayout, QWidget)

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402


class RemoteMonitorPanel(QWidget):
    """Panel con estado, gráficas y métricas del servidor."""

    _datos_listos = Signal(object)

    def __init__(self, remote: str = "", case: str = "openfoam_case",
                 parent=None) -> None:
        super().__init__(parent)
        self.remote = remote or os.environ.get("OPENBLADE_REMOTE", "")
        self.casos = [c.strip() for c in case.split(",") if c.strip()]
        self.case = self.casos[0] if self.casos else "openfoam_case"
        self.historial = {"t": [], "res": {}, "cl": [], "cd": []}
        self._busy = False

        self._build_ui()

        self._datos_listos.connect(self._aplicar)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refrescar)
        if self.remote:
            self.timer.start(15000)
            QTimer.singleShot(300, self.refrescar)

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        # barra superior
        top = QHBoxLayout()
        top.addWidget(QLabel("Servidor:"))
        self.ed_remote = QLineEdit(self.remote)
        self.ed_remote.setPlaceholderText("usuario@host")
        top.addWidget(self.ed_remote, 1)
        top.addWidget(QLabel("Caso:"))
        self.cb_case = QComboBox()
        self.cb_case.setEditable(True)
        self.cb_case.addItems(self.casos)
        self.cb_case.setMinimumWidth(240)
        self.cb_case.activated.connect(lambda _i: self._conectar())
        top.addWidget(self.cb_case)
        self.btn_conectar = QPushButton("Conectar")
        self.btn_conectar.clicked.connect(self._conectar)
        top.addWidget(self.btn_conectar)
        lay.addLayout(top)

        # estado en una línea grande
        self.lbl_estado = QLabel("Sin conexión")
        self.lbl_estado.setStyleSheet(
            "background:#1e2b36; color:#e6f1fa; padding:10px; "
            "border-radius:4px; font-family:Menlo,monospace; font-size:12px;")
        self.lbl_estado.setWordWrap(True)
        lay.addWidget(self.lbl_estado)

        # gráfica
        self.fig = Figure(figsize=(5, 5.2), dpi=90)
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(311)
        self.ax_cl = self.fig.add_subplot(312)
        self.ax_cd = self.fig.add_subplot(313)
        self.fig.patch.set_facecolor("#1e1e1e")
        for ax in (self.ax, self.ax_cl, self.ax_cd):
            self._estilo(ax)
        self.ax.set_yscale("log")
        self.ax.set_title("Residuales desde que se abrió el panel (escala log)",
                          color="white", fontsize=10)
        self.fig.subplots_adjust(left=0.12, right=0.97, top=0.95, bottom=0.08,
                                 hspace=0.45)
        lay.addWidget(self.canvas, 1)

        # métricas del servidor
        self.lbl_server = QLabel("—")
        self.lbl_server.setStyleSheet(
            "background:#12222e; color:#cfe6f7; padding:8px; "
            "border-radius:4px; font-family:Menlo,monospace; font-size:10px;")
        lay.addWidget(self.lbl_server)

    @staticmethod
    def _estilo(ax) -> None:
        ax.set_facecolor("#1e1e1e")
        ax.tick_params(colors="white", labelsize=8)
        for sp in ax.spines.values():
            sp.set_color("#555")
        ax.grid(True, which="both", ls="--", alpha=0.25, color="#888")

    # ------------------------------------------------------------ control
    def _conectar(self) -> None:
        self.remote = self.ed_remote.text().strip()
        nuevo = self.cb_case.currentText().strip() or "openfoam_case"
        if nuevo != self.case:
            self.historial = {"t": [], "res": {}, "cl": [], "cd": []}
        self.case = nuevo
        if self.remote:
            self.timer.start(15000)
            self.refrescar()
        else:
            self.timer.stop()
            self.lbl_estado.setText("Sin servidor configurado")

    def refrescar(self) -> None:
        """Pide los datos al servidor en un hilo aparte."""
        if not self.remote or self._busy:
            return
        self._busy = True

        def trabajo():
            cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                   self.remote,
                   f"cd ~/OpenBlade && ~/obenv/bin/python validation/monitor.py "
                   f"--case {self.case} --json"]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=40, stdin=subprocess.DEVNULL)
                if r.returncode != 0:
                    self._datos_listos.emit({"error": (r.stderr or "")[-200:]})
                    return
                self._datos_listos.emit(json.loads(r.stdout.strip().splitlines()[-1]))
            except Exception as e:  # noqa: BLE001
                self._datos_listos.emit({"error": str(e)})

        threading.Thread(target=trabajo, daemon=True).start()

    # ------------------------------------------------------------ pintado
    def _aplicar(self, d) -> None:
        self._busy = False
        if not d:
            return
        # respuesta de un caso anterior al cambio de selector
        if d.get("caso") and d["caso"] != os.path.basename(self.case.rstrip("/")):
            return
        if "error" in d:
            self.lbl_estado.setText(f"⚠️ {d['error'][:200]}")
            return

        estado = {"COMPLETADA": "✔ COMPLETADA", "EN_CURSO": "⏳ EN CURSO",
                  "DIVERGIDO": "💥 DIVERGIDO"}.get(d.get("estado"), "⏸ PARADA")

        t = d.get("t")
        end = d.get("endTime")
        pct = d.get("pct") or 0
        n = 30
        llenos = int(n * min(pct, 100) / 100)
        barra = "█" * llenos + "░" * (n - llenos)

        txt = f"{estado}   {d.get('caso','')}   ({d.get('procesos',0)} procesos)\n"
        if t is not None and end:
            txt += f"t = {t:.5f} / {end:g} s   [{barra}] {pct:.1f}%\n"
        txt += f"pasos: {d.get('pasos',0):,}   tiempos escritos: {d.get('tiempos_escritos',0)}"
        if d.get("continuidad") is not None:
            txt += f"   continuidad: {d['continuidad']:.1e}"
        c = d.get("coeffs")
        if c:
            txt += f"\nCl = {c['Cl']:+.5f}   Cd = {c['Cd']:.5f}"
        self.lbl_estado.setText(txt)

        # serie temporal
        if t is not None:
            self.historial["t"].append(t)
            for k, v in (d.get("residuales") or {}).items():
                self.historial["res"].setdefault(k, []).append(v)
            # limitar para no crecer sin fin
            if len(self.historial["t"]) > 600:
                self.historial["t"] = self.historial["t"][-600:]
                for k in self.historial["res"]:
                    self.historial["res"][k] = self.historial["res"][k][-600:]
            self._dibujar((c or {}).get("serie") or [])

        s = d.get("servidor") or {}
        partes = []
        if s.get("cpu_pct") is not None:
            partes.append(f"CPU {s['cpu_pct']:.0f}%")
        if s.get("ram_pct") is not None:
            partes.append(f"RAM {s['ram_pct']:.0f}% ({s['ram_usada_gb']:.1f}/"
                          f"{s['ram_total_gb']:.0f} GB)")
        if s.get("disco_libre_gb") is not None:
            partes.append(f"Disco {s['disco_libre_gb']:.0f} GB libre")
        if s.get("carga"):
            partes.append(f"carga {s['carga'][0]}")
        self.lbl_server.setText("   ·   ".join(partes) or "—")

    def _dibujar(self, serie_fuerzas) -> None:
        self.ax.clear()
        self.ax.set_yscale("log")
        colores = {"Ux": "#4fc3f7", "Uy": "#81c784", "Uz": "#a1887f",
                   "p": "#ffb74d", "k": "#e57373", "omega": "#ba68c8",
                   "epsilon": "#4db6ac", "nuTilda": "#90a4ae"}
        for k, serie in self.historial["res"].items():
            if serie:
                self.ax.plot(self.historial["t"][:len(serie)], serie,
                             label=k, lw=1.2,
                             color=colores.get(k, "#cccccc"))
        if self.historial["res"]:
            leg = self.ax.legend(fontsize=7, loc="upper right",
                                 facecolor="#2a2a2a", edgecolor="#555")
            for t in leg.get_texts():
                t.set_color("white")
        self._estilo(self.ax)
        self.ax.set_title("Residuales desde que se abrió el panel (escala log)",
                          color="white", fontsize=10)

        # Historia completa del caso, leida del servidor
        for ax, col, nombre, color in ((self.ax_cl, 2, "Cl", "#4fc3f7"),
                                       (self.ax_cd, 1, "Cd", "#ffb74d")):
            ax.clear()
            self._estilo(ax)
            ax.set_title(f"{nombre} (historia del caso)", color="white",
                         fontsize=10)
            if serie_fuerzas:
                ax.plot([f[0] for f in serie_fuerzas],
                        [f[col] for f in serie_fuerzas], lw=1.0, color=color)
                # El arranque (Cl ~ +-20) aplastaria la escala: el eje y se
                # ajusta a la ultima mitad, que es donde se juzga la convergencia.
                cola = [f[col] for f in serie_fuerzas[len(serie_fuerzas) // 2:]]
                margen = 0.1 * (max(cola) - min(cola)) or abs(cola[-1]) * 0.01 or 1e-6
                ax.set_ylim(min(cola) - margen, max(cola) + margen)
        self.canvas.draw_idle()
