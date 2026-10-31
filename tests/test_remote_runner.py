"""Pruebas de la ejecucion en servidor que no necesitan red."""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.remote_runner import (LogParser, RemoteError, RemoteJob,
                                configurar_acceso, validar_host)


def test_host_rejects_ssh_options():
    assert validar_host(" user@10.0.0.1 ") == "user@10.0.0.1"
    for malo in ("", "-oProxyCommand=x", "a b", "a;rm"):
        with pytest.raises(RemoteError):
            validar_host(malo)


def test_job_dir_stays_under_home():
    with pytest.raises(RemoteError):
        RemoteJob("u@h", job_dir="../fuera")
    assert "0012_a4.5_x_" in RemoteJob("u@h", etiqueta="0012_a4.5/x").job_dir


def test_two_jobs_launched_in_the_same_second_get_different_folders():
    """Compartian carpeta: un lanzamiento se perdia y ambos terminaban con rc=0."""
    assert len({RemoteJob("u@h", etiqueta="x").job_dir for _ in range(50)}) == 50


def test_parser_handles_openfoam12_output_and_split_lines():
    p = LogParser()
    ev = p.feed("Time = 12s\n\nGAMG:  Solving for p, Initial residual = 0.01, Fin")
    assert ev == []
    ev = p.feed("al residual = 1e-3, No Iterations 2\n"
                "    Cm    = 0.05\n    Cd    = 0.0123\n    Cl    = 0.8\n"
                "    Cl(f) = 0.4\n")
    assert ev == [("residual", "p", 0.01, 12.0), ("fuerza", "Cm", "0.05"),
                  ("fuerza", "Cd", "0.0123"), ("fuerza", "Cl", "0.8")]


def _ssh_falso(tmp_path, monkeypatch):
    """ssh que pide la contrasena por askpass y guarda la clave que recibe."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "ssh"
    script.write_text(
        '#!/bin/sh\n'
        'echo "$*" >> "$HOME/argv"\n'
        'case "$*" in *BatchMode=yes*) [ -s "$HOME/recibida" ]; exit $? ;; esac\n'
        '[ "$("$SSH_ASKPASS")" = "secreta 1" ] || { echo "Permission denied" >&2; exit 255; }\n'
        'cat > "$HOME/recibida"\n')
    script.chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_configurar_acceso_creates_key_and_hides_password(tmp_path, monkeypatch):
    _ssh_falso(tmp_path, monkeypatch)
    configurar_acceso("u@h", "secreta 1")
    pub = (tmp_path / ".ssh" / "id_ed25519.pub").read_text().strip()
    assert (tmp_path / "recibida").read_text().strip() == pub
    assert "secreta" not in (tmp_path / "argv").read_text()


def test_configurar_acceso_reports_wrong_password(tmp_path, monkeypatch):
    _ssh_falso(tmp_path, monkeypatch)
    with pytest.raises(RemoteError, match="incorrectos"):
        configurar_acceso("u@h", "otra")
