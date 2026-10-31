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
    """Primera celda de 2e-5c: dentro de la subcapa viscosa a Re=1e6 y Re=6e6."""
    assert params["bl_dist_min"] <= 5e-5, (
        f"primera celda {params['bl_dist_min']}c: la capa límite es más "
        "gruesa que el perfil (0.12c)")


def test_profile_is_resolved(params):
    """El contorno necesita suficientes puntos para el patch airfoil."""
    assert params["mesh_size_min"] <= 0.01


def test_default_run_has_enough_iterations(params):
    """Con 500 iteraciones la corrida por defecto terminaba sin converger."""
    assert params["max_iters"] >= 6000


def test_inflow_defaults_are_the_tmr_values(params):
    assert params["turb_intensity"] == pytest.approx(0.052)
    assert params["viscosity_ratio"] == pytest.approx(0.009)


def test_gamma_retheta_is_not_offered_because_openfoam_12_does_not_have_it():
    """El modelo no existe: el solver abortaba al leer turbulenceProperties."""
    from gui.input_panel import InputPanel
    panel = InputPanel()
    opciones = [panel.turbulence_model.itemText(i) for i in range(panel.turbulence_model.count())]
    assert not any("gamma-ReTheta" in o for o in opciones)
    panel.deleteLater()


def test_choosing_k_epsilon_moves_the_mesh_to_wall_functions():
    from gui.input_panel import InputPanel
    panel = InputPanel()
    panel.reynolds_input.setValue(6e6)
    panel.turbulence_model.setCurrentText("k-Epsilon (RAS)")
    assert panel.yplus_target.value() == 60.0
    assert "logarítmica" in panel.yplus_estimate.text()
    panel.turbulence_model.setCurrentText("k-Omega SST (RAS)")
    assert panel.yplus_target.value() == 0.5
    panel.deleteLater()


def test_first_cell_for_yplus_one_is_reachable():
    """Con 5 decimales 8.9e-6 se redondeaba a 1e-5: y+ = 1 a Re=6e6 no se podia pedir."""
    from gui.input_panel import InputPanel
    panel = InputPanel()
    panel.bl_dist_min.setValue(8.9e-6)
    assert panel.get_params()["bl_dist_min"] == pytest.approx(8.9e-6)
    panel.deleteLater()


def test_yplus_estimate_follows_the_panel():
    from gui.input_panel import InputPanel
    panel = InputPanel()
    panel.reynolds_input.setValue(6e6)
    assert "≈ 0.50" in panel.yplus_estimate.text()
    panel.grid_level.setCurrentIndex(1)
    assert "≈ 1.00" in panel.yplus_estimate.text()
    panel.set_params({"mesher": "gmsh"})
    assert "≈ 2.24" in panel.yplus_estimate.text()
    panel.bl_dist_min.setValue(1e-3)
    assert "logarítmica" in panel.yplus_estimate.text()
    panel.deleteLater()


def test_wheel_does_not_change_a_field_without_focus():
    """Al desplazar el panel la rueda cambiaba el AoA sin que nadie lo notara."""
    from qtpy.QtCore import QPoint, QPointF, Qt
    from qtpy.QtGui import QWheelEvent
    from qtpy.QtWidgets import QApplication
    from gui.input_panel import InputPanel
    panel = InputPanel()
    panel.aoa_input.setValue(0.0)
    evento = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(panel.aoa_input, evento)
    assert panel.aoa_input.value() == 0.0
    panel.deleteLater()


def test_saved_project_round_trip_keeps_new_fields(params):
    from gui.input_panel import InputPanel
    panel = InputPanel()
    p = dict(params, turb_intensity=0.2, viscosity_ratio=1.0, momentum_scheme="upwind",
             nb_airfoil_pts=300, bl_dist_min=8e-6)
    panel.set_params(p)
    q = panel.get_params()
    for clave in ("turb_intensity", "viscosity_ratio", "momentum_scheme", "nb_airfoil_pts"):
        assert q[clave] == p[clave]
    # un proyecto antiguo trae claves de controles que ya no existen
    panel.set_params({"element_type": "Quads (Gmsh)", "mesh_curvature": 100})
    panel.deleteLater()


def test_domain_is_large_enough(params):
    """Sin control de dominio el mesh_script usa 10c: dominio 5x menor."""
    assert "farfield" in params, "falta el control de dominio exterior"
    assert params["farfield"] >= 30.0


def test_default_mesh_is_the_nested_one_at_the_medium_level(params):
    assert params["mesher"] == "cgrid" and params["grid_level"] == 2


def test_each_mesher_shows_only_the_controls_that_change_it():
    from gui.input_panel import InputPanel
    panel = InputPanel()
    assert panel.mesh_layout.isRowVisible(panel.grid_level)
    assert not panel.mesh_layout.isRowVisible(panel.mesh_size_min)
    panel.set_params({"mesher": "gmsh"})
    assert not panel.mesh_layout.isRowVisible(panel.grid_level)
    assert panel.mesh_layout.isRowVisible(panel.mesh_size_min)
    assert "2.24" in panel.yplus_estimate.text() or "Primera celda" in panel.yplus_estimate.text()
    panel.deleteLater()


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


def test_window_defaults_are_the_ones_of_the_command_line(params):
    """La ventana y la linea de comandos parten del mismo caso."""
    from core.defaults import DEFAULT_PARAMS
    distintos = {k: (params.get(k), v) for k, v in DEFAULT_PARAMS.items() if params.get(k) != v}
    assert distintos == {}
