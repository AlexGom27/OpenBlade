"""El resumen de la polar no puede quedarse mudo en un punto que no converge."""

import argparse
import os
import sys

import pytest

from core import cli
from core.defaults import case_params
from core.jobs import new_job


def _polar_con_no_convergido(monkeypatch):
    """Una fila NO CONVERGIDO con cl y cd en su analisis, como los trabajos de hoy."""
    def falso_run_polar(*a, **k):
        j = new_job(case_params(aoa=0.0), "u@h", 8)
        return {"filas": [{
            "aoa": 0.0, "veredicto": "NO CONVERGIDO", "oscila": False, "transitorio": False,
            # Como en el resumen real: la fila no lleva numeros (no se dan sin banda),
            # aunque el analisis del trabajo si tenga cl y cd.
            "cl": None, "cd": None, "banda_cl": None, "banda_cd": None,
            "razon": "La media de Cd aún cambia 0.39 % entre tramos (máximo 0.3 %)",
            "trabajo": j.id}], "trabajos": {}}

    monkeypatch.setattr("core.campaign.run_polar", falso_run_polar)
    monkeypatch.setattr("core.campaign.write_polar_report", lambda r, s: "polar.png")


def test_a_point_without_numbers_says_why(monkeypatch, capsys):
    """Antes salia «α= 0.00  NO CONVERGIDO» y nada mas, aunque hubiera motivo.

    El analisis tenia cl y cd, pero el resumen los omite a proposito (darlos sin
    banda los haria pasar por buenos). Lo que no puede es quedarse callado.
    """
    _polar_con_no_convergido(monkeypatch)
    cli.cmd_polar(argparse.Namespace(maquinas="u@h:8:1", angulos="0", gci="", urans=False,
                                     continuar=False, ajustes=[], salida="x"))
    salida = capsys.readouterr().out
    assert "NO CONVERGIDO" in salida
    assert "aún cambia 0.39 %" in salida, salida


def test_a_point_with_numbers_still_prints_them(monkeypatch, capsys):
    """Y uno que si converge no cambia: numeros y banda."""
    def falso_run_polar(*a, **k):
        j = new_job(case_params(aoa=8.0), "u@h", 8)
        return {"filas": [{"aoa": 8.0, "veredicto": "CONVERGIDO", "oscila": False,
                           "transitorio": False, "cl": 0.8614, "cd": 0.01028,
                           "banda_cl": 0.002, "banda_cd": 0.0001,
                           "razon": "Cd varía 0.4 %", "trabajo": j.id}], "trabajos": {}}

    monkeypatch.setattr("core.campaign.run_polar", falso_run_polar)
    monkeypatch.setattr("core.campaign.write_polar_report", lambda r, s: "polar.png")
    cli.cmd_polar(argparse.Namespace(maquinas="u@h:8:1", angulos="8", gci="", urans=False,
                                     continuar=False, ajustes=[], salida="x"))
    salida = capsys.readouterr().out
    assert "Cl 0.8614 ± 0.0020" in salida, salida
