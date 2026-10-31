"""El veredicto y el y+ del programa, con historias e inputs sinteticos."""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.forces import ForceHistory
from core.verdict import (CONVERGIDO, DIVERGIDO, NO_CONVERGIDO, SIN_DATOS, analyze_case,
                          evaluate, evaluate_case)
from core.yplus import (compute_yplus, estimate_yplus, first_cell_distance,
                        first_cell_for_yplus, regime_notice, wall_condition, YPlusResult)


def historia(cl, cd, cm=None, tiempo=None):
    n = len(cl)
    return ForceHistory({"Time": list(tiempo or range(n)), "Cl": list(cl), "Cd": list(cd),
                         "Cm": list(cm or [0.0] * n)}, [])


def test_steady_flat_history_converges_with_window_mean():
    n = 6000
    v = evaluate(historia([0.9 + 1e-4 * math.sin(i) for i in range(n)],
                          [0.01 + 1e-6 * math.sin(i) for i in range(n)]))
    assert v.state == CONVERGIDO and v.usable
    assert v.window == 500 and v.n_rows == n
    assert v.cl == pytest.approx(0.9, abs=1e-4)
    assert v.cd_amp == pytest.approx(1e-6, rel=0.01)


def test_cd_still_falling_is_not_converged():
    """Asi termina hoy la corrida por defecto: 500 iteraciones y Cd bajando."""
    n = 500
    v = evaluate(historia([0.0] * n, [0.02 + 0.3 * math.exp(-i / 60) for i in range(n)]))
    assert v.state == NO_CONVERGIDO
    assert "Cd" in v.reason


def test_slow_drift_is_caught_even_if_the_range_looks_fine():
    n = 2000
    v = evaluate(historia([0.5] * n, [0.01 * (1 + 1.5e-5 * (n - i)) for i in range(n)]))
    assert v.cd_range_pct < 1.0
    assert v.state == NO_CONVERGIDO and "cambia" in v.reason


def test_slow_lift_drift_is_not_converged():
    """Cl sube 0.3 % por ventana: cabe en el rango, pero sumaria varios por ciento."""
    n = 6000
    v = evaluate(historia([1.0 + 6e-6 * i for i in range(n)], [0.012] * n))
    assert v.state == NO_CONVERGIDO and "Cl" in v.reason


def test_oscillating_steady_run_is_not_converged_and_reports_amplitude():
    n = 3000
    v = evaluate(historia([1.0 + 0.1 * math.sin(i / 7) for i in range(n)],
                          [0.02 + 1e-5 * math.sin(i / 7) for i in range(n)]))
    assert v.state == NO_CONVERGIDO and "Cl" in v.reason
    assert v.cl_amp == pytest.approx(0.1, rel=0.01)


def test_zero_lift_uses_absolute_tolerance():
    n = 1000
    v = evaluate(historia([1e-4 * math.sin(i) for i in range(n)], [0.008] * n))
    assert v.state == CONVERGIDO


@pytest.mark.parametrize("cl,cd", [
    ([800.0 * math.sin(i) for i in range(3000)], [2.0] * 3000),
    ([1.0] * 3000, [0.01 if i % 2 else -0.01 for i in range(3000)]),
    ([float("nan")] + [0.5] * 2999, [0.01] * 3000),
])
def test_divergence_is_never_reported_as_a_result(cl, cd):
    v = evaluate(historia(cl, cd))
    assert v.state == DIVERGIDO and not v.usable
    assert v.coefficients_text() == "sin coeficientes validos"


def test_startup_spike_does_not_condemn_a_converged_run():
    n = 3000
    cl = [40.0 if i < 50 else 0.9 for i in range(n)]
    cd = [-1.0 if i < 50 else 0.01 for i in range(n)]
    v = evaluate(historia(cl, cd))
    assert v.state == CONVERGIDO and v.max_abs_cl == 40.0


def test_blow_up_after_startup_that_calms_down_is_not_converged():
    """Hallado por OpenClaw: solo se miraba la ventana final."""
    n = 6000
    cl = [900.0 if 3000 <= i < 3050 else 0.9 for i in range(n)]
    v = evaluate(historia(cl, [0.01] * n))
    assert v.state == NO_CONVERGIDO and "dispararon" in v.reason


def test_transient_ramp_is_not_converged():
    tiempo = [i * 0.01 for i in range(4000)]
    v = evaluate(historia([0.5 + 0.02 * t for t in tiempo], [0.02] * 4000, tiempo=tiempo),
                 transient=True)
    assert v.state == NO_CONVERGIDO and "Cl" in v.reason


