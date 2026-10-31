#!/usr/bin/env python3
"""Panel de monitorización remota para la GUI de OpenBlade.

Muestra en vivo, desde la propia ventana:
  * estado y porcentaje de avance de la simulación
  * residuales de cada ecuación (gráfica log)
  * Cl y Cd
  * CPU, RAM y disco del servidor

Los datos se piden por SSH (core.remote_runner.instantanea): en el servidor no
hace falta nada instalado salvo OpenFOAM. Se usa una clave SSH sin contraseña; si
no está configurada, el panel lo indica en lugar de fallar.

Configuración
-------------
Variable de entorno (o atributo) con el destino SSH:
    OPENBLADE_REMOTE=alejandro@100.85.66.123
OPENBLADE_REMOTE_CASE admite varios casos separados por comas: el primero se
abre al iniciar y el resto queda en el selector.

Si no se define, el panel queda inactivo y lo dice.
"""

from __future__ import annotations

import os
import threading

from qtpy.QtCore import Qt, QTimer, Signal
from qtpy.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit,
                            QPushButton, QTabWidget, QVBoxLayout, QWidget)

from .plots import new_chart, style_axes


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
        self._serie = []
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
        # selector de escala
        escala = QHBoxLayout()
        escala.addWidget(QLabel("Escala:"))
        self.cb_escala = QComboBox()
        self.cb_escala.addItems(["Toda la gráfica", "Últimos 50 % (ignora el arranque)"])
        self.cb_escala.currentIndexChanged.connect(lambda _i: self._dibujar())
        escala.addWidget(self.cb_escala)
        escala.addStretch()
        lay.addLayout(escala)

        # Una subpestaña por gráfica, cada una con toda el área disponible.
        self.subtabs = QTabWidget()
        self.subtabs.setElideMode(Qt.ElideNone)
        self.fig, self.canvas, self.ax = new_chart()
        self.fig_cl, self.canvas_cl, self.ax_cl = new_chart()
        self.fig_cd, self.canvas_cd, self.ax_cd = new_chart()
        self.subtabs.addTab(self.canvas_cl, "Cl")
        self.subtabs.addTab(self.canvas_cd, "Cd")
        self.subtabs.addTab(self.canvas, "Residuales")
        self.subtabs.currentChanged.connect(lambda _i: self._dibujar())
        lay.addWidget(self.subtabs, 1)

        # métricas del servidor
        self.lbl_server = QLabel("—")
        self.lbl_server.setStyleSheet(
            "background:#12222e; color:#cfe6f7; padding:8px; "
            "border-radius:4px; font-family:Menlo,monospace; font-size:10px;")
        lay.addWidget(self.lbl_server)

    # ------------------------------------------------------------ control
    def _conectar(self) -> None:
        self.remote = self.ed_remote.text().strip()
        nuevo = self.cb_case.currentText().strip() or "openfoam_case"
        if nuevo != self.case:
            self.historial = {"t": [], "res": {}, "cl": [], "cd": []}
            self._serie = []
        self.case = nuevo
        if self.remote:
            self.timer.start(15000)
            self.refrescar()
        else:
            self.timer.stop()
            self.lbl_estado.setText("Sin servidor configurado")

    def watch(self, host: str, case: str) -> None:
        """Muestra un caso concreto, p. ej. el trabajo recien lanzado."""
        self.ed_remote.setText(host)
        if self.cb_case.findText(case) < 0:
            self.cb_case.addItem(case)
        self.cb_case.setCurrentText(case)
        self._conectar()

    def refrescar(self) -> None:
        """Pide los datos al servidor en un hilo aparte."""
        if not self.remote or self._busy:
            return
        self._busy = True

        def trabajo():
            from core.remote_runner import instantanea
            try:
                self._datos_listos.emit(instantanea(self.remote, self.case))
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
        # Sin "status" no hubo respuesta del servidor; con el, "error" es el del caso.
        if "status" not in d:
            self.lbl_estado.setText(f"⚠️ {(d.get('error') or 'Sin respuesta')[:200]}")
            return

        estado = {"running": "⏳ EN CURSO", "done": "✔ TERMINÓ", "failed": "❌ FALLÓ",
                  "stopped": "⏸ DETENIDA"}.get((d.get("status") or {}).get("state"), "⏸ SIN ESTADO")
        if d.get("veredicto"):
            estado += f"   ·   {d['veredicto']} hasta ahora"
        if d.get("error"):
            estado += f"\n{d['error']}"

        t = d.get("t")
        end = d.get("endTime")
        pct = d.get("pct") or 0
        n = 30
        llenos = int(n * min(pct, 100) / 100)
        barra = "█" * llenos + "░" * (n - llenos)

        txt = f"{estado}   {d.get('caso','')}\n"
        if t is not None and end:
            avance = f"iteración {t:.0f} de {end:g}" if d.get("estacionario") else f"t = {t:.5f} / {end:g} s"
            txt += f"{avance}   [{barra}] {pct:.1f}%\n"
        c = d.get("coeffs")
        txt += f"filas de fuerzas: {(c or {}).get('n', 0):,}"
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
            self._serie = (c or {}).get("serie") or []
            self._dibujar()

        s = d.get("servidor") or {}
        # Cuenta todos los solvers de la maquina, no solo los de este caso
        partes = [f"{d.get('procesos', 0)} procesos de OpenFOAM"]
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

    def _dibujar(self) -> None:
        solo_final = self.cb_escala.currentIndex() == 1
        tiempos = self.historial["t"]
        inicio = len(tiempos) // 2 if solo_final else 0

        self.ax.clear()
        style_axes(self.ax)
        self.ax.set_yscale("log")
        self.ax.set_title("Residuales desde que se abrió el panel", color="white", fontsize=11)
        self.ax.set_xlabel("Iteración / tiempo", color="white")
        self.ax.set_ylabel("Residuo inicial", color="white")
        colores = {"Ux": "#4fc3f7", "Uy": "#81c784", "Uz": "#a1887f",
                   "p": "#ffb74d", "k": "#e57373", "omega": "#ba68c8",
                   "epsilon": "#4db6ac", "nuTilda": "#90a4ae"}
        for k, serie in self.historial["res"].items():
            if serie:
                self.ax.plot(tiempos[inicio:len(serie)], serie[inicio:],
                             label=k, lw=1.2, color=colores.get(k, "#cccccc"))
        if self.historial["res"]:
            leg = self.ax.legend(fontsize=8, loc="upper right",
                                 facecolor="#2a2a2a", edgecolor="#555")
            for t in leg.get_texts():
                t.set_color("white")

        # Historia completa del caso, leida del servidor
        filas = self._serie[len(self._serie) // 2:] if solo_final else self._serie
        for ax, col, nombre, color in ((self.ax_cl, 2, "Cl", "#4fc3f7"),
                                       (self.ax_cd, 1, "Cd", "#ffb74d")):
            ax.clear()
            style_axes(ax)
            ax.set_title(f"{nombre}: historia del caso", color="white", fontsize=11)
            ax.set_xlabel("Iteración / tiempo", color="white")
            ax.set_ylabel(f"{nombre} [-]", color="white")
            if filas:
                ax.plot([f[0] for f in filas], [f[col] for f in filas],
                        lw=1.0, color=color)

        visible = self.subtabs.currentWidget()
        if visible is not None:
            visible.draw_idle()
