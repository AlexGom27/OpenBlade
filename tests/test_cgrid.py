"""La malla C propia: sin celdas invertidas, ortogonal y con niveles anidados."""

import json
import math

import numpy as np
import pytest

from core.cgrid import (CELDAS_ESTELA, CARAS_POR_LADO, build_mesh, first_cell_at_level, first_cell_of,
                        generate_cgrid, naca4, read_contour, vinokur)
from core.yplus import first_cell_for_yplus


def calidad(x, y):
    """No ortogonalidad maxima y area minima, con el centroide de cada celda."""
    v = [(x[:-1, :-1], y[:-1, :-1]), (x[1:, :-1], y[1:, :-1]), (x[1:, 1:], y[1:, 1:]), (x[:-1, 1:], y[:-1, 1:])]
    a, mx, my = 0, 0, 0
    for k in range(4):
        (xa, ya), (xb, yb) = v[k], v[(k + 1) % 4]
        c = xa * yb - xb * ya
        a, mx, my = a + c, mx + (xa + xb) * c, my + (ya + yb) * c
    a = a / 2
    cx, cy = mx / (6 * a), my / (6 * a)

    def angulo(ex, ey, dx, dy):
        return np.degrees(np.arccos(np.clip(np.abs(ey * dx - ex * dy) / np.hypot(ex, ey) / np.hypot(dx, dy), 0, 1)))

    ai = angulo(x[1:-1, 1:] - x[1:-1, :-1], y[1:-1, 1:] - y[1:-1, :-1], cx[1:, :] - cx[:-1, :], cy[1:, :] - cy[:-1, :])
    aj = angulo(x[1:, 1:-1] - x[:-1, 1:-1], y[1:, 1:-1] - y[:-1, 1:-1], cx[:, 1:] - cx[:, :-1], cy[:, 1:] - cy[:, :-1])
    return a, max(ai.max(), aj.max())


H = first_cell_for_yplus(0.5, 6e6)


@pytest.mark.parametrize("codigo,nivel,radio,tope", [
    ("0012", 0, 50.0, 70.0), ("0012", 1, 500.0, 60.0), ("0012", 2, 500.0, 35.0), ("0012", 3, 500.0, 35.0),
    ("0012", 2, 50.0, 35.0), ("0018", 2, 100.0, 35.0), ("4412", 2, 100.0, 35.0), ("6412", 2, 100.0, 40.0),
])
def test_no_inverted_cells_and_low_non_orthogonality(codigo, nivel, radio, tope):
    x, y = generate_cgrid(naca4(codigo), H, nivel, radio)
    area, maximo = calidad(x, y)
    assert np.all(area > 0) or np.all(area < 0)
    assert maximo < tope


def test_levels_are_nested_exactly():
    """El GCI necesita un factor de refinamiento exacto."""
    fino = generate_cgrid(naca4("0012"), H, 3, 500.0)
    medio = generate_cgrid(naca4("0012"), H, 2, 500.0)
    assert medio[0].shape == (449, 129) and fino[0].shape == (897, 257)
    assert np.allclose(medio[0], fino[0][::2, ::2], atol=1e-6)
    assert np.allclose(medio[1], fino[1][::2, ::2], atol=1e-6)


def test_wall_points_are_on_the_profile_and_wake_cut_closes():
    contorno = naca4("0012")
    x, y = generate_cgrid(contorno, H, 2, 500.0)
    n = CELDAS_ESTELA
    # La estela inferior y la superior coinciden en j=0.
    assert np.allclose(x[:n + 1, 0], x[::-1, 0][:n + 1], atol=1e-9)
    assert np.allclose(y[:n + 1, 0], 0.0, atol=1e-9)
    # El perfil: espesor del 12 % y cuerda 1.
    pared_x, pared_y = x[n:-n, 0], y[n:-n, 0]
    assert pared_x.min() == pytest.approx(0.0, abs=1e-6) and pared_x.max() == pytest.approx(1.0, abs=1e-6)
    assert pared_y.max() - pared_y.min() == pytest.approx(0.12, abs=2e-4)
    assert pared_y.size == 2 * CARAS_POR_LADO + 1


def test_lines_leave_the_wall_normal_to_it():
    x, y = generate_cgrid(naca4("0012"), H, 2, 500.0)
    for i in (150, 224, 300):
        tx, ty = x[i + 1, 0] - x[i - 1, 0], y[i + 1, 0] - y[i - 1, 0]
        nx, ny = x[i, 1] - x[i, 0], y[i, 1] - y[i, 0]
        assert abs(tx * nx + ty * ny) / math.hypot(tx, ty) / math.hypot(nx, ny) < 0.01