def test_pitching_moment_counts():
    n = 3000
    v = evaluate(historia([0.9] * n, [0.01] * n, [0.01 + 0.01 * math.sin(i) for i in range(n)]))
    assert v.state == NO_CONVERGIDO and "Cm" in v.reason


def test_return_code_and_crash():
    n = 1000
    h = historia([0.5] * n, [0.01] * n)
    assert evaluate(h, rc=143).state == NO_CONVERGIDO
    assert evaluate(h, rc=1).state == NO_CONVERGIDO
    assert evaluate(h, rc=136, log_tail="#1  Foam::sigFpe::sigHandler(int)").state == DIVERGIDO


def test_too_few_rows_cannot_be_judged():
    v = evaluate(historia([0.5] * 50, [0.01] * 50))
    assert v.state == NO_CONVERGIDO and "50" in v.reason


def test_transient_shedding_with_stable_mean_converges():
    tiempo = [i * 0.01 for i in range(4000)]
    v = evaluate(historia([1.2 + 0.3 * math.sin(4 * t) for t in tiempo],
                          [0.2 + 0.05 * math.sin(4 * t) for t in tiempo], tiempo=tiempo),
                 transient=True)
    assert v.state == CONVERGIDO
    assert v.cl == pytest.approx(1.2, abs=0.002)
    assert v.cl_amp == pytest.approx(0.3, rel=0.01)
    assert v.period == pytest.approx(2 * math.pi / 4, rel=0.01)


def test_case_without_forces_has_no_data(tmp_path):
    assert evaluate_case(str(tmp_path)).state == SIN_DATOS


# ---------------------------------------------------------------- y+

ALTURAS = (2e-3, 3e-3)


def _foam(clase, objeto, cuerpo):
    return ("/*---*\\\n| Version: 12 |\n\\*---*/\nFoamFile\n{\n    format ascii;\n"
            f"    class {clase};\n    note \"nPoints:12 nCells:2\";\n    object {objeto};\n}}\n"
            f"// * * //\n\n{cuerpo}\n// *** //\n")


def _caso_dos_celdas(tmp_path):
    """Dos hexaedros de cuerda 1 sobre una pared en y=0, con otra altura cada uno."""
    pm = tmp_path / "constant" / "polyMesh"
    pm.mkdir(parents=True)
    h1, h2 = ALTURAS
    puntos = []
    for z in (0.0, 0.1):
        puntos += [(0, 0, z), (1, 0, z), (2, 0, z), (0, h1, z), (1, (h1 + h2) / 2, z), (2, h2, z)]
    # Bordes verticales rectos: cada celda es un hexaedro; la pared son dos caras.
    caras = [
        (1, 7, 10, 4),               # interna entre celdas
        (0, 1, 7, 6), (1, 2, 8, 7),  # pared: normal hacia -y
        (3, 9, 10, 4), (4, 10, 11, 5),
        (0, 6, 9, 3), (2, 5, 11, 8),
        (0, 3, 4, 1), (1, 4, 5, 2), (6, 7, 10, 9), (7, 8, 11, 10),
    ]
    owner = [0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1]
    (pm / "points").write_text(_foam("vectorField", "points", "12\n(\n" + "\n".join(
        f"({x} {y} {z})" for x, y, z in puntos) + "\n)"))
    (pm / "faces").write_text(_foam("faceList", "faces", "11\n(\n" + "\n".join(
        "4(" + " ".join(map(str, c)) + ")" for c in caras) + "\n)"))
    (pm / "owner").write_text(_foam("labelList", "owner", "11\n(\n" + "\n".join(map(str, owner)) + "\n)"))
    (pm / "neighbour").write_text(_foam("labelList", "neighbour", "1\n(\n1\n)"))
    (pm / "boundary").write_text(_foam("polyBoundaryMesh", "boundary", """2
(
    airfoil
    {
        type            wall;
        nFaces          2;
        startFace       1;
    }
    resto
    {
        type            patch;
        nFaces          8;
        startFace       3;
    }
)"""))
    (tmp_path / "constant" / "transportProperties").write_text(
        "transportModel Newtonian;\nnu              [0 2 -1 0 0 0 0] 2.500000e-06;\n")
    cero = tmp_path / "0"
    cero.mkdir()
    (cero / "nut").write_text("boundaryField {\n airfoil { type nutLowReWallFunction; value uniform 0; }\n}\n")
    t = tmp_path / "6000"
    t.mkdir()
    (t / "wallShearStress").write_text(_foam("volVectorField", "wallShearStress", """
dimensions [0 2 -2 0 0 0 0];
internalField uniform (0 0 0);
boundaryField
{
    resto
    {
        type            calculated;
        value           uniform (0 0 0);
    }
    airfoil
    {
        type            calculated;
        value           nonuniform List<vector>
2
(
(0.04 0 0)
(0 -0.09 0)
)
;
    }
}"""))
    return str(tmp_path)


