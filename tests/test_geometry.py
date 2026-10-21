import pytest
import numpy as np
import gmsh
from core.geometry import NacaGeometry
import math

def test_valid_naca():
    """Test generating points for a valid NACA 0012 airfoil."""
    geom = NacaGeometry(naca_code="0012", chord=1.0)
    x, y = geom.get_points(n_points=100)
    
    # 100 on upper and 100 on lower surface -> 200 points total from concatenation
    # wait, get_points returns upper and lower without concatenation yet, but it does return x_rot, y_rot
    
    assert isinstance(x, np.ndarray), "x coordinates must be a numpy array"
    assert isinstance(y, np.ndarray), "y coordinates must be a numpy array"
    
    # The airfoil array starts at the trailing edge (x≈1.0) and wraps around to leading edge (x≈0.0).
    # Verify the full chord spans from 0 to 1.
    assert np.min(x) == pytest.approx(0.0, abs=0.01), "Leading edge should be near x=0"
    assert np.max(x) == pytest.approx(1.0, abs=0.01), "Trailing edge should be near x=1"
    
def test_invalid_naca_format():
    """Test providing an invalid NACA string."""
    geom = NacaGeometry(naca_code="00A2", chord=1.0)
    with pytest.raises(ValueError, match="Falla de Validación: el código NACA debe tener exactamente 4 dígitos numéricos"):
        geom.get_points()

def test_invalid_naca_length():
    """Test providing a NACA code with wrong length."""
    geom = NacaGeometry(naca_code="012", chord=1.0)
    with pytest.raises(ValueError, match="Falla de Validación"):
        geom.get_points()

def test_aoa_rotation():
    """Test angle of attack rotation."""
    geom = NacaGeometry(naca_code="0012", chord=1.0, aoa=90.0)
    x, y = geom.get_points(n_points=10)
    
    # Rotation is about the aerodynamic center (25% chord = 0.25, 0).
    # After 90° pitch, the chord is mostly vertical: x values cluster near 0.25
    # and the x-range equals the airfoil thickness (~12% chord for NACA 0012).
    x_range = np.max(x) - np.min(x)
    y_range = np.max(y) - np.min(y)
    assert x_range < 0.15, f"After 90° AoA x-range should equal thickness (~0.12), got {x_range:.3f}"
    assert y_range > 0.8, f"After 90° AoA y-range should span the chord (~1.0), got {y_range:.3f}"


def test_structured_mesh_puts_full_contour_on_airfoil_patch(tmp_path):
    """Regresión: `CType(..., farfield_size, ...)` dejaba el perfil con 3 puntos
    y el patch `airfoil` acababa con 11 caras; el resto se perdía en defaultFaces.

    Se comprueba sobre el .msh exportado: los quads del grupo físico `airfoil`
    deben ser del orden del número de puntos del perfil, no una decena.
    """
    import subprocess, sys, os
    from collections import Counter

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    params = {
        "naca": "0012", "chord": 1.0, "aoa": 4.0,
        "profile_type": "NACA 4-dígitos",
        "mesh_size_min": 0.02, "mesh_size_max": 0.5,
        "bl_dist_min": 2e-5, "mesh_num_layers": 10,
        "mesh_growth_rate": 1.15, "mesh_nb_points": 200,
        "wake_length": 10.0, "farfield": 30.0, "depth": 0.1,
        "mesh_strategy": "structured",
    }
    jf = tmp_path / "p.json"
    jf.write_text(__import__("json").dumps(params))
    msh = tmp_path / "m.msh"

    env = os.environ.copy()
    env["PYTHONPATH"] = root
    r = subprocess.run([sys.executable, "-m", "core.mesh_script", str(jf), str(msh)],
                       capture_output=True, text=True, env=env, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]

    lines = msh.read_text().splitlines()
    i = lines.index("$Elements")
    n = int(lines[i + 1])
    quads = Counter()
    for line in lines[i + 2: i + 2 + n]:
        parts = line.split()
        if int(parts[1]) != 3:
            continue
        ntags = int(parts[2])
        phys = int(parts[3])
        quads[phys] += 1

    # Grupo físico 5 = airfoil (ver $PhysicalNames)
    assert quads[5] > 50, (
        f"el patch airfoil tiene solo {quads[5]} caras; el contorno del perfil "
        "se está perdiendo en defaultFaces"
    )
