"""Rejilla C a .msh: la estela se funde y los contornos quedan bien clasificados."""

import json
import math
import os
from collections import Counter

import numpy as np
import pytest

from core.structured_mesh import import_plot3d, read_plot3d_2d, wake_points, write_cgrid_msh


def rejilla_c(n_estela=4, n_perfil=9, nj=5):
    """C sencilla: estela sobre y=0 y perfil como elipse fina."""
    x_estela = np.linspace(3.0, 1.0, n_estela)
    t = np.linspace(0.0, 2 * math.pi, n_perfil)
    x_perfil = 0.5 + 0.5 * np.cos(t)
    y_perfil = -0.05 * np.sin(t)
    x0 = np.concatenate([x_estela, x_perfil[1:-1], x_estela[::-1]])
    y0 = np.concatenate([0 * x_estela, y_perfil[1:-1], 0 * x_estela])
    ni = x0.size
    x = np.zeros((ni, nj))
    y = np.zeros((ni, nj))
    for j in range(nj):
        factor = j / (nj - 1)
        angulo = np.linspace(0.0, 2 * math.pi, ni)
        x[:, j] = (1 - factor) * x0 + factor * (0.5 + 10 * np.cos(angulo))
        y[:, j] = (1 - factor) * y0 + factor * (-10 * np.sin(angulo))
    return x, y


def leer_msh(ruta):
    texto = open(ruta).read().split("\n")
    i = texto.index("$PhysicalNames")
    nombres = {int(l.split()[1]): l.split()[2].strip('"') for l in texto[i + 2:i + 2 + int(texto[i + 1])]}
    i = texto.index("$Nodes")
    n_nodos = int(texto[i + 1])
    i = texto.index("$Elements")
    tipos = Counter()
    for l in texto[i + 2:i + 2 + int(texto[i + 1])]:
        v = l.split()
        tipos[(int(v[1]), nombres[int(v[3])])] += 1
    return n_nodos, tipos


def test_wake_nodes_are_counted():
    x, y = rejilla_c()
    assert wake_points(x, y) == 4


def test_grid_is_written_with_the_patches_the_case_expects(tmp_path):
    x, y = rejilla_c()
    ruta = str(tmp_path / "m.msh")
    info = write_cgrid_msh(ruta, x, y, 0.1)
    ni, nj = x.shape
    n_nodos, tipos = leer_msh(ruta)
    celdas = (ni - 1) * (nj - 1)
    assert info["celdas"] == celdas
    # Los nodos de la estela inferior se funden con los de la superior.
    assert n_nodos == 2 * (ni * nj - 4)
    assert tipos[(5, "fluid")] == celdas
    assert tipos[(3, "frontAndBack")] == 2 * celdas
    assert tipos[(3, "airfoil")] == ni - 2 * 4 + 1
    assert tipos[(3, "inlet")] == ni - 1
    assert tipos[(3, "outlet")] == 2 * (nj - 1)


def test_inverted_or_mixed_cells_are_rejected(tmp_path):
    x, y = rejilla_c()
    x[10, 2] = 50.0
    with pytest.raises(ValueError, match="invertidas"):
        write_cgrid_msh(str(tmp_path / "m.msh"), x, y)


def test_plot3d_format_is_read_in_fortran_order(tmp_path):
    ruta = tmp_path / "g.p2dfmt"
    ruta.write_text("1\n3 2\n0 1 2 10 11 12\n5 6 7 15 16 17\n")
    x, y = read_plot3d_2d(str(ruta))
    assert x.shape == (3, 2)
    assert x[1, 0] == 1 and x[0, 1] == 10 and y[2, 1] == 17


def test_plot3d_with_wrong_size_is_rejected(tmp_path):
    ruta = tmp_path / "g.p2dfmt"
    ruta.write_text("1\n3 2\n0 1 2\n")
    with pytest.raises(ValueError):
        read_plot3d_2d(str(ruta))


def test_import_leaves_mesh_information(tmp_path):
    x, y = rejilla_c()
    entrada = tmp_path / "g.p2dfmt"
    ni, nj = x.shape
    valores = list(x.flatten(order="F")) + list(y.flatten(order="F"))
    entrada.write_text(f"1\n{ni} {nj}\n" + " ".join(f"{v:.12g}" for v in valores) + "\n")
    salida = str(tmp_path / "m.msh")
    import_plot3d(str(entrada), salida)
    info = json.load(open(salida + ".info.json"))
    assert info["mallador"] == "importada de g.p2dfmt"