def test_first_cell_distance_is_half_the_height_at_the_centre(tmp_path):
    caso = _caso_dos_celdas(tmp_path)
    d = first_cell_distance(caso)
    h1, h2 = ALTURAS
    # Cada celda es un trapecio: su centroide queda algo por debajo de media altura.
    assert d[0] == pytest.approx((h1 + (h1 + h2) / 2) / 4, rel=0.03)
    assert d[1] == pytest.approx(((h1 + h2) / 2 + h2) / 4, rel=0.03)


def test_yplus_uses_real_friction(tmp_path):
    caso = _caso_dos_celdas(tmp_path)
    r = compute_yplus(caso)
    d = first_cell_distance(caso)
    assert r.nu == 2.5e-6 and r.n_faces == 2 and r.time == "6000"
    assert r.wall_condition == "nutLowReWallFunction"
    assert r.min == pytest.approx(d[0] * 0.2 / 2.5e-6)
    assert r.max == pytest.approx(d[1] * 0.3 / 2.5e-6)
    assert r.mean == pytest.approx((r.min + r.max) / 2)
    assert wall_condition(caso) == "nutLowReWallFunction"


def test_analysis_is_saved_next_to_the_case(tmp_path):
    caso = _caso_dos_celdas(tmp_path)
    fuerzas = tmp_path / "postProcessing" / "forceCoeffs" / "0"
    fuerzas.mkdir(parents=True)
    (fuerzas / "forceCoeffs.dat").write_text("# Time Cm Cd Cl Cl(f) Cl(r)\n" + "".join(
        f"{i} 0 0.01 0.5 0.25 0.25\n" for i in range(1000)))
    a = analyze_case(caso)
    assert a["verdict"]["state"] == CONVERGIDO
    assert a["yplus"]["n_faces"] == 2
    assert (tmp_path / "resultado.json").exists()


def test_analysis_survives_a_case_without_friction(tmp_path):
    a = analyze_case(str(tmp_path))
    assert a["verdict"]["state"] == SIN_DATOS
    assert a["yplus"] is None and "no disponible" in a["yplus_notice"]["text"]


def _yp(media, pared="nutLowReWallFunction"):
    return YPlusResult(media, media / 2, media * 2, 290, "6000", 2.5e-6, 1e-5, pared, 0.5)


@pytest.mark.parametrize("media,pared,nivel", [
    (0.8, "nutLowReWallFunction", "ok"),
    (2.46, "nutLowReWallFunction", "aviso"),
    (2.46, "nutkWallFunction", "aviso"),
    (12.0, "nutLowReWallFunction", "mal"),
    (12.0, "nutkWallFunction", "mal"),
    (60.0, "nutLowReWallFunction", "mal"),
    (60.0, "nutkWallFunction", "ok"),
    (400.0, "nutkWallFunction", "aviso"),
])
def test_mesh_regime_notice(media, pared, nivel):
    assert regime_notice(_yp(media, pared))[0] == nivel


def test_k_epsilon_on_a_wall_resolved_mesh_is_flagged():
    """Medido: k-e con y+ = 2 da Cd = 0.119 y el veredicto es CONVERGIDO."""
    yp = YPlusResult(2.0, 1.0, 3.0, 290, "6000", 2.5e-6, 1e-5, "nutLowReWallFunction", 0.5, "kEpsilon")
    assert regime_notice(yp)[0] == "mal"
    yp = YPlusResult(60.0, 30.0, 90.0, 290, "6000", 2.5e-6, 1e-4, "nutkWallFunction", 0.5, "kEpsilon")
    assert regime_notice(yp)[0] == "ok"


def test_first_cell_counts_the_centre_at_half_height():
    h = first_cell_for_yplus(1.0, 6e6)
    # y_P = h/2; u_tau/U = sqrt(cf/2) con cf = 0.026/Re^(1/7)
    cf = 0.026 / 6e6 ** (1 / 7)
    assert (h / 2) * 6e6 * math.sqrt(cf / 2) == pytest.approx(1.0)
    assert 7e-6 < h < 1e-5
    assert estimate_yplus(2 * h, 6e6) == pytest.approx(2.0)
