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
