"""Trabajos con carpeta propia y reparto entre maquinas, sin OpenFOAM ni red."""

import json
import os
import threading
import time

import pytest

from core import jobs as J
from core.defaults import case_params
from core.jobs import (CORRIENDO, DETENIDO, FALLIDO, LOCAL, PENDIENTE, TERMINADO, Dispatcher, Events,
                       JobError, Machine, follow, load_jobs, mesh_key, new_job)


def test_two_jobs_created_together_do_not_share_a_folder():
    a, b = new_job(case_params()), new_job(case_params())
    assert a.id != b.id and a.folder != b.folder
    assert os.path.isdir(a.folder) and os.path.isdir(b.folder)


def test_job_survives_a_restart_of_the_program():
    a = new_job(case_params(aoa=8.0), "u@h", 4, group="g")
    a.state, a.remote_dir = CORRIENDO, "openblade_jobs/x"
    a.save()
    b = next(j for j in load_jobs() if j.id == a.id)
    assert (b.params["aoa"], b.host, b.nproc, b.group, b.state, b.remote_dir) == (
        8.0, "u@h", 4, "g", CORRIENDO, "openblade_jobs/x")


def test_same_mesh_parameters_give_the_same_key_and_others_do_not():
    gmsh = dict(mesher="gmsh")
    assert mesh_key(case_params(aoa=2.0, **gmsh)) == mesh_key(case_params(aoa=2.0, reynolds=6e6, **gmsh))
    assert mesh_key(case_params(aoa=2.0, **gmsh)) != mesh_key(case_params(aoa=4.0, **gmsh))
    assert mesh_key(case_params()) != mesh_key(case_params(farfield=100.0))


def test_cgrid_mesh_is_not_reused_for_another_reynolds():
    """La primera celda depende del Reynolds: reutilizarla dio y+ = 30 en lugar de 1."""
    base = dict(mesher="cgrid", grid_level=1, farfield=50.0)
    assert mesh_key(case_params(reynolds=1e5, **base)) != mesh_key(case_params(reynolds=6e6, **base))
    assert mesh_key(case_params(reynolds=6e6, aoa=2.0, **base)) == mesh_key(case_params(reynolds=6e6, aoa=8.0, **base))
    assert mesh_key(case_params(reynolds=6e6, yplus_target=1.0, **base)) != mesh_key(case_params(reynolds=6e6, **base))


def test_unknown_parameter_is_an_error():
    with pytest.raises(KeyError):
        case_params(reynolds_mal_escrito=1)


class _RunnerFalso:
    def __init__(self, estados, log=""):
        self.estados = list(estados)
        self.log = log
        self.detenido = False

    def leer_log(self):
        texto, self.log = self.log, ""
        return texto

    def estado(self):
        return self.estados.pop(0) if len(self.estados) > 1 else self.estados[0]

    def comprobar_ficha(self, est):
        pass


def test_follow_reports_steps_and_events_until_the_end():
    r = _RunnerFalso([{"state": "running", "step": "solver"}, {"state": "done", "step": "fin", "rc": 0}],
                     "Time = 1s\nGAMG:  Solving for p, Initial residual = 0.1, x\n    Cl    = 0.5\n")
    pasos, eventos = [], []
    est = follow(r, eventos.append, pasos.append, lambda: False, poll_s=0)
    assert est["state"] == "done" and pasos == ["solver", "fin"]
    assert ("residual", "p", 0.1, 1.0) in eventos and ("fuerza", "Cl", "0.5") in eventos


def test_network_cut_does_not_fail_the_job_and_warns_once():
    """Un corte de red marcaba como fallido un trabajo que seguia corriendo."""
    from core.remote_runner import RemoteError

    class Cortado(_RunnerFalso):
        fallos = 3

        def estado(self):
            if self.fallos:
                self.fallos -= 1
                raise RemoteError("Tailscale pide autenticarse: abre https://login.tailscale.com/a/x")
            return {"state": "done", "rc": 0}

    avisos = []
    est = follow(Cortado([{}]), lambda e: None, lambda p: None, lambda: False, poll_s=0,
                 on_notice=avisos.append)
    assert est["state"] == "done"
    assert len(avisos) == 1 and "login.tailscale.com" in avisos[0]