def test_first_cell_is_the_requested_one_and_doubles_per_level():
    x, y = generate_cgrid(naca4("0012"), H, 2, 500.0)
    primera = np.hypot(x[224, 1] - x[224, 0], y[224, 1] - y[224, 0])
    assert primera == pytest.approx(H, rel=1e-3)
    x1, y1 = generate_cgrid(naca4("0012"), H, 1, 500.0)
    assert np.hypot(x1[112, 1] - x1[112, 0], y1[112, 1] - y1[112, 0]) > 1.9 * H


def test_outer_boundary_is_where_it_was_asked():
    x, y = generate_cgrid(naca4("0012"), H, 2, 100.0)
    assert x.min() == pytest.approx(-99.5, abs=1e-3)
    assert x.max() == pytest.approx(101.0, abs=1e-6)
    assert abs(y).max() == pytest.approx(100.0, abs=1e-6)
    # La salida es vertical
    assert np.allclose(x[0, :], 101.0) and np.allclose(x[-1, :], 101.0)


def test_wake_cells_do_not_reach_absurd_aspect_ratios():
    x, y = generate_cgrid(naca4("0012"), H, 2, 500.0)
    largo = np.hypot(np.diff(x, axis=0)[:, :-1], np.diff(y, axis=0)[:, :-1])
    alto = np.hypot(np.diff(x, axis=1)[:-1, :], np.diff(y, axis=1)[:-1, :])
    assert (largo / alto).max() < 6000
    assert (alto / largo).max() < 40


def test_distribution_hits_the_requested_end_spacings():
    xi = np.linspace(0.0, 1.0, 129)
    t = vinokur(xi, 2e-4, 2e-3, 128)
    assert t[0] == 0.0 and t[-1] == pytest.approx(1.0)
    assert t[1] - t[0] == pytest.approx(2e-4, rel=0.2)
    assert t[-1] - t[-2] == pytest.approx(2e-3, rel=0.2)
    assert np.all(np.diff(t) > 0)


def _archivo_selig(ruta, codigo="2412", abrir=0.0):
    xu, yu, xl, yl = naca4(codigo, 121)
    with open(ruta, "w") as f:
        f.write("perfil de prueba\n")
        for a, b in zip(xu[::-1], yu[::-1] + abrir * xu[::-1]):
            f.write(f"{a:.6f} {b:.6f}\n")
        for a, b in zip(xl[1:], yl[1:] - abrir * xl[1:]):
            f.write(f"{a:.6f} {b:.6f}\n")


def test_custom_profile_file_is_meshed_and_a_blunt_edge_is_closed(tmp_path):
    ruta = tmp_path / "perfil.dat"
    _archivo_selig(ruta, abrir=0.002)
    contorno = read_contour(str(ruta))
    assert contorno[1][-1] == pytest.approx(contorno[3][-1], abs=1e-9)
    assert contorno[1].max() > 0.0 > contorno[3].min()
    x, y = generate_cgrid(contorno, H, 2, 100.0)
    area, maximo = calidad(x, y)
    assert (np.all(area > 0) or np.all(area < 0)) and maximo < 55.0


def test_mesh_file_scales_with_chord_and_keeps_depth_ratio(tmp_path):
    p = {"naca": "0012", "chord": 2.0, "grid_level": 0, "farfield": 50.0, "reynolds": 6e6, "depth": 0.1}
    salida = str(tmp_path / "m.msh")
    info = build_mesh(p, salida)
    assert info["celdas"] == (113 - 1) * (33 - 1) and "nivel 0" in info["mallador"]
    assert json.load(open(salida + ".info.json"))["caras_perfil"] == 64
    lineas = open(salida).read().split("\n")
    i = lineas.index("$Nodes")
    nodos = np.array([l.split()[1:] for l in lineas[i + 2:i + 2 + int(lineas[i + 1])]], float)
    assert nodos[:, 2].max() == pytest.approx(0.2)
    assert nodos[:, 1].max() == pytest.approx(100.0)
    assert first_cell_at_level(p) == pytest.approx(4 * first_cell_of(p))


def test_selig_and_lednicer_files_give_the_same_profile(tmp_path):
    xu, yu, xl, yl = naca4("2412", 81)
    selig = tmp_path / "s.dat"
    selig.write_text("perfil\n" + "".join(f"{a:.6f} {b:.6f}\n" for a, b in zip(xu[::-1], yu[::-1]))
                     + "".join(f"{a:.6f} {b:.6f}\n" for a, b in zip(xl[1:], yl[1:])))
    lednicer = tmp_path / "l.dat"
    lednicer.write_text(f"perfil\n81. 81.\n\n" + "".join(f"{a:.6f} {b:.6f}\n" for a, b in zip(xu, yu))
                        + "\n" + "".join(f"{a:.6f} {b:.6f}\n" for a, b in zip(xl, yl)))
    s, l = read_contour(str(selig)), read_contour(str(lednicer))
    for a, b in zip(s, l):
        assert np.allclose(a, b, atol=1e-5)
    # Extrados arriba, cuerda 1
    assert s[1].max() > s[3].max() and s[0][-1] == pytest.approx(1.0)
