"""Un solo proceso por trabajo: la ventana y la linea de ordenes comparten datos.

Sin esto, abrir la ventana mientras `core.cli polar` esta vivo reenvia los
paquetes que aun no habian salido y hace attach a los que corren: el mismo
paquete se calcula dos veces y los dos procesos escriben su job.json.
"""

import json
import os
import subprocess
import sys

import pytest

from core import owner
from core.defaults import case_params
from core.jobs import PENDIENTE, TERMINADO, load_jobs, new_job


def _dueno_vivo(job):
    """Un proceso de verdad, que existe mientras dure la prueba."""
    otro = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    d = owner.yo()
    d.update(pid=otro.pid, arranque=owner._arranque(otro.pid))
    with open(os.path.join(job.folder, owner.ARCHIVO), "w") as f:
        json.dump(d, f)
    return otro


def _dueno_muerto(job):
    otro = subprocess.Popen([sys.executable, "-c", "pass"])
    otro.wait()
    d = owner.yo()
    d.update(pid=otro.pid, arranque=owner._arranque(otro.pid))
    with open(os.path.join(job.folder, owner.ARCHIVO), "w") as f:
        json.dump(d, f)
    return otro.pid


def test_a_pending_job_with_a_live_owner_is_not_resent():
    job = new_job(case_params(aoa=6.0), "u@h", 2)
    otro = _dueno_vivo(job)
    try:
        assert owner.de_otro(job) is not None
        with pytest.raises(owner.OwnerError, match=str(otro.pid)):
            owner.reclamar(job)
        # Y sigue pendiente: nadie lo ha marcado como detenido ni lo ha reescrito.
        guardado = next(j for j in load_jobs() if j.id == job.id)
        assert guardado.state == PENDIENTE
    finally:
        otro.kill()
        otro.wait()


def test_a_pending_job_whose_owner_is_gone_can_be_taken():
    job = new_job(case_params(aoa=6.0), "u@h", 2)
    _dueno_muerto(job)
    assert owner.de_otro(job) is None
    assert owner.reclamar(job)["pid"] == os.getpid()
    assert owner.de_otro(job) is None          # el dueno soy yo: no estorba


def test_the_owner_is_released_when_the_job_ends():
    job = new_job(case_params(aoa=6.0), "u@h", 2)
    owner.reclamar(job)
    assert owner.leer(job) is not None
    owner.liberar(job)
    assert owner.leer(job) is None


def test_a_reused_pid_is_not_taken_for_the_owner():
    # El sistema reutiliza los pid: el mismo numero con otra hora de arranque es otro proceso.
    job = new_job(case_params(aoa=6.0), "u@h", 2)
    d = owner.yo()
    d.update(pid=os.getpid(), arranque=(d["arranque"] or 0) - 3600)
    with open(os.path.join(job.folder, owner.ARCHIVO), "w") as f:
        json.dump(d, f)
    assert owner.de_otro(job) is None
    assert owner.reclamar(job)["pid"] == os.getpid()


def test_an_owner_from_another_machine_does_not_block_this_one():
    job = new_job(case_params(aoa=6.0), "u@h", 2)
    d = owner.yo()
    d.update(maquina="otra-maquina")
    with open(os.path.join(job.folder, owner.ARCHIVO), "w") as f:
        json.dump(d, f)
    assert owner.de_otro(job) is None


def test_the_window_leaves_alone_what_another_process_is_running():
    """La ventana no reenvia ni hace attach a un trabajo con dueno vivo."""
    from core.jobs import ACTIVOS, SUBIENDO

    job = new_job(case_params(aoa=6.0), "u@h", 2)
    job.state, job.step = SUBIENDO, "subiendo"
    job.save()
    otro = _dueno_vivo(job)
    try:
        from gui import main_window as mw

        ventana = mw.MainWindow.__new__(mw.MainWindow)     # sin Qt: solo el metodo
        enviados, seguidos, dichos = [], [], []
        ventana.dispatcher = type("D", (), {
            "jobs": {}, "submit": enviados.append, "attach": seguidos.append})()
        ventana.jobs_panel = type("P", (), {"add_job": staticmethod(lambda _j: None)})()
        ventana.log = dichos.append
        ventana._sync_machines = lambda: None
        ventana._select_job = lambda _i: None

        ventana._restore_jobs()

        assert job.id not in {j.id for j in enviados}
        assert job.id not in {j.id for j in seguidos}
        assert job.id in ventana.dispatcher.jobs       # se ve, pero no se toca
        assert any("otro proceso" in t for t in dichos)
        assert any(str(otro.pid) in t for t in dichos)
    finally:
        otro.kill()
        otro.wait()


