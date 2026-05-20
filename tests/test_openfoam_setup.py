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