def test_other_ficha_is_fatal_not_a_network_cut():
    from core.remote_runner import FichaDistinta

    class Distinta(_RunnerFalso):
        def comprobar_ficha(self, est):
            raise FichaDistinta("otra ficha")

    with pytest.raises(FichaDistinta):
        follow(Distinta([{"state": "running"}]), lambda e: None, lambda p: None, lambda: False, poll_s=0)


def test_follow_returns_none_when_asked_to_let_go():
    assert follow(_RunnerFalso([{"state": "running"}]), lambda e: None, lambda p: None,
                  lambda: True, poll_s=0) is None


def test_watch_detects_when_forces_stop_changing_at_fixed_iterations():
    v = J._Vigilancia()
    for i in range(600):
        v.agrega("Cl", "0.9")
        v.agrega("Cd", "0.01")
    assert not v.convergio()
    for i in range(2000):
        v.agrega("Cl", "0.9")
        v.agrega("Cd", "0.01")
    assert not v.convergio(), "solo se mira en multiplos fijos, para que el final sea el mismo en toda maquina"
    for i in range(400):
        v.agrega("Cl", "0.9")
        v.agrega("Cd", "0.01")
    assert v.n == 3000 and v.convergio()
    assert v.final_previsto() == 6000
    # Una deriva lenta, invisible entre dos ventanas, tampoco termina
    lenta = J._Vigilancia()
    for i in range(6000):
        lenta.agrega("Cl", str(0.9 + 1e-6 * i))
        lenta.agrega("Cd", str(0.01 * (1 + 6e-7 * i)))
    assert lenta.n == 6000 and not lenta.convergio()
    # Cl sube 0.5 % por ventana: no ha terminado
    subiendo = J._Vigilancia()
    for i in range(3000):
        subiendo.agrega("Cl", str(0.9 + 1e-5 * i))
        subiendo.agrega("Cd", "0.01")
    assert not subiendo.convergio()
    # Oscilando no termina aunque la media no cambie
    oscila = J._Vigilancia()
    for i in range(6000):
        oscila.agrega("Cl", str(0.9 + 0.01 * (-1) ** i))
        oscila.agrega("Cd", "0.01")
    assert not oscila.convergio()


def test_watch_waits_longer_on_a_slow_mesh():
    import math
    def termina_en(tau):
        v = J._Vigilancia()
        for i in range(1, 100001):
            v.agrega("Cd", str(0.012 + 0.002 * math.exp(-i / tau)))
            v.agrega("Cl", str(1.06 - 0.03 * math.exp(-i / tau)))
            if i % 1000 == 0 and v.convergio():
                return i
        return None
    rapida, lenta = termina_en(1500), termina_en(7000)
    assert rapida < 15000
    # Proporcional al tiempo de relajacion, y parando cuando ya casi no falta nada.
    assert lenta > 30000 and 0.002 * math.exp(-lenta / 7000) / 0.012 < 0.002


def test_watch_detects_divergence_only_after_enough_iterations():
    v = J._Vigilancia()
    for i in range(600):
        v.agrega("Cl", "900")
        v.agrega("Cd", "-1")
    assert not v.divergio()
    for i in range(600):
        v.agrega("Cl", "900")
        v.agrega("Cd", "-1")
    assert v.divergio()
    bien = J._Vigilancia()
    for i in range(1200):
        bien.agrega("Cl", "0.9")
        bien.agrega("Cd", "0.01")
    assert not bien.divergio()
    # El arranque impulsivo de un transitorio no es divergencia: medido a 18 grados, solo
    # 6 de sus primeros pasos pasan de |Cl| = 5. Cl = -146 si lo es.
    impulso = J._Vigilancia()
    for i in range(6):
        impulso.agrega("Cl", "29")
        impulso.agrega("Cd", "8")
    for i in range(1200):
        impulso.agrega("Cl", "0.7")
        impulso.agrega("Cd", "0.15")
    assert not impulso.divergio()
    for i in range(500):
        impulso.agrega("Cl", "-146")
    assert impulso.divergio()
    # Un arranque lento puede pasar por Cd < 0 sin estar divergiendo.
    lento = J._Vigilancia()
    for i in range(1400):
        lento.agrega("Cl", "0.8")
        lento.agrega("Cd", "-0.001")
    assert not lento.divergio()


