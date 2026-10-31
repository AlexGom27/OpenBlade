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
