"""El GCI con casos cuya respuesta se conoce."""

import pytest

from core.gci import grid_study, study_from_levels


def test_second_order_sequence_recovers_order_and_exact_value():
    """f = 1 + 0.01 h^2 con h = 1, 2, 4: orden 2 y valor exacto 1."""
    g = grid_study(1.01, 1.04, 1.16)
    assert g.convergencia == "monotona"
    assert g.orden == pytest.approx(2.0)
    assert g.extrapolado == pytest.approx(1.0)
    # 1.25 * 0.03 / 3 / 1.01
    assert g.gci_fina == pytest.approx(1.25 * 0.03 / 3 / 1.01)
    assert g.banda == pytest.approx(0.0125)


def test_first_order_sequence():
    g = grid_study(1.1, 1.2, 1.4)
    assert g.orden == pytest.approx(1.0)
    assert g.extrapolado == pytest.approx(1.0)


def test_implausible_order_is_bounded():
    """Un salto mucho menor en el nivel fino no autoriza a creer en orden 5."""
    g = grid_study(1.0, 1.0001, 1.2)
    assert g.orden == 2.0


def test_very_low_order_is_not_asymptotic_and_does_not_narrow_the_band():
    """Hallado por OpenClaw: recortar el orden a 0.5 daba una banda varias veces menor."""
    g = grid_study(1.0, 1.1, 1.11)
    assert g.convergencia == "no asintotica" and g.orden is None and g.extrapolado is None
    assert g.banda == pytest.approx(3 * 0.1)


def test_oscillating_sequence_has_no_order_and_a_conservative_band():
    g = grid_study(1.00, 1.02, 0.99)
    assert g.convergencia == "oscilatoria"
    assert g.orden is None and g.extrapolado is None
    assert g.banda == pytest.approx(3 * 0.03)


def test_unchanged_values_have_zero_band():
    g = grid_study(0.5, 0.5, 0.5)
    assert g.convergencia == "sin cambio" and g.gci_fina == 0.0


def test_near_zero_coefficient_does_not_divide_by_zero():
    g = grid_study(0.0, 0.001, 0.003)
    assert g.banda > 0 and g.gci_fina < float("inf")


def test_levels_go_from_coarse_to_fine():
    assert study_from_levels([1.16, 1.04, 1.01]).extrapolado == pytest.approx(1.0)
    with pytest.raises(ValueError):
        study_from_levels([1.0, 1.1])


def test_band_for_a_result_on_the_medium_mesh_uses_the_two_coarser_levels():
    g = grid_study(1.01, 1.04, 1.16)
    assert g.banda_media == pytest.approx(1.25 * 0.12 / 3)
    assert g.gci_media == pytest.approx(g.banda_media / 1.04)
    # El error real de la media es 0.04: la banda lo cubre.
    assert g.banda_media >= abs(1.04 - g.extrapolado)
