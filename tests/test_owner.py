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


def test_a_running_job_with_no_owner_file_is_not_attached_while_a_cli_runs(monkeypatch):
    """El hueco que quedaba: un activo con remote_dir y sin dueno.json.

    La proteccion solo cubria a los pendientes. Un activo con remote_dir caia en
    `attach`, y en run_job `reclamar` salia bien porque no habia archivo: la ventana
    anotaba como suyo un trabajo que ya llevaba la linea de ordenes, y los dos
    seguian, descargaban y escribian el mismo job.json.
    """
    from core.jobs import CORRIENDO

    job = new_job(case_params(aoa=6.0), "u@h", 2)
    job.state, job.remote_dir = CORRIENDO, "openblade_jobs/x"
    job.save()
    assert owner.leer(job) is None                  # anterior al archivo de dueno
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

    assert job.id not in {j.id for j in seguidos}   # no se le sigue el rastro
    assert job.id not in {j.id for j in enviados}
    assert any("sin dueño anotado" in t for t in dichos)


def test_a_running_job_with_no_owner_file_is_attached_without_a_cli(monkeypatch):
    """Sin otra campana viva no hay nadie mas: se sigue, que es lo util al reabrir."""
    from core.jobs import CORRIENDO

    job = new_job(case_params(aoa=6.0), "u@h", 2)
    job.state, job.remote_dir = CORRIENDO, "openblade_jobs/x"
    job.save()
    monkeypatch.setattr(owner, "hay_cli_vivo", lambda: False)

    from gui import main_window as mw

    ventana = mw.MainWindow.__new__(mw.MainWindow)
    seguidos = []
    ventana.dispatcher = type("D", (), {
        "jobs": {}, "submit": staticmethod(lambda _j: None), "attach": seguidos.append})()
    ventana.jobs_panel = type("P", (), {"add_job": staticmethod(lambda _j: None)})()
    ventana.log = lambda _t: None
    ventana._sync_machines = lambda: None
    ventana._select_job = lambda _i: None

    ventana._restore_jobs()

    assert job.id in {j.id for j in seguidos}


def _retomar(job_id, etiqueta, params, barrera, cola):
    """Retoma un trabajo desde otro proceso. Va a nivel de modulo para poder usar spawn.

    La ventana entre comprobar y anotar se ensancha a proposito (200 ms dentro de
    de_otro): con el candado, el segundo ni siquiera llega a comprobar hasta que el
    primero ha anotado, asi que el resultado no depende del planificador.
    """
    import time

    from core import owner as O
    from core.jobs import Job

    real = O.de_otro

    def lento(j):
        visto = real(j)
        time.sleep(0.2)
        return visto

    O.de_otro = lento
    job = Job(job_id, etiqueta, dict(params))
    barrera.wait(15)          # los dos llegan a la vez, con el trabajo libre
    try:
        cola.put(("gano", O.reclamar(job)["pid"]))
    except O.OwnerError:
        cola.put(("perdio", None))


def test_two_processes_retaking_at_once_cannot_both_own_the_job():
    """Dos retomando a la vez: comprobar y anotar iban sueltos y pasaban los dos.

    El archivo de dueno evitaba el caso lento (uno ya anotado), no el simultaneo:
    los dos leian "libre", los dos escribian y los dos se creian duenos. Ahora la
    comprobacion y la escritura van bajo un candado.
    """
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    job = new_job(case_params(aoa=6.0), "u@h", 2)
    cola, barrera = ctx.Queue(), ctx.Barrier(2)
    hijos = [ctx.Process(target=_retomar,
                         args=(job.id, job.label, dict(job.params), barrera, cola))
             for _ in range(2)]
    for h in hijos:
        h.start()
    dicho = [cola.get(timeout=60) for _ in hijos]
    for h in hijos:
        h.join(60)

    ganadores = [d for d in dicho if d[0] == "gano"]
    assert len(ganadores) == 1, dicho          # uno solo, ni dos ni ninguno
    anotado = owner.leer(job)
    assert anotado is not None and anotado["pid"] == ganadores[0][1]


def test_the_lock_is_left_clean_after_claiming():
    job = new_job(case_params(aoa=6.0), "u@h", 2)
    owner.reclamar(job)
    assert not os.path.exists(os.path.join(job.folder, owner.CANDADO))


def _procesos(monkeypatch, lineas, real):
    """Hace que `hay_cli_vivo` lea una tabla de procesos dada, ejecutando la de verdad."""
    from core import owner as O

    monkeypatch.setattr(O, "hay_cli_vivo", real)
    salida = "\n".join(lineas)

    class R:
        stdout = salida

    monkeypatch.setattr(O.subprocess, "run", lambda *a, **k: R())
    monkeypatch.setattr(O, "_existe", lambda pid: True)


def test_only_a_python_running_a_campaign_counts_as_a_live_one(monkeypatch, sin_campanas_ajenas):
    """Un `doctor` suelto o un shell que menciona el comando no llevan trabajos.

    Contarlos dejaba la ventana sin retomar nada mientras hubiera un proceso
    cualquiera con ese texto en su linea de ordenes.
    """
    _procesos(monkeypatch, [
        "  111 /usr/bin/python3 -m core.cli doctor",
        "  112 /bin/zsh -c eval 'python3 -m core.cli polar --angulos 0,4'",
        "  113 /usr/bin/vim /tmp/notas/core.cli.txt",
    ], sin_campanas_ajenas)
    assert owner.hay_cli_vivo() is False

    _procesos(monkeypatch, ["  114 /usr/bin/python3 -m core.cli polar --angulos 0,4"],
              sin_campanas_ajenas)
    assert owner.hay_cli_vivo() is True

    _procesos(monkeypatch, ["  115 /usr/bin/python3 -m core.cli banco",
                            "  116 /usr/bin/python3 -m core.cli control --hosts a,b"],
              sin_campanas_ajenas)
    assert owner.hay_cli_vivo() is True


def test_this_very_process_never_counts_as_another_campaign(monkeypatch, sin_campanas_ajenas):
    """El proceso que pregunta no es una campana ajena, aunque su linea lo parezca.

    Sin esto, una ventana abierta desde un `python3 -m core.cli ...` se bloquearia
    a si misma y no retomaria nada.
    """
    _procesos(monkeypatch, [f"  {os.getpid()} /usr/bin/python3 -m core.cli polar --angulos 0"],
              sin_campanas_ajenas)
    assert owner.hay_cli_vivo() is False
