"""Los valores por defecto de la GUI deben producir mallas válidas.

Motivación: los defaults estaban puestos para "cálculo rápido" (5 capas de
capa límite, primera celda de 0.05c, 100 puntos en el perfil). Con esos valores
la malla tiene 9 828 nodos y la capa límite es más gruesa que el perfil, así
que los resultados no tienen valor físico. Estos tests fijan los valores
mínimos que se validaron contra NASA TM 4074.
"""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="module")
def params():
    from qtpy.QtWidgets import QApplication
    from gui.input_panel import InputPanel

    app = QApplication.instance() or QApplication([])
    panel = InputPanel()
    p = panel.get_params()
    yield p
    panel.deleteLater()


def test_boundary_layer_is_resolved(params):
    """30 capas y primera celda de 2e-5c: y+ ~ 1 a Re=6e6."""
    assert params["mesh_num_layers"] >= 25, (
        f"{params['mesh_num_layers']} capas no resuelven el gradiente")
    assert params["bl_dist_min"] <= 5e-5, (
        f"primera celda {params['bl_dist_min']}c: la capa límite es más "
        "gruesa que el perfil (0.12c)")


def test_profile_is_resolved(params):
    """El contorno necesita suficientes puntos para el patch airfoil."""
    assert params["mesh_nb_points"] >= 300
    assert params["mesh_size_min"] <= 0.01


def test_domain_is_large_enough(params):
    """Sin control de dominio el mesh_script usa 10c: dominio 5x menor."""
    assert "farfield" in params, "falta el control de dominio exterior"
    assert params["farfield"] >= 30.0


def test_decimals_precede_value():
    """setValue antes de setDecimals trunca el valor.

    Con los decimales por defecto (2), 0.00002 se redondea a 0.00 y la capa
    límite desaparece silenciosamente.
    """
    import re
    src = open(os.path.join(os.path.dirname(__file__), "..", "gui",
                            "input_panel.py")).read()
    for field in ("mesh_size_min", "bl_dist_min"):
        m = re.search(rf"self\.{field}\s*=\s*QDoubleSpinBox\(\)(.*?)(?=\n\s*self\.\w+\s*=)",
                      src, re.S)
        assert m, f"no se encontró el bloque de {field}"
        body = m.group(1)
        dec = body.find("setDecimals")
        val = body.find("setValue")
        assert dec != -1 and val != -1, f"{field}: falta setDecimals o setValue"
        assert dec < val, (
            f"{field}: setValue antes de setDecimals trunca el valor")
