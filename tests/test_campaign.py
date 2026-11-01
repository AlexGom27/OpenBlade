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
    assert [c["max_iters"] for c in grid_study_cases(case_params(max_iters=20000))] == [10000, 20000, 40000]


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
    # Fuera de los angulos con estudio de malla no se inventa una banda
    fuera = polar_table([trabajo(aoa=12.0, cl=1.2, cd=0.015)], estudio)
    assert fuera[0]["cl"] == 1.2 and fuera[0]["banda_cl"] is None and fuera[0]["banda_cd"] is None


def test_a_point_that_barely_oscillates_gives_its_mean_marked_and_without_band():
    estudio = [{"aoa": 0.0, "cl": {"gci_media": 0.01}, "cd": {"gci_media": 0.02}},
               {"aoa": 20.0, "cl": {"gci_media": 0.03}, "cd": {"gci_media": 0.06}}]
    oscila = trabajo(aoa=16.0, estado="NO CONVERGIDO", cl=1.558, cd=0.0233)
    oscila.analysis["verdict"]["oscila"] = True
    fila = polar_table([oscila], estudio)[0]
    assert fila["cl"] == 1.558 and fila["oscila"] and fila["banda_cl"] is None
    assert not usable(oscila)
    # Con una amplitud grande, esa media no es un resultado
    oscila.analysis["verdict"]["cl_amp"] = 0.4
    fila = polar_table([oscila], estudio)[0]
    assert fila["cl"] is None and not fila["oscila"]


def test_results_are_saved(tmp_path):
    filas = polar_table([trabajo(aoa=0.0, cl=0.0), trabajo(aoa=4.0)])
    write_polar_csv(filas, str(tmp_path / "p.csv"))
    leido = list(csv.DictReader(open(tmp_path / "p.csv")))
    assert [float(f["aoa"]) for f in leido] == [0.0, 4.0]
    ruta = write_polar_report({"base": {"naca": "0012", "reynolds": 6e6}, "filas": filas, "estudios": []},
                              str(tmp_path / "salida"))
    assert (tmp_path / "salida" / "polar.csv").exists() and (tmp_path / "salida" / "polar.json").exists()
    assert ruta.endswith("polar.png")


def _nivel_que_oscila(cd_amp=0.0002, cd_deriva_pct=0.002, cl_deriva=1e-5):
    j = trabajo(nivel=1, estado="NO CONVERGIDO", cl=1.48, cd=0.0186)
    j.analysis["verdict"].update(oscila=True, cd_amp=cd_amp, cd_drift_pct=cd_deriva_pct, cl_drift=cl_deriva)
    return j


def _finos(cl2=1.50):
    return [trabajo(nivel=2, cl=cl2, cd=0.0199), trabajo(nivel=3, cl=1.505, cd=0.0205)]


def test_a_level_that_barely_oscillates_counts_for_the_grid_study():
    r = grid_study_result([_nivel_que_oscila()] + _finos())
    assert r["sin_converger"] == [1] and r["oscilan"] == [1]
    assert "motivo" not in r and r["cd"]["orden"] is not None
    assert "oscila poco" in grid_study_text(r)


def test_the_amplitude_may_exceed_a_small_jump_if_the_mean_is_stable():
    # Medido a 10 grados: Cl oscila 6e-4 y el salto a la malla siguiente es de 1.5e-3
    r = grid_study_result([_nivel_que_oscila()] + _finos(cl2=1.4815))
    assert r["oscilan"] == [1]


@pytest.mark.parametrize("ajuste", [{"cd_amp": 0.002}, {"cd_deriva_pct": 2.0}, {"cl_deriva": 0.01}])
def test_a_level_that_oscillates_a_lot_or_whose_mean_moves_does_not_count(ajuste):
    r = grid_study_result([_nivel_que_oscila(**ajuste)] + _finos())
    assert r["oscilan"] == [] and "no convergieron" in r["motivo"]


def test_pitching_moment_counts_for_the_oscillation():
    j = _nivel_que_oscila()
    j.analysis["verdict"]["cm_amp"] = 0.05
    assert grid_study_result([j] + _finos())["oscilan"] == []


def test_only_the_coarsest_level_may_oscillate():
    # La banda sale de la media: no diria nada de una oscilacion en el nivel que se usa.
    medio = trabajo(nivel=2, estado="NO CONVERGIDO", cl=1.50, cd=0.0199)
    medio.analysis["verdict"].update(oscila=True, cl_amp=0.03, cd_amp=0.0002, cd_drift_pct=0.002, cl_drift=1e-5)
    r = grid_study_result([trabajo(nivel=1, cl=1.48, cd=0.0186), medio, trabajo(nivel=3, cl=1.505, cd=0.0205)])
    assert r["sin_converger"] == [2] and r["oscilan"] == [] and "motivo" in r


