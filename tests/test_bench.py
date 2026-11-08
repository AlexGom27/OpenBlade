"""El banco compara con los datos publicados y dice lo que cumple y lo que no."""

import json

import numpy as np
import pytest

from core.bench import (BenchCase, SA, SST, TMR, _domain_test, case_parameters, default_cases, evaluate, ladson,
                        summarize, surface_comparison, write_report, _zona, REFS)
from core.defaults import case_params
from core.jobs import TERMINADO, new_job


def test_published_values_are_in_the_table():
    assert TMR[SST][10.0]["CFL3D"] == (1.0778, 0.01236)
    assert TMR[SA][15.0]["CFL3D"] == (1.5461, 0.02124)


def test_ladson_is_interpolated_at_the_angle():
    cl, cd = ladson(10.12)
    assert (cl, cd) == pytest.approx((1.0707, 0.01201))
    assert ladson(0.0)[1] == pytest.approx(0.00809, abs=1e-5)


def test_ladson_uses_only_the_80_grit_series_and_not_the_180_grit_one():
    # 13.08° y 14.22° del tramo de 80 granos; con la serie de 180 mezclada, 14° daba Cd 0.01520
    cl, cd = ladson(14.0)
    assert cl == pytest.approx(1.3455 + (1.4365 - 1.3455) * (14.0 - 13.08) / (14.22 - 13.08))
    assert cd == pytest.approx(0.01503 + (0.01625 - 0.01503) * (14.0 - 13.08) / (14.22 - 13.08))


def test_a_zone_is_matched_by_its_whole_title_not_by_a_piece_of_it():
    # "80 grit" esta dentro de "180 grit": la zona se pide y se compara entera.
    d = _zona(f"{REFS}/ladson_clcd.dat", "80 grit")
    assert d.shape[0] == 17
    assert d[:, 0].max() == pytest.approx(19.08)     # ultima fila de 80 granos
    assert 18.21 not in d[:, 0]                      # 18.21 es de 180 granos
    assert _zona(f"{REFS}/ladson_clcd.dat", "180 grit").shape[0] == 18


def test_a_title_that_is_not_there_says_so_instead_of_returning_nothing():
    with pytest.raises(ValueError, match="80 grits"):
        _zona(f"{REFS}/ladson_clcd.dat", "80 grits")


def test_reference_files_have_every_angle():
    for modelo in ("sst", "sa"):
        for a in (0, 10, 15):
            assert _zona(f"{REFS}/tmr_n0012cp_cfl3d_{modelo}.dat", f"alpha={a}").shape[0] > 100
            assert _zona(f"{REFS}/tmr_n0012cf_cfl3d_{modelo}.dat", f"alpha={a}, upper surface").shape[0] > 100


def test_default_bench_covers_both_models_and_the_domain_test():
    casos = default_cases()
    assert {c.aoa for c in casos} == {0.0, 10.0, 15.0}
    assert {c.turbulencia for c in casos} == {SST, SA}
    assert sorted(c.radio for c in casos if "dominio" in c.etiqueta) == [40.0, 500.0]
    p = case_parameters(casos[1])
    assert (p["reynolds"], p["aoa"], p["mesher"], p["grid_level"]) == (6e6, 10.0, "cgrid", 2)


def _trabajo(c, estado="CONVERGIDO", cl=1.08, cd=0.0125):
    j = new_job(case_parameters(c), "u@h", 2)
    j.state = TERMINADO
    j.analysis = {"verdict": {"state": estado, "reason": "r", "cl": cl, "cl_amp": 0.0, "cd": cd, "cd_amp": 0.0,
                              "cm": 0.0, "n_rows": 9000}, "yplus": {"mean": 0.7}}
    return j


def test_case_inside_the_tolerances_passes_and_outside_fails():
    c = BenchCase("a", 10.0)
    bien = evaluate(c, _trabajo(c))
    nombres = {x["nombre"]: x for x in bien["comprobaciones"]}
    assert nombres["Cl frente a TMR"]["cumple"] and nombres["Cd frente a TMR"]["cumple"]
    mal = evaluate(c, _trabajo(c, cl=1.2))
    assert not {x["nombre"]: x for x in mal["comprobaciones"]}["Cl frente a TMR"]["cumple"]


def test_diverged_case_has_no_comparison():
    c = BenchCase("a", 10.0)
    f = evaluate(c, _trabajo(c, estado="DIVERGIDO", cl=20.0))
    assert f["comprobaciones"] == [] and f["veredicto"] == "DIVERGIDO"


def test_zero_lift_error_is_absolute():
    c = BenchCase("a", 0.0)
    f = evaluate(c, _trabajo(c, cl=0.0005, cd=0.0081))
    assert {x["nombre"]: x for x in f["comprobaciones"]}["Cl frente a TMR"]["cumple"]


def test_domain_test_compares_each_radius_with_the_default_case():
    filas = [{"caso": {"etiqueta": "banco_dominio_R40", "radio": 40.0}, "cl": 1.06, "cd": 0.0120},
             {"caso": {"etiqueta": "banco_sst_a10", "radio": 200.0}, "cl": 1.08, "cd": 0.0121},
             {"caso": {"etiqueta": "banco_dominio_R500", "radio": 500.0}, "cl": 1.081, "cd": 0.0120}]
    d = _domain_test(filas)
    assert [x["cumple"] for x in d] == [False, True, True, True]


def test_report_is_written_with_what_passed_and_what_did_not(tmp_path):
    casos = [BenchCase("a", 10.0), BenchCase("b", 15.0)]
    trabajos = [_trabajo(casos[0]), _trabajo(casos[1], estado="NO CONVERGIDO", cl=1.5, cd=0.022)]
    r = summarize(casos, trabajos)
    assert r["sin_converger"] == ["b"]
    assert 0 < r["cumplidas"] <= r["total"]
    ruta = write_report(r, str(tmp_path))
    assert (tmp_path / "banco_validacion.pdf").stat().st_size > 1000
    assert json.load(open(tmp_path / "banco.json"))["total"] == r["total"]
