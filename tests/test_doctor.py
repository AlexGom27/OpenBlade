"""El diagnostico que no lanza nada."""

import argparse
from types import SimpleNamespace

from core import cli


def _preparar(monkeypatch, servidor):
    import core.local_runner as L
    import core.remote_runner as R
    monkeypatch.setattr(L, "probar_docker", lambda: {"mensaje": "Abre Docker Desktop: no está corriendo."})
    monkeypatch.setattr(R, "probar_servidor", servidor)
    monkeypatch.setattr(R, "_ssh", lambda *a, **k: SimpleNamespace(stdout="/dev/sda 1 2 400000000 1% /home\n"))
    monkeypatch.setattr(cli, "_versiones_distintas", lambda: [])


def test_all_ready(monkeypatch, capsys):
    _preparar(monkeypatch, lambda h: {"rsync": True, "python3": True, "openfoam": "/opt/openfoam12/etc/bashrc",
                                      "nucleos": 20, "carga": 3.0})
    assert cli.cmd_doctor(argparse.Namespace(hosts="u@a")) == 0
    salida = capsys.readouterr().out
    assert "Todo listo" in salida and "openfoam12" in salida and "400 GB" in salida


def test_a_machine_that_does_not_answer_is_a_problem(monkeypatch, capsys):
    from core.remote_runner import RemoteError

    def sin_red(host):
        raise RemoteError(f"{host} no responde")

    _preparar(monkeypatch, sin_red)
    assert cli.cmd_doctor(argparse.Namespace(hosts="u@a")) == 1
    assert "No responde" in capsys.readouterr().out


def test_a_server_without_openfoam_is_a_problem(monkeypatch, capsys):
    _preparar(monkeypatch, lambda h: {"rsync": True, "python3": True, "openfoam": "", "nucleos": 4, "carga": 0.0})
    assert cli.cmd_doctor(argparse.Namespace(hosts="u@a")) == 1
    assert "no se encontró" in capsys.readouterr().out


def test_versions_are_compared_with_requirements():
    distintos = cli._versiones_distintas()
    assert isinstance(distintos, list)