def test_the_window_does_resend_when_the_owner_is_gone():
    from core.jobs import PENDIENTE

    job = new_job(case_params(aoa=6.0), "u@h", 2)
    job.state = PENDIENTE
    job.save()
    _dueno_muerto(job)

    from gui import main_window as mw

    ventana = mw.MainWindow.__new__(mw.MainWindow)
    enviados, seguidos = [], []
    ventana.dispatcher = type("D", (), {
        "jobs": {}, "submit": enviados.append, "attach": seguidos.append})()
    ventana.jobs_panel = type("P", (), {"add_job": staticmethod(lambda _j: None)})()
    ventana.log = lambda _t: None
    ventana._sync_machines = lambda: None
    ventana._select_job = lambda _i: None

    ventana._restore_jobs()

    assert job.id in {j.id for j in enviados}
    assert job.id not in {j.id for j in seguidos}


def test_a_finished_job_is_never_resent():
    job = new_job(case_params(aoa=6.0), "u@h", 2)
    job.state = TERMINADO
    job.save()

    from gui import main_window as mw

    ventana = mw.MainWindow.__new__(mw.MainWindow)
    enviados, seguidos = [], []
    ventana.dispatcher = type("D", (), {
        "jobs": {}, "submit": enviados.append, "attach": seguidos.append})()
    ventana.jobs_panel = type("P", (), {"add_job": staticmethod(lambda _j: None)})()
    ventana.log = lambda _t: None
    ventana._sync_machines = lambda: None
    ventana._select_job = lambda _i: None

    ventana._restore_jobs()

    assert job.id not in {j.id for j in enviados}
    assert job.id not in {j.id for j in seguidos}


def test_a_job_owned_by_another_process_is_not_run(monkeypatch):
    """run_job no toca un trabajo ajeno: ni malla, ni envio, ni job.json."""
    from core import jobs as J

    job = new_job(case_params(aoa=6.0), "u@h", 2)
    otro = _dueno_vivo(job)
    llamadas = []
    monkeypatch.setattr(J, "ensure_mesh", lambda *a, **k: llamadas.append("malla"))

    class Eventos(J.Events):
        def __init__(self):
            self.dichos = []

        def log(self, _j, texto):
            self.dichos.append(texto)

    ev = Eventos()
    try:
        J.run_job(job, ev, poll_s=0.01)
        assert llamadas == []
        assert job.state == PENDIENTE          # no se marca detenido ni terminado
        assert any(str(otro.pid) in t for t in ev.dichos)
        assert any("otro proceso" in t for t in ev.dichos)
    finally:
        otro.kill()
        otro.wait()


def test_a_job_with_no_owner_file_is_left_alone_while_a_cli_campaign_runs(monkeypatch):
    """Lo lanzado antes de este arreglo no tiene dueno: con una campana viva, no se reenvia."""
    job = new_job(case_params(aoa=6.0), "u@h", 2)
    assert owner.leer(job) is None                  # trabajo antiguo, sin archivo de dueno
    monkeypatch.setattr(owner, "hay_cli_vivo", lambda: True)

    from gui import main_window as mw

    ventana = mw.MainWindow.__new__(mw.MainWindow)
    enviados, seguidos, dichos = [], [], []
    ventana.dispatcher = type("D", (), {
        "jobs": {}, "submit": enviados.append, "attach": seguidos.append})()
    ventana.jobs_panel = type("P", (), {"add_job": staticmethod(lambda _j: None)})()
    ventana.log = dichos.append
    ventana._sync_machines = lambda: None
    ventana._select_job = lambda _i: None

    ventana._restore_jobs()

    assert job.id not in {j.id for j in enviados}
    assert any("sin dueño anotado" in t for t in dichos)


def test_without_a_cli_campaign_an_old_pending_job_is_resent(monkeypatch):
    job = new_job(case_params(aoa=6.0), "u@h", 2)
    monkeypatch.setattr(owner, "hay_cli_vivo", lambda: False)

    from gui import main_window as mw

    ventana = mw.MainWindow.__new__(mw.MainWindow)
    enviados = []
    ventana.dispatcher = type("D", (), {
        "jobs": {}, "submit": enviados.append, "attach": staticmethod(lambda _j: None)})()
    ventana.jobs_panel = type("P", (), {"add_job": staticmethod(lambda _j: None)})()
    ventana.log = lambda _t: None
    ventana._sync_machines = lambda: None
    ventana._select_job = lambda _i: None

    ventana._restore_jobs()

    assert job.id in {j.id for j in enviados}