def test_polar_sends_the_fine_meshes_last(monkeypatch):
    import core.campaign as C

    enviados = []

    class Falso:
        def __init__(self, *a, **k):
            pass

        def set_machines(self, m):
            pass

        def submit(self, j):
            enviados.append(j.label)
            j.state = TERMINADO

        def wait(self):
            pass

    monkeypatch.setattr(C, "Dispatcher", Falso)
    r = C.run_polar([], {"reynolds": 6e6}, [0.0, 4.0], [0.0])
    assert enviados == ["gci_a0_n1", "gci_a0_n2", "polar_a4", "gci_a0_n3"]
    assert [f["aoa"] for f in r["filas"]] == [0.0, 4.0]


def test_an_interrupted_polar_goes_on_without_repeating_anything(monkeypatch):
    import core.campaign as C
    from core.jobs import CORRIENDO, FALLIDO, PENDIENTE, load_jobs

    enviados, retomados = [], []

    class Falso:
        def __init__(self, *a, **k):
            pass

        def set_machines(self, m):
            pass

        def submit(self, j):
            enviados.append(j.label)

        def attach(self, j):
            retomados.append(j.label)

        def wait(self):
            pass

    monkeypatch.setattr(C, "Dispatcher", Falso)
    C.run_polar([], {"reynolds": 6e6}, [2.0, 4.0, 6.0, 8.0, 10.0], [])
    assert enviados == ["polar_a2", "polar_a4", "polar_a6", "polar_a8", "polar_a10"]
    por_etiqueta = {j.label: j for j in load_jobs()}
    a2, a4, a6 = por_etiqueta["polar_a2"], por_etiqueta["polar_a4"], por_etiqueta["polar_a6"]
    a2.state = TERMINADO
    a2.save()
    a4.state, a4.remote_dir = CORRIENDO, "openblade_jobs/x"
    a4.save()
    a6.state = FALLIDO
    a6.save()
    a10 = por_etiqueta["polar_a10"]
    a10.state, a10.remote_dir, a10.rc, a10.error = FALLIDO, "openblade_jobs/y", 0, "rsync: sin espacio"
    a10.save()
    assert por_etiqueta["polar_a8"].state == PENDIENTE
    enviados.clear()
    total = len(load_jobs())
    r = C.run_polar([], {"reynolds": 6e6}, [2.0, 4.0, 6.0, 8.0, 10.0], [], continuar=True)
    # El calculo de a10 termino y solo fallo su descarga: se retoma, no se repite
    assert retomados == ["polar_a4", "polar_a10"]
    assert enviados == ["polar_a6", "polar_a8"]
    # Solo el que fallo de verdad tiene carpeta nueva
    assert len(load_jobs()) == total + 1
    assert [f["aoa"] for f in r["filas"]] == [2.0, 4.0, 6.0, 8.0, 10.0]


def test_a_point_that_blows_up_at_the_start_is_rescued_from_its_nearest_neighbor(monkeypatch):
    import core.campaign as C

    enviados = []

    class Falso:
        def __init__(self, *a, **k):
            pass

        def set_machines(self, m):
            pass

        def submit(self, j):
            enviados.append(j)
            j.state = TERMINADO
            estado = "DIVERGIDO" if j.params["aoa"] == 15.0 and not j.params.get("campo_inicial") else "CONVERGIDO"
            j.analysis = {"verdict": {"state": estado, "reason": "r", "cl": 1.0, "cl_amp": 0.0, "cd": 0.01,
                                      "cd_amp": 0.0, "cm": 0.0}, "yplus": {"mean": 0.7}}

        def attach(self, j):
            pass

        def wait(self):
            pass

    monkeypatch.setattr(C, "Dispatcher", Falso)
    r = C.run_polar([], {"reynolds": 6e6}, [4.0, 12.0, 15.0], [])
    rescate = enviados[-1]
    assert rescate.label == "polar_a15_vecino"
    a12 = next(j for j in enviados if j.label == "polar_a12")
    assert rescate.params["campo_inicial"] == a12.case_dir
    fila = next(f for f in r["filas"] if f["aoa"] == 15.0)
    assert fila["veredicto"] == "CONVERGIDO" and fila["trabajo"] == rescate.id