@pytest.fixture
def corrida_falsa(monkeypatch):
    """Sustituye el calculo: registra donde corrio cada trabajo y cuantos a la vez."""
    registro = {"por_maquina": {}, "maximo": {}, "activos": {}, "candado": threading.Lock()}
    soltar = threading.Event()

    def falso(job, ev, should_detach=lambda: False, registrar=lambda _: None, poll_s=0,
              stop_on_divergence=True):
        with registro["candado"]:
            registro["por_maquina"].setdefault(job.host, []).append(job.params["aoa"])
            registro["activos"][job.host] = registro["activos"].get(job.host, 0) + 1
            registro["maximo"][job.host] = max(registro["maximo"].get(job.host, 0),
                                               registro["activos"][job.host])
        job.state = CORRIENDO
        ev.state(job)
        soltar.wait(5)
        with registro["candado"]:
            registro["activos"][job.host] -= 1
        job.state = TERMINADO
        ev.state(job)

    monkeypatch.setattr(J, "run_job", falso)
    registro["soltar"] = soltar
    return registro


def test_dispatcher_spreads_jobs_and_respects_each_machine(corrida_falsa):
    d = Dispatcher(poll_s=0)
    d.set_machines([Machine("a@h", 10, 1), Machine("b@h", 8, 2)])
    trabajos = [new_job(case_params(aoa=float(a))) for a in range(5)]
    for t in trabajos:
        d.submit(t)
    time.sleep(0.2)
    assert sorted(len(v) for v in corrida_falsa["por_maquina"].values()) == [1, 2]
    assert sum(1 for t in trabajos if t.state == PENDIENTE) == 2
    corrida_falsa["soltar"].set()
    assert d.wait(5)
    assert all(t.state == TERMINADO for t in trabajos)
    assert sorted(a for v in corrida_falsa["por_maquina"].values() for a in v) == [0, 1, 2, 3, 4]
    assert corrida_falsa["maximo"]["a@h"] == 1 and corrida_falsa["maximo"]["b@h"] <= 2
    por_maquina = {t.host: t.nproc for t in trabajos}
    assert por_maquina == {"a@h": 10, "b@h": 8}


def test_unmarked_machine_only_runs_jobs_sent_to_it(corrida_falsa):
    d = Dispatcher(poll_s=0)
    d.set_machines([Machine("sin@marcar", 4, 1, reparto=False), Machine("marcada@h", 4, 1)])
    libre, fijo = new_job(case_params(aoa=1.0)), new_job(case_params(aoa=2.0), "sin@marcar", 4)
    d.submit(libre)
    d.submit(fijo)
    corrida_falsa["soltar"].set()
    assert d.wait(5)
    assert corrida_falsa["por_maquina"] == {"marcada@h": [1.0], "sin@marcar": [2.0]}


def test_job_with_a_fixed_machine_waits_for_it(corrida_falsa):
    d = Dispatcher(poll_s=0)
    d.set_machines([Machine("a@h", 4, 1), Machine("b@h", 4, 1)])
    uno, dos = new_job(case_params(aoa=1.0), "a@h", 4), new_job(case_params(aoa=2.0), "a@h", 4)
    d.submit(uno)
    d.submit(dos)
    time.sleep(0.2)
    assert uno.state == CORRIENDO and dos.state == PENDIENTE
    corrida_falsa["soltar"].set()
    assert d.wait(5)
    assert corrida_falsa["por_maquina"] == {"a@h": [1.0, 2.0]}


