"""La compuerta 2 compara las fuerzas, no el tamano del archivo.

El caso de control lanza el mismo paquete en dos maquinas y exige el mismo
archivo de fuerzas. Con una de ellas inalcanzable, la Mac no podia recortar la
corrida y una acabo en 40000 y la otra en 16000, con las fuerzas identicas hasta
donde coincidian: la compuerta fallaba por la red, no por el programa.
"""

import os

import pytest

from core.control import evaluate_gates
from core.defaults import case_params
from core.jobs import TERMINADO, new_job


def _trabajo(aoa, host):
    return new_job(case_params(aoa=aoa, reynolds=6e6), host, 8)


def _escribir(caso, iteraciones, cd=0.00884, cl=0.8614):
    ruta = os.path.join(caso, "postProcessing", "forceCoeffs", "0")
    os.makedirs(ruta, exist_ok=True)
    with open(os.path.join(ruta, "forceCoeffs.dat"), "w") as f:
        f.write("# Time\tCm\tCd\tCl\n")
        for i in range(iteraciones + 1):
            f.write(f"{i}\t0.0\t{cd}\t{cl}\n")


def _par(a, b):
    ja, jb = _trabajo(0.0, "a@h"), _trabajo(0.0, "b@h")
    _escribir(ja.case_dir, a)
    _escribir(jb.case_dir, b)
    ja.analysis = {"verdict": {"state": "CONVERGIDO", "cl": 0.0, "cd": 0.00884}, "yplus": {"mean": 0.5}}
    jb.analysis = {"verdict": {"state": "CONVERGIDO", "cl": 0.0, "cd": 0.00884}, "yplus": {"mean": 0.5}}
    return evaluate_gates(0.0, [ja, jb])


def test_two_runs_stopped_at_different_iterations_pass_when_the_forces_match():
    """Uno paro en 40000 y el otro en 16000: las fuerzas del tramo comun son iguales."""
    g2 = next(f for f in _par(40000, 16000) if f["n"] == 2)
    assert g2["ok"], g2["detalle"]


def test_two_runs_that_disagree_in_the_forces_still_fail():
    """La compuerta sigue sirviendo: si el Cd no coincide, falla."""
    ja, jb = _trabajo(0.0, "a@h"), _trabajo(0.0, "b@h")
    _escribir(ja.case_dir, 5000, cd=0.00884)
    _escribir(jb.case_dir, 5000, cd=0.00910)
    for j in (ja, jb):
        j.analysis = {"verdict": {"state": "CONVERGIDO", "cl": 0.0, "cd": 0.00884}, "yplus": {"mean": 0.5}}
    g2 = next(f for f in evaluate_gates(0.0, [ja, jb]) if f["n"] == 2)
    assert not g2["ok"]
