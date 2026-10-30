"""Pruebas de la ejecucion en servidor que no necesitan red."""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.remote_runner import (LogParser, RemoteError, RemoteJob,
                                coeficientes_finales, validar_host)


def test_host_rejects_ssh_options():
    assert validar_host(" user@10.0.0.1 ") == "user@10.0.0.1"
    for malo in ("", "-oProxyCommand=x", "a b", "a;rm"):
        with pytest.raises(RemoteError):
            validar_host(malo)


def test_job_dir_stays_under_home():
    with pytest.raises(RemoteError):
        RemoteJob("u@h", job_dir="../fuera")
    assert RemoteJob("u@h", etiqueta="0012_a4.5/x").job_dir.endswith("0012_a4.5_x")


def test_parser_handles_openfoam12_output_and_split_lines():
    p = LogParser()
    ev = p.feed("Time = 12s\n\nGAMG:  Solving for p, Initial residual = 0.01, Fin")
    assert ev == []
    ev = p.feed("al residual = 1e-3, No Iterations 2\n"
                "    Cm    = 0.05\n    Cd    = 0.0123\n    Cl    = 0.8\n"
                "    Cl(f) = 0.4\n")
    assert ev == [("residual", "p", 0.01, 12.0), ("fuerza", "Cm", "0.05"),
                  ("fuerza", "Cd", "0.0123"), ("fuerza", "Cl", "0.8")]


def test_final_coefficients_use_the_header(tmp_path):
    d = tmp_path / "postProcessing" / "forceCoeffs" / "0"
    d.mkdir(parents=True)
    (d / "forceCoeffs.dat").write_text(
        "# Force coefficients\n# Time Cm Cd Cl Cl(f) Cl(r)\n"
        "1 0.1 0.2 0.3 0.4 0.5\n2 0.05 0.012 0.8 0.5 0.3\n")
    assert coeficientes_finales(str(tmp_path)) == (0.8, 0.012, 0.05)
