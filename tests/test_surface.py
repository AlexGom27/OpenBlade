import numpy as np

from core.surface import SurfaceData, friction_drag, surface_text, transition_location


def _placa(cf_sup, cf_inf=None, n=200):
    x = np.linspace(0.0, 1.0, n)
    cf_inf = cf_sup if cf_inf is None else cf_inf
    xs = np.concatenate([x, x])
    cf = np.concatenate([cf_sup(x), cf_inf(x)])
    upper = np.concatenate([np.ones(n, bool), np.zeros(n, bool)])
    tau = np.column_stack([-cf, np.zeros_like(cf)])  # pared sobre el fluido: contra la corriente
    area = np.full(2 * n, 1.0 / n)
    return SurfaceData(xs, np.zeros_like(xs), np.zeros_like(xs), cf, upper, tau, area)


def _laminar_turbulenta(x_tr):
    def cf(x):
        lam = 0.664 / np.sqrt(1e6 * np.maximum(x, 1e-3))
        turb = 0.0576 / (1e6 * np.maximum(x, 1e-3)) ** 0.2
        return np.where(x < x_tr, lam, turb)
    return cf


def test_transicion_en_su_sitio():
    t = transition_location(_placa(_laminar_turbulenta(0.4)))
    assert abs(t["subida"] - 0.4) < 0.01 and abs(t["inicio"] - 0.4) < 0.01


def test_turbulenta_desde_el_borde_no_tiene_transicion():
    s = _placa(lambda x: 0.0576 / (1e6 * np.maximum(x, 1e-3)) ** 0.2)
    assert transition_location(s) is None and transition_location(s, False) is None


def test_cada_cara_por_separado():
    s = _placa(_laminar_turbulenta(0.3), _laminar_turbulenta(0.6))
    assert abs(transition_location(s, True)["subida"] - 0.3) < 0.01
    assert abs(transition_location(s, False)["subida"] - 0.6) < 0.01


def test_friccion_de_una_placa_a_cero_grados():
    s = _placa(lambda x: np.full_like(x, 0.004))
    assert abs(friction_drag(s, 0.0) - 0.008) < 1e-9  # dos caras
    assert abs(friction_drag(s, 60.0) - 0.004) < 1e-9


def test_texto():
    r = {"cd_friccion": 0.004, "transicion": {"extrados": {"inicio": 0.44, "subida": 0.45}, "intrados": None}}
    t = surface_text(r, 0.005)
    assert "80 % del total" in t and "0.440" in t and "sin transición clara en el intradós" in t
    assert surface_text(None, 0.005) == ""
