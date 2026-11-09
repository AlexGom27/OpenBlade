"""Volver a mirar una campana de control ya calculada, sin lanzarla otra vez."""

import json
import os

import pytest

from core import jobs as J
from core.cli import main
from core.control import ControlIncompleto, evaluar_guardados
from core.defaults import case_params
from core.jobs import CORRIENDO, FALLIDO, TERMINADO, new_job


@pytest.fixture(autouse=True)
def _datos_limpios(tmp_path, monkeypatch):
    """Cada prueba con sus propios trabajos.

    Los ids empiezan por la fecha del dia, asi que sin esto los trabajos de una
    prueba salen en la busqueda por prefijo de la siguiente y la campana parece
    completa cuando no lo esta.
    """
    monkeypatch.setenv("OPENBLADE_DATA_DIR", str(tmp_path / "datos"))
    yield


def _con_resultados(aoa, host, estado=TERMINADO):
    """Un trabajo de control con su case, sus fuerzas y su analisis."""
    j = new_job(case_params(aoa=aoa, reynolds=6e6), host, 8,
                label=f"control_a{aoa:g}_{host.split('@')[-1]}")
    # Valores del caso de control real: las compuertas 6 y 7 deben pasar.
    cd = 0.00809 if aoa == 0 else 0.01028
    cl = -0.0072 if aoa == 0 else 0.8557
    ruta = os.path.join(j.case_dir, "postProcessing", "forceCoeffs", "0")
    os.makedirs(ruta, exist_ok=True)
    with open(os.path.join(ruta, "forceCoeffs.dat"), "w") as f:
        f.write("# Time\tCm\tCd\tCl\n")
        for i in range(1, 3001):
            f.write(f"{i}\t0.0\t{cd}\t{cl}\n")
    # La ficha con la malla: la compuerta 1 la lee de ahi.
    with open(os.path.join(j.case_dir, "ficha.json"), "w") as f:
        json.dump({"archivos": {"mesh.msh": "da22c85800000000000000000000000000000000000000000000000000000000"}}, f)
    j.analysis = {"verdict": {"state": "CONVERGIDO", "cl": cl, "cd": cd},
                  "yplus": {"mean": 0.5}}
    j.state = estado
    j.save()
    return j


def test_gates_are_evaluated_from_saved_jobs_without_launching_anything(monkeypatch):
    """Repetir el control costaba 10 h de calculo; mirar los resultados, nada."""
    a0a = _con_resultados(0.0, "u@h1")
    a0b = _con_resultados(0.0, "u@h2")
    a8a = _con_resultados(8.0, "u@h1")
    a8b = _con_resultados(8.0, "u@h2")

    def no_lanzar(*a, **k):
        raise AssertionError("no debe lanzarse nada al evaluar")

    monkeypatch.setattr(J, "new_job", no_lanzar)
    monkeypatch.setattr(J.Dispatcher, "submit", no_lanzar)

    r = evaluar_guardados(a0a.id[:15])
    assert sorted(r["por_angulo"]) == [0.0, 8.0]
    assert len(r["por_angulo"][0.0]) >= 8
    assert all(f["ok"] for f in r["por_angulo"][0.0]), r["por_angulo"][0.0]
    assert r["trabajos"]["0@h1"] == a0a.id
    assert r["trabajos"]["8@h2"] == a8b.id


def test_a_missing_package_is_reported_instead_of_evaluated():
    """Faltando uno, las compuertas de ese angulo mentirian: se dice y no se evalua."""
    a0a = _con_resultados(0.0, "u@h1")
    _con_resultados(8.0, "u@h1")
    _con_resultados(8.0, "u@h2")
    with pytest.raises(ControlIncompleto) as e:
        evaluar_guardados(a0a.id[:15])
    assert "α=0" in str(e.value), str(e.value)


def test_a_package_still_running_blocks_the_evaluation():
    """El ultimo paquete del 174028 seguia descargando: no se puede evaluar aun."""
    _con_resultados(0.0, "u@h1")
    _con_resultados(0.0, "u@h2", estado=CORRIENDO)
    _con_resultados(8.0, "u@h1")
    _con_resultados(8.0, "u@h2")
    prefijo = next(j.id[:15] for j in J.load_jobs() if j.label.startswith("control_a0"))
    with pytest.raises(ControlIncompleto) as e:
        evaluar_guardados(prefijo)
    assert "corriendo" in str(e.value)


def test_a_package_without_its_result_blocks_the_evaluation():
    """Terminado pero sin descargar: las compuertas saldrian vacias."""
    j = _con_resultados(0.0, "u@h1")
    _con_resultados(0.0, "u@h2")
    _con_resultados(8.0, "u@h1")
    _con_resultados(8.0, "u@h2")
    j.analysis = None
    j.save()
    with pytest.raises(ControlIncompleto) as e:
        evaluar_guardados(j.id[:15])
    assert "sin resultado descargado" in str(e.value)


def test_the_command_writes_the_same_json_and_returns_nonzero_when_a_gate_fails(tmp_path):
    a0a = _con_resultados(0.0, "u@h1")
    _con_resultados(0.0, "u@h2")
    a8a = _con_resultados(8.0, "u@h1")
    # Un Cd muy fuera de Ladson: la compuerta 6 del 8 grados falla.
    ruta = os.path.join(a8a.case_dir, "postProcessing", "forceCoeffs", "0", "forceCoeffs.dat")
    with open(ruta, "w") as f:
        f.write("# Time\tCm\tCd\tCl\n")
        for i in range(1, 3001):
            f.write(f"{i}\t0.0\t0.03000\t0.8614\n")
    a8a.analysis = {"verdict": {"state": "CONVERGIDO", "cl": 0.8614, "cd": 0.03000},
                    "yplus": {"mean": 0.5}}
    a8a.save()
    _con_resultados(8.0, "u@h2")

    salida = tmp_path / "c.json"
    codigo = main(["control", "--evaluar", a0a.id[:15], "--salida", str(salida)])
    datos = json.load(open(salida))
    assert codigo == 1, "una compuerta falla y el codigo debe decirlo"
    # En JSON las claves numericas van como texto; el resumen en pantalla no cambia.
    assert sorted(float(a) for a in datos["por_angulo"]) == [0.0, 8.0]
    assert "por_angulo" in datos and "trabajos" in datos


def test_the_command_says_what_is_missing_and_does_not_launch(tmp_path):
    j = _con_resultados(0.0, "u@h1")
    codigo = main(["control", "--evaluar", j.id[:15]])
    assert codigo == 2