def test_stopping_a_queued_job_never_launches_it(corrida_falsa):
    d = Dispatcher(poll_s=0)
    d.set_machines([Machine("a@h", 4, 1)])
    uno, dos = new_job(case_params(aoa=1.0)), new_job(case_params(aoa=2.0))
    d.submit(uno)
    d.submit(dos)
    time.sleep(0.1)
    d.stop(dos.id)
    assert dos.state == DETENIDO
    corrida_falsa["soltar"].set()
    assert d.wait(5)
    assert corrida_falsa["por_maquina"] == {"a@h": [1.0]}


def test_failed_mesh_fails_the_job_and_frees_the_machine(monkeypatch):
    def malla_rota(params, log=lambda _: None):
        raise JobError("La malla no se pudo generar")
    monkeypatch.setattr(J, "ensure_mesh", malla_rota)
    d = Dispatcher(poll_s=0)
    d.set_machines([Machine("a@h", 4, 1)])
    uno = new_job(case_params())
    d.submit(uno)
    assert d.wait(5)
    assert uno.state == FALLIDO and "malla" in uno.error


def test_unexpected_error_also_fails_the_job(monkeypatch):
    def malla_rara(params, log=lambda _: None):
        raise ValueError("La rejilla tiene 3 celdas invertidas")
    monkeypatch.setattr(J, "ensure_mesh", malla_rara)
    d = Dispatcher(poll_s=0)
    d.set_machines([Machine("a@h", 4, 1)])
    uno = new_job(case_params())
    d.submit(uno)
    assert d.wait(5)
    assert uno.state == FALLIDO and "invertidas" in uno.error
    assert next(j for j in load_jobs() if j.id == uno.id).state == FALLIDO


def test_local_job_refuses_without_docker_image(monkeypatch, tmp_path):
    from core import local_runner as L
    from core.remote_runner import RemoteError
    monkeypatch.setattr(L, "probar_docker", lambda: {"docker": False, "imagen": False, "mensaje": "sin docker"})
    with pytest.raises(RemoteError, match="sin docker"):
        L.LocalJob(str(tmp_path), "x").lanzar()


def test_local_job_runs_the_same_script_natively(tmp_path):
    """Modo nativo sin OpenFOAM: el trabajo arranca, verifica el paquete y lo cuenta."""
    from core.defaults import case_params as cp
    from core.local_runner import LocalJob
    from core.solve_script import configure_case
    params = cp(reynolds=6e6)
    transient = configure_case(str(tmp_path), params)
    malla = tmp_path / "m.msh"
    malla.write_text("malla")
    job = LocalJob(str(tmp_path), "x", nativo=True)
    job.subir(str(tmp_path), str(malla), 2, transient, params)
    malla.unlink()
    job.lanzar()
    for _ in range(100):
        est = job.estado()
        if est.get("state") != "running":
            break
        time.sleep(0.1)
    assert est["state"] == "failed"
    assert est["ficha_sha256"] == job.ficha_sha256


def test_without_network_a_job_waits_instead_of_failing(monkeypatch):
    """Un corte de red dejo nueve paquetes de la cola como fallidos en pocos minutos."""
    from core.remote_runner import RemoteError

    intentos = []

    def subir():
        intentos.append(1)
        if len(intentos) < 4:
            raise RemoteError("No se pudo crear el trabajo: ssh: connect to host h port 22: Operation timed out")

    avisos = []
    assert J.insiste(subir, avisos.append, lambda: False, poll_s=0)
    assert len(intentos) == 4 and len(avisos) == 1 and "reintenta" in avisos[0]

    # Sin permiso no sirve esperar
    def sin_permiso():
        raise RemoteError("No se pudo crear el trabajo: Permission denied (publickey)")

    with pytest.raises(RemoteError, match="Permission denied"):
        J.insiste(sin_permiso, avisos.append, lambda: False, poll_s=0)

    # Cerrar la ventana mientras espera no lo da por fallido
    assert J.insiste(subir, avisos.append, lambda: True, poll_s=0) is False


