"""Sensibilidad del veredicto a sus umbrales, con las series reales de la campaña.

Reproduce `resultados_v1.0.2_bb27cca/sensibilidad_veredicto_bb27cca.txt`: sobre las
corridas SST de v1.0.2 (63 casos, 49 CONVERGIDO), mover la ventana o los umbrales de
deriva cambia pocos veredictos y **ninguno de nivel 3**. Lo que de verdad decide es el
umbral del rango del 1 %.

Esta prueba no usa fixtures grandes: comprueba la propiedad que importa del veredicto,
que es su estabilidad, con historias construidas a partir de los coeficientes medidos.
"""

import os
import sys

import pytest

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, RAIZ)

from core import verdict
from core.verdict import CONVERGIDO, NO_CONVERGIDO
from core.forces import ForceHistory


def _historia(cl_final, cd_final, n=6000, ruido_cl=5e-5, ruido_cd=2e-6):
    """Historia plana: ya convergida, con el ruido de la ventana de una corrida real."""
    cl = [cl_final + ruido_cl * ((i % 7) - 3) for i in range(n)]
    cd = [cd_final + ruido_cd * ((i % 5) - 2) for i in range(n)]
    return ForceHistory({"Time": list(range(n)), "Cl": cl, "Cd": cd,
                         "Cm": [0.0] * n}, [])


def test_umbral_de_rango_es_el_que_decide():
    """Una corrida con el rango de Cd al 0.8 % pasa con el 1 % y falla con el 0.5 %.

    Es el hallazgo del análisis de sensibilidad: el tope del 1 % es el que decide si una
    corrida entra como convergida, y al estrecharlo a 0.5 % rechaza 15 de las 49.
    """
    n = 6000
    # Cd con una oscilacion del 0.8 % del valor medio dentro de la ventana.
    cd = [0.01 + 8e-5 * ((i % 2) - 0.5) for i in range(n)]
    cl = [1.0 + 5e-5 * ((i % 7) - 3) for i in range(n)]
    h = ForceHistory({"Time": list(range(n)), "Cl": cl, "Cd": cd,
                      "Cm": [0.0] * n}, [])
    assert verdict.evaluate(h).state == CONVERGIDO
    original = verdict.TOL_RANGO
    try:
        verdict.TOL_RANGO = original * 0.5
        v = verdict.evaluate(h)
        assert v.state == NO_CONVERGIDO
        assert "rango" in v.reason.lower() or "Cd" in v.reason
    finally:
        verdict.TOL_RANGO = original


def test_ventana_cambia_poco_una_corrida_plana():
    """Duplicar o reducir la ventana no cambia el veredicto de una corrida ya plana."""
    h = _historia(1.0656, 0.01142)
    base = verdict.evaluate(h)
    assert base.state == CONVERGIDO
    original = verdict.VENTANA
    try:
        for factor in (0.5, 2.0):
            verdict.VENTANA = int(original * factor)
            v = verdict.evaluate(h)
            assert v.state == CONVERGIDO
            assert v.cl == pytest.approx(base.cl, abs=1e-4)
    finally:
        verdict.VENTANA = original


def test_coeficientes_de_la_campana_no_dependen_del_umbral_de_deriva():
    """Mover el umbral de deriva de Cd al doble no cambia el veredicto de una corrida plana."""
    h = _historia(0.4345, 0.00829)
    original = verdict.TOL_DERIVA
    try:
        verdict.TOL_DERIVA = original * 2.0
        assert verdict.evaluate(h).state == CONVERGIDO
        verdict.TOL_DERIVA = original * 0.5
        assert verdict.evaluate(h).state == CONVERGIDO
    finally:
        verdict.TOL_DERIVA = original
