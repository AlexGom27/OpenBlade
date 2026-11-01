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
    
    assert "internalField   uniform (25 0 0);" in u_content
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


def _valor_entrada(caso, campo):
    texto = (caso / "0" / campo).read_text()
    return float(texto.split("internalField")[1].split("uniform")[1].split(";")[0])


def test_inflow_comes_from_tu_and_viscosity_ratio(tmp_path):
    """k = 1.5 (U Tu)^2, omega = k / (nut/nu nu); con .6f k se perdia al escribirse."""
    caso = tmp_path / "c"
    OpenFoamSetup(case_dir=str(caso)).create_case(
        u_inlet=15.0, chord=1.0, reynolds=6e6, turb_intensity=0.00052, viscosity_ratio=0.009)
    k = 1.5 * (15.0 * 0.00052) ** 2
    assert _valor_entrada(caso, "k") == pytest.approx(k, rel=1e-5)
    assert _valor_entrada(caso, "omega") == pytest.approx(k / (0.009 * 2.5e-6), rel=1e-5)
    assert "airfoil" in (caso / "0" / "k").read_text()


def test_other_turbulence_models_get_consistent_inflow(tmp_path):
    caso = tmp_path / "c"
    OpenFoamSetup(case_dir=str(caso)).create_case(
        u_inlet=10.0, chord=1.0, reynolds=1e6, turbulence="k-Epsilon (RAS)",
        turb_intensity=0.01, viscosity_ratio=1.0)
    k = 1.5 * (10.0 * 0.01) ** 2
    assert _valor_entrada(caso, "epsilon") == pytest.approx(0.09 * k * k / 1e-5, rel=1e-5)
    caso = tmp_path / "sa"
    OpenFoamSetup(case_dir=str(caso)).create_case(
        u_inlet=15.0, chord=1.0, reynolds=6e6, turbulence="Spalart-Allmaras (RAS)")
    assert _valor_entrada(caso, "nuTilda") == pytest.approx(3 * 2.5e-6, rel=1e-5)


def test_retheta_uses_tu_in_percent_with_both_branches(tmp_path):
    def re_theta(tu):
        caso = tmp_path / f"t{tu}"
        OpenFoamSetup(case_dir=str(caso)).create_case(
            turbulence="k-Omega SST-LM Transición (RAS)", turb_intensity=tu)
        return _valor_entrada(caso, "ReThetat")
    assert re_theta(0.00052) == pytest.approx(1224, abs=2)
    assert re_theta(0.05) == pytest.approx(331.5 * (5 - 0.5658) ** -0.671, abs=0.1)


@pytest.mark.parametrize("reynolds,primera,condicion", [
    (6e6, 2e-5, "nutLowReWallFunction"),
    (1e6, 2e-5, "nutLowReWallFunction"),
    (6e6, 1e-3, "nutkWallFunction"),
    (1e9, 2e-5, "nutkWallFunction"),
])
def test_wall_condition_follows_the_estimated_yplus(tmp_path, reynolds, primera, condicion):
    caso = tmp_path / "c"
    OpenFoamSetup(case_dir=str(caso)).create_case(reynolds=reynolds, bl_dist_min=primera)
    assert condicion in (caso / "0" / "nut").read_text()


@pytest.mark.parametrize("iteraciones,intervalo", [(6000, 50), (500, 50), (525, 25), (777, 1)])
def test_last_iteration_is_always_written(tmp_path, iteraciones, intervalo):
    caso = tmp_path / "c"
    OpenFoamSetup(case_dir=str(caso)).create_case(max_iters=iteraciones)
    control = (caso / "system" / "controlDict").read_text()
    assert f"writeInterval   {intervalo};" in control


def test_gui_parameters_reach_the_case(tmp_path):
    """Lo validado por scripts no era lo que corre la GUI: estos parametros se perdian."""
    from core.solve_script import configure_case
    caso = tmp_path / "c"
    configure_case(str(caso), {
        "u_inlet": 15.0, "p_outlet": 0.0, "chord": 2.0, "reynolds": 6e6,
        "turbulence": "k-Omega SST (RAS)", "regime": "Estacionario (simpleFoam)",
        "momentum_scheme": "upwind", "bl_dist_min": 1e-3, "turb_intensity": 0.2,
        "viscosity_ratio": 2.0, "depth": 0.1, "max_iters": 100})
    control = (caso / "system" / "controlDict").read_text()
    # Aref = cuerda x profundidad; la malla extruye 0.1 cuerdas
    assert "Aref            0.4;" in control
    assert "Gauss upwind;" in (caso / "system" / "fvSchemes").read_text()
    assert "nutkWallFunction" in (caso / "0" / "nut").read_text()
    k = 1.5 * (15.0 * 0.002) ** 2
    assert _valor_entrada(caso, "k") == pytest.approx(k, rel=1e-5)
    assert _valor_entrada(caso, "omega") == pytest.approx(k / (2.0 * 5e-6), rel=1e-5)


