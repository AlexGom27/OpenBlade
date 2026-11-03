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
    OPENBLADE_REMOTE=usuario@servidor-a
OPENBLADE_REMOTE_CASE admite varios casos separados por comas: el primero se
abre al iniciar y el resto queda en el selector.

Si no se define, el panel queda inactivo y lo dice.
"""

from __future__ import annotations

import os
import threading

from qtpy.QtCore import Qt, QTimer, Signal
from qtpy.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                            QLineEdit, QPushButton, QScrollArea, QSplitter, QTabWidget, QTableWidget,
                            QTableWidgetItem, QVBoxLayout, QWidget)

from .plots import new_chart, style_axes


class RemoteMonitorPanel(QWidget):
    """Panel con estado, gráficas y métricas del servidor."""

    _datos_listos = Signal(object)
    _resumen_listo = Signal(object)

    def __init__(self, remote: str = "", case: str = "openfoam_case",
                 parent=None) -> None:
        super().__init__(parent)
        self.remote = remote or os.environ.get("OPENBLADE_REMOTE", "")
        self.casos = [c.strip() for c in case.split(",") if c.strip()]
        self.case = self.casos[0] if self.casos else "openfoam_case"
        self.historial = {"t": [], "res": {}, "cl": [], "cd": []}
        self._serie = []
        self._busy = False
        self.hosts: list = []
        self._resumenes: dict = {}
        self._busy_resumen = False

        self._build_ui()

        self._datos_listos.connect(self._aplicar)
        self._resumen_listo.connect(self._aplicar_resumen)
        self.timer_resumen = QTimer(self)
        self.timer_resumen.timeout.connect(self.refrescar_resumen)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refrescar)
        if self.remote:
            self.timer.start(15000)
            QTimer.singleShot(300, self.refrescar)

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        # Dos partes con un divisor que se arrastra: arriba tablas y estado, con su propia
        # barra de desplazamiento; abajo las graficas. Las graficas de matplotlib dentro de
        # un QScrollArea redimensionable entran en recursion de tamanos y tiran la ventana.
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        self.divisor = QSplitter(Qt.Vertical)
        self.divisor.setChildrenCollapsible(False)
        externo.addWidget(self.divisor)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        contenido = QWidget()
        self.scroll.setWidget(contenido)
        self.divisor.addWidget(self.scroll)
        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(8, 8, 8, 8)

        # Todos los servidores y todos sus casos: lo que corre, lo que espera en su cola y
        # lo que termino en las ultimas 48 h. Un clic en un caso lo muestra abajo.
        lay.addWidget(QLabel("<b>Servidores</b>"))
        self.tabla_servidores = QTableWidget(0, 5)
        self.tabla_servidores.setHorizontalHeaderLabels(
            ["Servidor", "Conexión", "CPU", "Corriendo / en cola", "Procesos OpenFOAM"])
        self.tabla_servidores.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tabla_servidores.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla_servidores.setMinimumHeight(100)
        self.tabla_servidores.setMaximumHeight(140)
        lay.addWidget(self.tabla_servidores)
        lay.addWidget(QLabel("<b>Casos en los servidores</b> (clic para ver su detalle)"))
        self.tabla_casos = QTableWidget(0, 5)
        self.tabla_casos.setHorizontalHeaderLabels(["Caso", "Servidor", "Estado", "Avance", "Iteración"])
        cab = self.tabla_casos.horizontalHeader()
        cab.setSectionResizeMode(QHeaderView.ResizeToContents)
        cab.setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabla_casos.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla_casos.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla_casos.setMinimumHeight(180)
        self.tabla_casos.setMaximumHeight(260)
        self.tabla_casos.cellClicked.connect(self._caso_elegido)
        lay.addWidget(self.tabla_casos)

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
        # Escribir servidor y caso a mano queda para lo que no salga en las tablas.
        for w in (self.ed_remote, self.cb_case, self.btn_conectar):
            w.setVisible(False)
        for i in range(top.count()):
            item = top.itemAt(i).widget()
            if isinstance(item, QLabel):
                item.setVisible(False)

        # estado en una línea grande
        self.lbl_estado = QLabel("Sin conexión")
        self.lbl_estado.setStyleSheet(
            "background:#1e2b36; color:#e6f1fa; padding:10px; "
            "border-radius:4px; font-family:Menlo,monospace; font-size:12px;")
        self.lbl_estado.setWordWrap(True)
        lay.addWidget(self.lbl_estado)

        graficas = QWidget()
        self.divisor.addWidget(graficas)
        self.divisor.setSizes([360, 480])
        lay = QVBoxLayout(graficas)
        lay.setContentsMargins(8, 0, 8, 8)

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
        self.subtabs.setMinimumHeight(260)
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
            from core.remote_runner import friendly_error
            self.lbl_estado.setText(f"⚠️ {self.remote}: {friendly_error(d.get('error') or '')}")
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

    # ------------------------------------------------------------ resumen
    ESTADOS = {"running": "En curso", "done": "Terminó", "failed": "Falló", "stopped": "Detenida"}

    def set_hosts(self, hosts) -> None:
        """Los servidores que se resumen arriba: los de la tabla de máquinas."""
        hosts = [h for h in hosts if h and h != "local"]
        if hosts == self.hosts:
            return
        self.hosts = hosts
        self._resumenes = {h: v for h, v in self._resumenes.items() if h in hosts}
        if hosts:
            self.timer_resumen.start(20000)
            QTimer.singleShot(200, self.refrescar_resumen)
        else:
            self.timer_resumen.stop()
        self._pintar_resumen()

    def refrescar_resumen(self) -> None:
        if not self.hosts or self._busy_resumen:
            return
        self._busy_resumen = True
        hosts = list(self.hosts)

        def trabajo():
            from core.remote_runner import friendly_error, resumen_servidor
            datos = {}
            for h in hosts:
                try:
                    datos[h] = resumen_servidor(h)
                except Exception as e:  # noqa: BLE001
                    datos[h] = {"host": h, "error": friendly_error(str(e))}
            self._resumen_listo.emit(datos)

        threading.Thread(target=trabajo, daemon=True).start()

    def _aplicar_resumen(self, datos) -> None:
        self._busy_resumen = False
        for h, d in datos.items():
            if "error" in d and h in self._resumenes and "casos" in self._resumenes[h]:
                # Se conservan los casos de la ultima respuesta buena, con el aviso.
                d = dict(self._resumenes[h], error=d["error"])
            self._resumenes[h] = d
        self._pintar_resumen()

    @staticmethod
    def _etiqueta(caso: str) -> str:
        """20261103_111623_naca63-3-418_abbott_a2.0_609b -> naca63-3-418_abbott_a2.0, 03/11 11:16"""
        partes = caso.split("_")
        if len(partes) > 3 and partes[0].isdigit() and partes[1].isdigit():
            return f"{'_'.join(partes[2:-1])}  ({partes[0][6:8]}/{partes[0][4:6]} {partes[1][:2]}:{partes[1][2:4]})"
        return caso

    def _pintar_resumen(self) -> None:
        self.tabla_servidores.setRowCount(len(self.hosts))
        filas = []
        for i, h in enumerate(self.hosts):
            d = self._resumenes.get(h, {})
            s = d.get("servidor") or {}
            casos = d.get("casos") or []
            corriendo = sum(1 for c in casos if c["estado"] == "running" and c["paso"] != "en cola")
            en_cola = sum(1 for c in casos if c["estado"] == "running" and c["paso"] == "en cola")
            conexion = ("⚠️ " + d["error"]) if d.get("error") else ("✅ conectado" if d else "…")
            valores = [h.split("@")[-1], conexion,
                       f"{s['cpu_pct']:.0f} %" if s.get("cpu_pct") is not None else "—",
                       f"{corriendo} / {en_cola}" if d.get("casos") is not None else "—",
                       str(s.get("procesos", "—"))]
            for j, v in enumerate(valores):
                self.tabla_servidores.setItem(i, j, QTableWidgetItem(v))
            for c in casos:
                filas.append((h, c))
        orden = {"running": 0, "failed": 1, "stopped": 2, "done": 3}
        filas.sort(key=lambda f: (orden.get(f[1]["estado"], 4) + (0.5 if f[1]["paso"] == "en cola" else 0),
                                  f[1]["caso"]), reverse=False)
        self.tabla_casos.setRowCount(len(filas))
        self._filas_casos = filas
        for i, (h, c) in enumerate(filas):
            estado = "En cola" if c["estado"] == "running" and c["paso"] == "en cola" else \
                self.ESTADOS.get(c["estado"], "Sin estado")
            if c["estado"] == "running" and c["paso"] not in ("solver", "en cola", None):
                estado += f" ({c['paso']})"
            avance = f"{c['pct']:.0f} %" if c.get("pct") is not None else "—"
            it = f"{c['t']:.0f} de {c['fin']:.0f}" if c.get("t") is not None and c.get("fin") else "—"
            for j, v in enumerate([self._etiqueta(c["caso"]), h.split("@")[-1], estado, avance, it]):
                self.tabla_casos.setItem(i, j, QTableWidgetItem(v))

    def _caso_elegido(self, fila: int, _col: int) -> None:
        if 0 <= fila < len(getattr(self, "_filas_casos", [])):
            h, c = self._filas_casos[fila]
            self.watch(h, c["ruta"])

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
