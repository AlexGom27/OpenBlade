"""Polar con incertidumbre y estudio de malla, a partir de trabajos ya terminados."""

import csv

import pytest

from core.campaign import (grid_study_cases, grid_study_result, grid_study_text, polar_table, usable,
                           write_polar_csv, write_polar_report)
from core.defaults import case_params
from core.jobs import TERMINADO, new_job


def trabajo(aoa=4.0, nivel=2, estado="CONVERGIDO", cl=0.43, cd=0.0084, transitorio=False):
    q = case_params(aoa=aoa, grid_level=nivel, reynolds=6e6)
    if transitorio:
        q["regime"] = "Transitorio (pimpleFoam)"
    j = new_job(q, "u@h", 2)
    j.state = TERMINADO
    j.analysis = {"verdict": {"state": estado, "reason": "r", "cl": cl, "cl_amp": 0.001, "cd": cd, "cd_amp": 1e-5,
                              "cm": 0.001}, "yplus": {"mean": 0.7}}
    return j


def test_grid_study_has_three_nested_levels_of_the_same_case():
    casos = grid_study_cases(case_params(aoa=4.0))
    assert [c["grid_level"] for c in casos] == [1, 2, 3]
    assert all(c["mesher"] == "cgrid" and c["aoa"] == 4.0 for c in casos)


def test_gci_needs_all_levels_converged():
    malos = [trabajo(nivel=1, estado="NO CONVERGIDO"), trabajo(nivel=2), trabajo(nivel=3)]
    r = grid_study_result(malos)
    assert r["sin_converger"] == [1] and "cl" not in r
    assert "no convergieron" in grid_study_text(r)


def test_gci_comes_from_the_three_levels_in_any_order():
    t = [trabajo(nivel=3, cl=1.01, cd=0.0100), trabajo(nivel=1, cl=1.16, cd=0.0130), trabajo(nivel=2, cl=1.04, cd=0.0106)]
    r = grid_study_result(t)
    assert r["cl"]["orden"] == pytest.approx(2.0)
    assert r["cl"]["extrapolado"] == pytest.approx(1.0)
    assert "GCI" in grid_study_text(r)


def test_polar_applies_interpolated_band_and_hides_what_did_not_converge():
    estudio = [{"aoa": 0.0, "cl": {"gci_media": 0.01}, "cd": {"gci_media": 0.02}},
               {"aoa": 10.0, "cl": {"gci_media": 0.03}, "cd": {"gci_media": 0.06}}]
    t = [trabajo(aoa=5.0, cl=0.5, cd=0.01), trabajo(aoa=18.0, estado="NO CONVERGIDO", cl=1.2, cd=0.1),
         trabajo(aoa=19.0, estado="DIVERGIDO", cl=9.0)]
    filas = polar_table(t, estudio)
    assert filas[0]["banda_cl"] == pytest.approx(0.02 * 0.5)
    assert filas[0]["banda_cd"] == pytest.approx(0.04 * 0.01)
    assert filas[1]["cl"] is None and filas[1]["veredicto"] == "NO CONVERGIDO"
    assert filas[2]["cl"] is None
    assert not usable(t[1])


def test_results_are_saved(tmp_path):
    filas = polar_table([trabajo(aoa=0.0, cl=0.0), trabajo(aoa=4.0)])
    write_polar_csv(filas, str(tmp_path / "p.csv"))
    leido = list(csv.DictReader(open(tmp_path / "p.csv")))
    assert [float(f["aoa"]) for f in leido] == [0.0, 4.0]
    ruta = write_polar_report({"base": {"naca": "0012", "reynolds": 6e6}, "filas": filas, "estudios": []},
                              str(tmp_path / "salida"))
    assert (tmp_path / "salida" / "polar.csv").exists() and (tmp_path / "salida" / "polar.json").exists()
    assert ruta.endswith("polar.png")


def _nivel_que_oscila(cd_amp):
    j = trabajo(nivel=1, estado="NO CONVERGIDO", cl=1.48, cd=0.0186)
    j.analysis["verdict"].update(oscila=True, cd_amp=cd_amp)
    return j


def test_a_level_that_barely_oscillates_counts_for_the_grid_study():
    trabajos = [_nivel_que_oscila(0.0002), trabajo(nivel=2, cl=1.50, cd=0.0199), trabajo(nivel=3, cl=1.505, cd=0.0205)]
    r = grid_study_result(trabajos)
    assert r["sin_converger"] == [1] and r["oscilan"] == [1]
    assert "motivo" not in r and r["cd"]["orden"] is not None
    assert "oscilan" in grid_study_text(r)


def test_a_level_that_oscillates_as_much_as_the_jump_does_not():
    trabajos = [_nivel_que_oscila(0.001), trabajo(nivel=2, cl=1.50, cd=0.0199), trabajo(nivel=3, cl=1.505, cd=0.0205)]
    r = grid_study_result(trabajos)
    assert r["oscilan"] == [] and "no convergieron" in r["motivo"]