def test_retrying_the_upload_does_not_trip_on_its_own_folder(monkeypatch, tmp_path):
    from core import remote_runner as R

    class Salida:
        def __init__(self, rc, err=""):
            self.returncode, self.stderr, self.stdout = rc, err, ""

    respuestas = [Salida(255, "Connection closed"), Salida(1, "mkdir: cannot create: File exists")]
    monkeypatch.setattr(R, "_ssh", lambda *a, **k: respuestas.pop(0))
    trabajo = R.RemoteJob("u@h", job_dir="jobs/x")
    with pytest.raises(R.RemoteError, match="Connection closed"):
        trabajo.subir(str(tmp_path), "/no/existe", 2, False, {})
    # El segundo intento pasa de crear la carpeta y llega hasta copiar la malla
    with pytest.raises(FileNotFoundError):
        trabajo.subir(str(tmp_path), "/no/existe", 2, False, {})
    # Una carpeta que ya existia antes de este trabajo no es suya
    respuestas.append(Salida(1, "mkdir: cannot create: File exists"))
    with pytest.raises(R.RemoteError, match="File exists"):
        R.RemoteJob("u@h", job_dir="jobs/y").subir(str(tmp_path), "/no/existe", 2, False, {})
    # Salvo la que lleva el id del trabajo, tras reiniciar la Mac a media subida
    respuestas.append(Salida(1, "mkdir: cannot create: File exists"))
    job = new_job(case_params(), "u@h", 2)
    with pytest.raises(FileNotFoundError):
        J.make_runner(job).subir(str(tmp_path), "/no/existe", 2, False, {})


@pytest.mark.parametrize("mensaje", [
    "rsync error: timeout in data send/receive (code 30) at io.c(197)",
    "rsync: connection unexpectedly closed (0 bytes received so far) [receiver]",
    "Timeout, server u@h not responding.",
    "ssh: connect to host h port 22: Operation timed out",
    "mux_client_request_session: read from master failed: Broken pipe",
    "rsync error: error in rsync protocol data stream (code 12)",
])
def test_transport_messages_are_cuts(mensaje):
    from core.remote_runner import RemoteError
    assert J.es_corte(RemoteError(mensaje))


@pytest.mark.parametrize("mensaje", [
    "No se pudo crear el trabajo: Permission denied (publickey)",
    "rsync: write failed: No space left on device (28)",
    "No se pudo crear el trabajo: mkdir: cannot create: File exists",
])
def test_real_errors_are_not_cuts(mensaje):
    from core.remote_runner import RemoteError
    assert not J.es_corte(RemoteError(mensaje))


def test_hours_without_connection_let_go_of_the_job_but_do_not_fail_it(monkeypatch):
    from core.remote_runner import RemoteError

    class Cortado(_RunnerFalso):
        def estado(self):
            raise RemoteError("ssh: connect to host h port 22: Operation timed out")

    monkeypatch.setattr(J, "MAX_FALLOS", 3)
    avisos = []
    assert follow(Cortado([{}]), lambda e: None, lambda p: None, lambda: False, poll_s=0,
                  on_notice=avisos.append) is None
    assert "se retoma" in avisos[-1]


def test_a_job_that_never_starts_is_not_followed_forever(monkeypatch):
    from core.remote_runner import RemoteError
    monkeypatch.setattr(J, "ARRANQUE_MAX", -1.0)
    with pytest.raises(RemoteError, match="no arrancó"):
        follow(_RunnerFalso([{"state": "running", "step": "inicio"}]), lambda e: None, lambda p: None,
               lambda: False, poll_s=0)


def test_stopping_a_job_that_waits_for_the_network_never_sends_it(monkeypatch):
    from core.remote_runner import RemoteError
    intentos = []

    class SinRed:
        job_dir = "openblade_jobs/x"

        def subir(self, *a):
            intentos.append(1)
            raise RemoteError("ssh: connect to host h port 22: Operation timed out")

    monkeypatch.setattr(J, "make_runner", lambda job: SinRed())
    monkeypatch.setattr(J, "ensure_mesh", lambda *a: "/no/importa")
    monkeypatch.setattr("core.solve_script.configure_case", lambda *a: False)
    d = Dispatcher(poll_s=0.01)
    d.set_machines([Machine("a@h", 2, 1)])
    trabajo = new_job(case_params(), "a@h", 2)
    d.submit(trabajo)
    while not intentos:
        time.sleep(0.01)
    d.stop(trabajo.id)
    assert d.wait(5)
    assert trabajo.state == DETENIDO and not trabajo.remote_dir


