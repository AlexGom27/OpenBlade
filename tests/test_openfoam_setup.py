import pytest
import os
from core.openfoam_setup import OpenFoamSetup

def test_create_case_structure(tmp_path):
    """Test generating openfoam dictionary structures in a dummy tmp_path."""
    case_dir = tmp_path / "dummy_case"
    setup = OpenFoamSetup(case_dir=str(case_dir))
    
    # Exec
    setup.create_case(
        u_inlet=25.0, 
        p_outlet=0.0, 
        chord=1.5, 
        transient=False, 
        turbulence="Spalart-Allmaras (RAS)"
    )
    
    # Assert directories
    assert (case_dir / "0").exists()
    assert (case_dir / "system").exists()
    assert (case_dir / "constant").exists()
    
    # Assert specific files
    assert (case_dir / "system" / "controlDict").exists()
    assert (case_dir / "system" / "fvSchemes").exists()
    assert (case_dir / "constant" / "transportProperties").exists()
    assert (case_dir / "0" / "U").exists()
    
    # Read a generated file to ensure template populated correctly
    with open(case_dir / "0" / "U", "r") as f:
        u_content = f.read()
    
    assert "internalField   uniform (25.0 0 0);" in u_content
    # SA shouldn't create k, epsilon by default, but it does in the generic OpenFoamSetup 
    # to be safe, we check that at least U and p created correctly.
    assert (case_dir / "0" / "nuTilda").exists()
    
def test_transient_parameter_application(tmp_path):
    """Verify that pimpleFoam settings inject properly into controlDict"""
    case_dir = tmp_path / "transient_case"
    setup = OpenFoamSetup(case_dir=str(case_dir))
    
    setup.create_case(transient=True, end_time="2.5", delta_t="1e-4")
    
    # Verify controlDict has pimpleFoam specifics
    with open(case_dir / "system" / "controlDict", "r") as f:
        content = f.read()
        
    assert "application     pimpleFoam;" in content
    assert "endTime         2.5;" in content
    assert "deltaT          1e-4;" in content


def test_momentum_scheme_default_is_limited_linear(tmp_path):
    setup = OpenFoamSetup(case_dir=str(tmp_path / "c"))
    setup.create_case()
    schemes = (tmp_path / "c" / "system" / "fvSchemes").read_text()
    assert "div(phi,U)      bounded Gauss limitedLinearV 1;" in schemes


def test_linear_upwind_gets_gradient_argument(tmp_path):
    """linearUpwind sin `grad(U)` hace abortar a OpenFOAM con EOF."""
    setup = OpenFoamSetup(case_dir=str(tmp_path / "c"))
    setup.create_case(momentum_scheme="linearUpwind")
    schemes = (tmp_path / "c" / "system" / "fvSchemes").read_text()
    assert "bounded Gauss linearUpwind grad(U);" in schemes


def test_boundary_conditions_match_mesher_patch_names(tmp_path):
    """El mallador crea `farfield`, no `walls_TB`: una BC para un parche
    inexistente se ignora en silencio."""
    setup = OpenFoamSetup(case_dir=str(tmp_path / "c"))
    setup.create_case()
    for field in ("U", "p", "k", "omega", "nut"):
        text = (tmp_path / "c" / "0" / field).read_text()
        assert "walls_TB" not in text, f"{field} referencia un parche inexistente"
        assert "farfield" in text


def test_yplus_does_not_write_every_iteration(tmp_path):
    """writeInterval 1 creaba un directorio por iteración (1678 en una corrida)."""
    setup = OpenFoamSetup(case_dir=str(tmp_path / "c"))
    setup.create_case()
    control = (tmp_path / "c" / "system" / "controlDict").read_text()
    block = control.split("yPlus", 1)[1].split("}", 1)[0]
    assert "writeInterval   1;" not in block
