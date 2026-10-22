"""Regresión: el contorno del perfil no debe tener puntos duplicados.

`addSpline` de OCC rechaza puntos coincidentes y aborta con
"Could not create spline", que es el error que aparecía al pulsar
"Generar Geometría" en la GUI. El fallo venía de concatenar el extradós
invertido con el intradós sin quitar el punto del borde de salida, que
quedaba repetido al principio y al final.
"""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.mark.parametrize("aoa", [0.0, 4.0, 8.0, 12.0, -4.0])
def test_contour_has_no_duplicate_endpoints(aoa):
    from core.geometry import NacaGeometry

    x, y = NacaGeometry("0012", 1.0, aoa).get_points(100)
    gap = math.hypot(x[0] - x[-1], y[0] - y[-1])
    assert gap > 1e-6, (
        f"primer y último punto coinciden (distancia {gap:.2e}): "
        "addSpline fallará")


@pytest.mark.parametrize("naca", ["0012", "2412", "4412"])
def test_all_four_digit_profiles_close(naca):
    from core.geometry import NacaGeometry

    x, y = NacaGeometry(naca, 1.0, 0.0).get_points(120)
    assert len(x) == len(y)
    assert 0.0 <= x.min() and x.max() <= 1.01


def test_geometry_builds_in_gmsh():
    """La prueba que reproduce el error original del botón."""
    gmsh = pytest.importorskip("gmsh")
    from core.geometry import NacaGeometry

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        NacaGeometry("0012", 1.0, 8.0).build_geometry(
            mesh_extrusion=False, preview=True)
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"build_geometry falló: {e}")
    finally:
        if gmsh.isInitialized():
            gmsh.finalize()