def test_a_finished_job_does_not_wait_for_a_log_that_cannot_arrive():
    import subprocess

    class Lento(_RunnerFalso):
        def leer_log(self):
            raise subprocess.TimeoutExpired("ssh", 60)

    est = follow(Lento([{"state": "done", "rc": 0}]), lambda e: None, lambda p: None, lambda: False, poll_s=0)
    assert est["state"] == "done"


def test_a_failed_cleanup_does_not_fail_a_finished_job(monkeypatch):
    import subprocess

    class Trabajo(_RunnerFalso):
        job_dir = "openblade_jobs/x"
        offset = 0

        def subir(self, *a):
            pass

        def lanzar(self):
            pass

        def descargar(self, carpeta):
            pass

        def limpiar(self):
            raise subprocess.TimeoutExpired("ssh", 120)

    monkeypatch.setattr(J, "make_runner", lambda job: Trabajo([{"state": "done", "rc": 0, "step": "fin"}]))
    monkeypatch.setattr(J, "ensure_mesh", lambda *a: "/no/importa")
    monkeypatch.setattr("core.solve_script.configure_case", lambda *a: False)
    monkeypatch.setattr("core.verdict.analyze_case", lambda *a: {"verdict": {"state": "CONVERGIDO"}})
    trabajo = new_job(case_params(), "a@h", 2)
    avisos = []

    class Registro(Events):
        def log(self, job, texto):
            avisos.append(texto)

    J.run_job(trabajo, Registro(), poll_s=0)
    assert trabajo.state == TERMINADO and trabajo.analysis["verdict"]["state"] == "CONVERGIDO"
    assert any("temporales" in a for a in avisos)


def test_a_job_waits_for_the_one_it_starts_from(corrida_falsa, monkeypatch):
    monkeypatch.setattr(J, "has_start_field", lambda job: True)
    d = Dispatcher(poll_s=0)
    d.set_machines([Machine("a@h", 4, 2)])
    grueso, fino = new_job(case_params(aoa=1.0), "a@h", 4), new_job(case_params(aoa=2.0), "a@h", 4)
    fino.despues = grueso.id
    d.submit(grueso)
    d.submit(fino)
    time.sleep(0.2)
    # Hay sitio para los dos, pero el fino espera
    assert grueso.state == CORRIENDO and fino.state == PENDIENTE
    corrida_falsa["soltar"].set()
    assert d.wait(5)
    assert fino.params["campo_inicial"] == grueso.case_dir
    # Si el anterior no deja un campo util, arranca en frio
    monkeypatch.setattr(J, "has_start_field", lambda job: False)
    otro = new_job(case_params(aoa=3.0), "a@h", 4)
    otro.despues = grueso.id
    d.submit(otro)
    assert d.wait(5)
    assert "campo_inicial" not in otro.params
    # Un anterior ya terminado en otra sesion tambien cuenta
    monkeypatch.setattr(J, "has_start_field", lambda job: True)
    nuevo = Dispatcher(poll_s=0)
    nuevo.set_machines([Machine("a@h", 4, 1)])
    nuevo.register(grueso)
    siguiente = new_job(case_params(aoa=4.0), "a@h", 4)
    siguiente.despues = grueso.id
    nuevo.submit(siguiente)
    assert nuevo.wait(5)
    assert siguiente.params["campo_inicial"] == grueso.case_dir


def test_queued_jobs_go_to_the_least_busy_machine(corrida_falsa):
    d = Dispatcher(poll_s=0)
    d.set_machines([Machine("a@h", 8, 2), Machine("b@h", 8, 2)])
    for a in (1.0, 2.0):
        d.submit(new_job(case_params(aoa=a)))
    time.sleep(0.3)
    assert sorted(len(v) for v in corrida_falsa["por_maquina"].values()) == [1, 1]
    corrida_falsa["soltar"].set()
    assert d.wait(5)