def test_previous_run_leaves_nothing_behind(tmp_path):
    """Un 0/phi o un run.log viejos viajarian con el paquete siguiente."""
    caso = tmp_path / "c"
    setup = OpenFoamSetup(case_dir=str(caso))
    setup.create_case()
    for viejo in ("0/phi", "run.log", "log.gmshToFoam", "resultado.json", "ficha.json"):
        (caso / viejo).write_text("viejo")
    (caso / "processor0").mkdir()
    (caso / "6000").mkdir()
    setup.create_case()
    for viejo in ("0/phi", "run.log", "log.gmshToFoam", "resultado.json", "ficha.json",
                  "processor0", "6000"):
        assert not (caso / viejo).exists(), viejo
    assert (caso / "0" / "U").exists()


def test_angle_by_flow_turns_inlet_and_force_directions(tmp_path):
    from math import cos, radians, sin
    caso = tmp_path / "c"
    OpenFoamSetup(case_dir=str(caso)).create_case(u_inlet=10.0, aoa_flow=10.0)
    u = (caso / "0" / "U").read_text()
    assert f"{10 * cos(radians(10)):.12g} {10 * sin(radians(10)):.12g} 0" in u
    control = (caso / "system" / "controlDict").read_text()
    assert f"dragDir         ({cos(radians(10)):.12g} {sin(radians(10)):.12g} 0);" in control
    assert f"liftDir         ({-sin(radians(10)):.12g} {cos(radians(10)):.12g} 0);" in control


def test_pitching_moment_is_positive_nose_up(tmp_path):
    caso = tmp_path / "c"
    OpenFoamSetup(case_dir=str(caso)).create_case()
    assert "pitchAxis       (0 0 -1);" in (caso / "system" / "controlDict").read_text()


def test_free_outer_boundary_lets_the_flow_in_and_out_anywhere(tmp_path):
    caso = tmp_path / "c"
    OpenFoamSetup(case_dir=str(caso)).create_case(bc_type="libre", aoa_flow=5.0)
    assert (caso / "0" / "U").read_text().count("type freestreamVelocity;") == 2
    assert (caso / "0" / "p").read_text().count("type freestreamPressure;") == 2
    assert (caso / "0" / "k").read_text().count("type inletOutlet;") == 2
    assert (caso / "0" / "omega").read_text().count("type inletOutlet;") == 2


def test_mesh_points_keep_their_precision(tmp_path):
    """gmshToFoam redondeaba los puntos a 6 cifras: mas que la altura de una celda de pared."""
    caso = tmp_path / "c"
    OpenFoamSetup(case_dir=str(caso)).create_case()
    assert "writePrecision  15;" in (caso / "system" / "controlDict").read_text()


def test_turbulence_equations_are_never_frozen_by_the_absolute_tolerance(tmp_path):
    """Con 1e-6, k y omega hacian 0 iteraciones y las fuerzas parecian convergidas."""
    import re
    caso = tmp_path / "c"
    OpenFoamSetup(case_dir=str(caso)).create_case()
    solucion = (caso / "system" / "fvSolution").read_text()
    bloque = solucion[solucion.index('"(U|k|omega)"'):]
    assert float(re.search(r"tolerance\s+([0-9e.-]+);", bloque).group(1)) <= 1e-12


def test_bounded_convection_is_only_for_steady_runs(tmp_path):
    """En transitorio, "bounded" quita un termino que forma parte del paso de tiempo."""
    from core.openfoam_setup import OpenFoamSetup

    def esquemas(transitorio):
        carpeta = tmp_path / ("t" if transitorio else "e")
        OpenFoamSetup(str(carpeta)).create_case(transient=transitorio, ddt_scheme="Euler")
        return (carpeta / "system" / "fvSchemes").read_text()

    estacionario, transitorio = esquemas(False), esquemas(True)
    assert "bounded Gauss" in estacionario and "steadyState" in estacionario
    assert "bounded" not in transitorio and "default Euler" in transitorio


def test_the_outlet_stops_backflow_only_in_a_transient(tmp_path):
    from core.openfoam_setup import OpenFoamSetup

    def salida(transitorio):
        carpeta = tmp_path / ("t" if transitorio else "e")
        OpenFoamSetup(str(carpeta)).create_case(transient=transitorio)
        texto = (carpeta / "0" / "U").read_text()
        return texto[texto.index("outlet"):texto.index("}", texto.index("outlet"))]

    assert "inletOutlet" in salida(True)
    assert "zeroGradient" in salida(False)
