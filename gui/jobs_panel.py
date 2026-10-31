"""Pestaña Trabajos: las maquinas disponibles y los paquetes enviados a cada una."""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QInputDialog,
                            QLabel, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                            QVBoxLayout, QWidget)

from core import paths
from core.jobs import ACTIVOS, LOCAL, PENDIENTE, Job, Machine

COL_TRABAJOS = ["Trabajo", "Máquina", "Estado", "Veredicto", "Cl", "Cd", "y+ medio"]


def _archivo_maquinas() -> str:
    return os.path.join(paths.data_root(), "machines.json")


def _cargar_maquinas() -> List[Dict]:
    try:
        with open(_archivo_maquinas()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return [{"host": LOCAL, "nproc": 4, "slots": 1, "usar": False}]


class JobsPanel(QWidget):
    job_selected = Signal(str)
    stop_requested = Signal(str)
    remove_requested = Signal(str)
    machines_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        lay.addWidget(QLabel("<b>Máquinas</b>: «Repartir entre máquinas» envía cada paquete "
                             "a la primera marcada que esté libre."))
        self.tabla_maquinas = QTableWidget(0, 4)
        self.tabla_maquinas.setHorizontalHeaderLabels(["Usar", "Máquina", "Procesos", "A la vez"])
        self.tabla_maquinas.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla_maquinas.setMaximumHeight(130)
        self.tabla_maquinas.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.tabla_maquinas)

        fila = QHBoxLayout()
        self.btn_agregar = QPushButton("Agregar servidor…")
        self.btn_agregar.clicked.connect(self._pedir_servidor)
        fila.addWidget(self.btn_agregar)
        fila.addStretch()
        lay.addLayout(fila)

        lay.addWidget(QLabel("<b>Trabajos</b>: cada uno tiene su carpeta. Doble clic para verlo."))
        self.tabla = QTableWidget(0, len(COL_TRABAJOS))
        self.tabla.setHorizontalHeaderLabels(COL_TRABAJOS)
        cabecera = self.tabla.horizontalHeader()
        for c in range(len(COL_TRABAJOS)):
            cabecera.setSectionResizeMode(c, QHeaderView.Stretch if c == 0 else QHeaderView.ResizeToContents)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.cellDoubleClicked.connect(lambda r, _c: self._emitir(r, self.job_selected))
        lay.addWidget(self.tabla, 1)

        acciones = QHBoxLayout()
        self.btn_ver = QPushButton("Ver en la ventana")
        self.btn_ver.clicked.connect(lambda: self._emitir(self.tabla.currentRow(), self.job_selected))
        self.btn_detener = QPushButton("Detener")
        self.btn_detener.clicked.connect(lambda: self._emitir(self.tabla.currentRow(), self.stop_requested))
        self.btn_borrar = QPushButton("Borrar carpeta local")
        self.btn_borrar.clicked.connect(lambda: self._emitir(self.tabla.currentRow(), self.remove_requested))
        for b in (self.btn_ver, self.btn_detener, self.btn_borrar):
            acciones.addWidget(b)
        acciones.addStretch()
        lay.addLayout(acciones)

        self._filas: Dict[str, int] = {}
        self._cargando = False
        for m in _cargar_maquinas():
            self._agregar_fila_maquina(m["host"], int(m.get("nproc", 4)), int(m.get("slots", 1)),
                                       bool(m.get("usar", True)))

    # ------------------------------------------------------------ maquinas
    def _agregar_fila_maquina(self, host: str, nproc: int, slots: int, usar: bool) -> None:
        self._cargando = True
        r = self.tabla_maquinas.rowCount()
        self.tabla_maquinas.insertRow(r)
        marca = QCheckBox()
        marca.setChecked(usar)
        marca.stateChanged.connect(lambda _s: self._maquinas_editadas())
        self.tabla_maquinas.setCellWidget(r, 0, marca)
        self.tabla_maquinas.setItem(r, 1, QTableWidgetItem(host))
        for col, valor, tope in ((2, nproc, 512), (3, slots, 32)):
            caja = QSpinBox()
            caja.setRange(1, tope)
            caja.setValue(valor)
            caja.valueChanged.connect(lambda _v: self._maquinas_editadas())
            self.tabla_maquinas.setCellWidget(r, col, caja)
        self._cargando = False

    def _filas_maquinas(self) -> List[Dict]:
        filas = []
        for r in range(self.tabla_maquinas.rowCount()):
            filas.append({"host": self.tabla_maquinas.item(r, 1).text(),
                          "usar": self.tabla_maquinas.cellWidget(r, 0).isChecked(),
                          "nproc": self.tabla_maquinas.cellWidget(r, 2).value(),
                          "slots": self.tabla_maquinas.cellWidget(r, 3).value()})
        return filas

    def _maquinas_editadas(self) -> None:
        if self._cargando:
            return
        try:
            with open(_archivo_maquinas(), "w") as f:
                json.dump(self._filas_maquinas(), f)
        except OSError:
            pass
        self.machines_changed.emit()

    def machines(self) -> List[Machine]:
        """Las maquinas marcadas, en el orden de la tabla."""
        return [Machine(m["host"], m["nproc"], m["slots"]) for m in self._filas_maquinas() if m["usar"]]

    def all_machines(self) -> List[Machine]:
        """Todas: un trabajo con maquina fija respeta sus limites aunque no este marcada."""
        return [Machine(m["host"], m["nproc"], m["slots"], m["usar"]) for m in self._filas_maquinas()]

    def add_machine(self, host: str, nproc: int = 8, usar: bool = True) -> None:
        if any(m["host"] == host for m in self._filas_maquinas()):
            return
        self._agregar_fila_maquina(host, nproc, 1, usar)
        self._maquinas_editadas()

    def _pedir_servidor(self) -> None:
        from core.remote_runner import RemoteError, validar_host
        host, ok = QInputDialog.getText(self, "Agregar servidor", "usuario@host:")
        if not ok:
            return
        try:
            self.add_machine(validar_host(host))
        except RemoteError as e:
            self.window().log(f"❌ {e}")

    # ------------------------------------------------------------ trabajos
    def _emitir(self, fila: int, senal) -> None:
        if fila < 0:
            return
        for identificador, r in self._filas.items():
            if r == fila:
                senal.emit(identificador)
                return

    def add_job(self, job: Job) -> None:
        r = self.tabla.rowCount()
        self.tabla.insertRow(r)
        self._filas[job.id] = r
        for c in range(len(COL_TRABAJOS)):
            self.tabla.setItem(r, c, QTableWidgetItem(""))
        self.update_job(job)

    def remove_job(self, job_id: str) -> None:
        r = self._filas.pop(job_id, None)
        if r is None:
            return
        self.tabla.removeRow(r)
        self._filas = {i: (f - 1 if f > r else f) for i, f in self._filas.items()}

    def select_row(self, job_id: str) -> None:
        r = self._filas.get(job_id)
        if r is not None:
            self.tabla.selectRow(r)

    def update_job(self, job: Job) -> None:
        r = self._filas.get(job.id)
        if r is None:
            return
        analisis = job.analysis or {}
        v = analisis.get("verdict") or {}
        yp = analisis.get("yplus") or {}
        estado = job.state if not job.step or job.state not in ACTIVOS else f"{job.state}: {job.step}"
        utiles = v.get("state") in ("CONVERGIDO", "NO CONVERGIDO") and v.get("cl") is not None
        valores = [job.label, job.host or "(primera libre)", estado, v.get("state", ""),
                   f"{v['cl']:.4f}" if utiles else "", f"{v['cd']:.5f}" if utiles else "",
                   f"{yp['mean']:.2f}" if yp else ""]
        for c, texto in enumerate(valores):
            item = self.tabla.item(r, c)
            item.setText(texto)
            item.setToolTip(job.error or v.get("reason", "") if c in (2, 3) else job.id)
        color = {"CONVERGIDO": Qt.darkGreen, "DIVERGIDO": Qt.red,
                 "NO CONVERGIDO": Qt.darkYellow}.get(v.get("state"))
        if color is not None:
            self.tabla.item(r, 3).setForeground(color)
