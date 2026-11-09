"""Retomar un trabajo que su maquina ya termino, sin volver a calcularlo."""

import json
import os

import pytest

from core import jobs as J
from core import owner
from core.cli import cmd_retomar
from core.defaults import case_params
from core.jobs import FALLIDO, TERMINADO, new_job


class Args:
    def __init__(self, trabajos, si_terminado=False):
        self.trabajos = list(trabajos)
        self.si_terminado = si_terminado


def _un_fallido_como_los_de_hoy(monkeypatch, estado_servidor):
    """Un trabajo fallido con el calculo ya hecho en el servidor.

    Es el caso de los control_a8 del 8-nov: la Mac los marco fallidos por un error
    suyo, pero en la maquina el solver habia terminado bien.
    """
    job = new_job(case_params(aoa=8.0), "u@h", 8)
    job.state, job.remote_dir, job.rc = FALLIDO, "openblade_jobs/x", None
    job.error = "'str' object has no attribute 'stdout'"
    job.save()

    class Runner:
        job_dir = "openblade_jobs/x"
        ficha_sha256 = None

        def __init__(self):
            self.descargado = False

        def estado(self):
            return estado_servidor

        def comprobar_ficha(self, est):
            pass

        def leer_log(self):
            return ""

        def descargar(self, case_dir):
            self.descargado = True

        def limpiar(self):
            pass

        def subir(self, *a, **k):
            raise AssertionError("no debe volver a enviarse: el calculo ya esta hecho")

        def terminar_en(self, iteracion):
            pass

    runner = Runner()
    monkeypatch.setattr(J, "make_runner", lambda j: runner)
    monkeypatch.setattr("core.jobs.make_runner", lambda j: runner)
    monkeypatch.setattr(owner, "de_otro", lambda j: None)
    return job, runner


def test_a_failed_job_whose_machine_finished_is_downloaded_without_recomputing(monkeypatch):
    """El sintoma de hoy: la Mac lo dio por fallido y no lo descargo."""
    job, runner = _un_fallido_como_los_de_hoy(
        monkeypatch, {"state": "done", "rc": 0, "error": "", "step": 3})
    assert cmd_retomar(Args([job.id])) == 0
    otra_vez = next(j for j in J.load_jobs() if j.id == job.id)
    assert otra_vez.state == TERMINADO, f"quedo en {otra_vez.state}: {otra_vez.error}"
    assert runner.descargado, "no se descargo el resultado"


def test_a_job_that_is_still_running_is_left_alone_with_si_terminado(monkeypatch):
    """Con --si-terminado no se espera a los que siguen calculando."""
    job, runner = _un_fallido_como_los_de_hoy(
        monkeypatch, {"state": "running", "step": "solver"})
    assert cmd_retomar(Args([job.id], si_terminado=True)) == 0
    otra_vez = next(j for j in J.load_jobs() if j.id == job.id)
    assert otra_vez.state == FALLIDO, "no debio tocarse"


def test_a_job_that_really_failed_on_the_server_is_not_retaken(monkeypatch):
    """Si alla fallo de verdad, no hay nada que descargar: se avisa y no se toca."""
    job, runner = _un_fallido_como_los_de_hoy(
        monkeypatch, {"state": "failed", "rc": 1, "error": "solver diverge", "step": 3})
    cmd_retomar(Args([job.id]))
    otra_vez = next(j for j in J.load_jobs() if j.id == job.id)
    assert otra_vez.state == FALLIDO
    assert not runner.descargado


def test_a_job_owned_by_another_live_process_is_not_touched(monkeypatch):
    """Dos procesos sobre el mismo paquete es lo que se arreglo ayer: no se repite."""
    job, runner = _un_fallido_como_los_de_hoy(
        monkeypatch, {"state": "done", "rc": 0, "error": "", "step": 3})
    monkeypatch.setattr(owner, "de_otro", lambda j: {"pid": 1, "maquina": "otra"})
    cmd_retomar(Args([job.id]))
    otra_vez = next(j for j in J.load_jobs() if j.id == job.id)
    assert otra_vez.state == FALLIDO
    assert not runner.descargado
