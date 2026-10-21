"""Tests del solver estructural 2D (FEM CST, tensión plana).

No requieren preCICE ni Docker: prueban sólo la parte FEM, comparando contra
soluciones analíticas conocidas.

El test de convergencia documenta el sesgo propio del elemento CST: es rígido
en flexión, así que la flecha se acerca por debajo. Se exige que el error
**decrezca con el refinamiento** y que con malla fina quede bajo el 5%.
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.fsi_solid import (SolidMaterial, assemble_stiffness, build_rect_mesh,
                            cst_stiffness, solve_displacement,
                            traction_to_nodal_forces)


# --------------------------------------------------------------------------
# Malla
# --------------------------------------------------------------------------
def test_mesh_node_and_element_counts():
    mesh = build_rect_mesh(1.0, 0.1, nx=4, ny=2)
    assert mesh.n_nodes == 5 * 3
    assert mesh.triangles.shape == (4 * 2 * 2, 3)
    assert mesh.n_dof == 2 * mesh.n_nodes


def test_mesh_fixed_edge_is_x_zero():
    mesh = build_rect_mesh(1.0, 0.1, nx=4, ny=2)
    assert np.allclose(mesh.nodes[mesh.fixed_nodes][:, 0], 0.0)


def test_mesh_interface_edge_selection():
    for edge, axis, value in (("top", 1, 0.1), ("bottom", 1, 0.0), ("right", 0, 1.0)):
        mesh = build_rect_mesh(1.0, 0.1, nx=4, ny=2, interface_edge=edge)
        assert np.allclose(mesh.nodes[mesh.interface_nodes][:, axis], value)


def test_mesh_rejects_bad_edge():
    with pytest.raises(ValueError):
        build_rect_mesh(1.0, 0.1, 2, 2, interface_edge="left")


# --------------------------------------------------------------------------
# Elemento
# --------------------------------------------------------------------------
def test_cst_stiffness_is_symmetric():
    mat = SolidMaterial()
    mesh = build_rect_mesh(1.0, 0.1, 2, 1)
    ke = cst_stiffness(mesh.nodes, mesh.triangles[0], mat)
    assert np.allclose(ke, ke.T)


def test_cst_stiffness_rigid_body_modes_are_null():
    """Traslación y rotación rígidas no deben generar fuerza interna."""
    mat = SolidMaterial()
    mesh = build_rect_mesh(1.0, 0.1, 3, 2)
    tri = mesh.triangles[0]
    ke = cst_stiffness(mesh.nodes, tri, mat)
    p = mesh.nodes[tri]
    centre = p.mean(axis=0)

    tx = np.tile([1.0, 0.0], 3)
    ty = np.tile([0.0, 1.0], 3)
    # rotación infinitesimal: (-y, x)
    rot = np.concatenate([[-p[i][1] + centre[1], p[i][0] - centre[0]] for i in range(3)])

    for mode in (tx, ty, rot):
        assert np.allclose(ke @ mode, 0.0, atol=1e-6 * np.abs(ke).max())


def test_global_stiffness_is_spd_on_free_dofs():
    mat = SolidMaterial()
    mesh = build_rect_mesh(1.0, 0.1, 4, 2)
    K = assemble_stiffness(mesh, mat)
    assert np.allclose(K, K.T)

    from core.fsi_solid import apply_fixed
    Kred, _ = apply_fixed(K, np.zeros(mesh.n_dof), mesh.fixed_nodes)
    eigvals = np.linalg.eigvalsh(Kred)
    assert eigvals.min() > 0, "la matriz reducida debe ser definida positiva"


# --------------------------------------------------------------------------
# Carga
# --------------------------------------------------------------------------
def test_traction_forces_sum_to_applied_resultant():
    """La suma de fuerzas nodales debe igualar tracción × área del borde."""
    mat = SolidMaterial(thickness=0.01)
    mesh = build_rect_mesh(1.0, 0.2, 10, 2, interface_edge="right")
    p = 500.0
    trac = np.tile([0.0, p], (len(mesh.interface_nodes), 1))
    f = traction_to_nodal_forces(mesh, trac, mat)

    fy = f[1::2].sum()
    expected = p * 0.2 * 0.01  # tracción × altura × espesor
    assert fy == pytest.approx(expected, rel=1e-12)


def test_traction_shape_is_checked():
    mat = SolidMaterial()
    mesh = build_rect_mesh(1.0, 0.1, 4, 2)
    with pytest.raises(ValueError):
        traction_to_nodal_forces(mesh, np.zeros((3, 2)), mat)


# --------------------------------------------------------------------------
# Validación contra solución analítica
# --------------------------------------------------------------------------
def _cantilever_tip_deflection(nx, ny, length=1.0, height=0.1, pressure=1000.0):
    """Viga en voladizo con carga distribuida en el extremo libre."""
    mat = SolidMaterial(young=200e9, poisson=0.3, thickness=0.01)
    mesh = build_rect_mesh(length, height, nx, ny, interface_edge="right")
    K = assemble_stiffness(mesh, mat)
    trac = np.tile([0.0, pressure], (len(mesh.interface_nodes), 1))
    f = traction_to_nodal_forces(mesh, trac, mat)
    u = solve_displacement(K, f, mesh.fixed_nodes)
    tip = int(mesh.interface_nodes[-1])
    return float(u[2 * tip + 1])


def _euler_bernoulli(length=1.0, height=0.1, pressure=1000.0):
    e, th = 200e9, 0.01
    total = pressure * height * th
    inertia = th * height ** 3 / 12.0
    return total * length ** 3 / (3.0 * e * inertia)


def test_cantilever_matches_euler_bernoulli():
    exact = _euler_bernoulli()
    err = lambda nx, ny: abs(_cantilever_tip_deflection(nx, ny) - exact) / exact

    coarse, mid, fine = err(20, 4), err(40, 8), err(80, 16)

    # CST subestima la flecha, pero debe converger al refinar.
    assert fine < mid < coarse
    assert fine < 0.05, f"error con malla fina demasiado alto: {fine:.3%}"


def test_zero_load_gives_zero_displacement():
    mat = SolidMaterial()
    mesh = build_rect_mesh(1.0, 0.1, 6, 3)
    K = assemble_stiffness(mesh, mat)
    u = solve_displacement(K, np.zeros(mesh.n_dof), mesh.fixed_nodes)
    assert np.allclose(u, 0.0)


def test_uniform_extension_matches_hooke():
    """Tracción axial uniforme: u = sigma*L/E en el extremo libre."""
    length, height = 1.0, 0.1
    e, th = 200e9, 0.01
    sigma = 1.0e6
    mat = SolidMaterial(young=e, poisson=0.3, thickness=th)

    mesh = build_rect_mesh(length, height, 20, 4, interface_edge="right")
    K = assemble_stiffness(mesh, mat)
    trac = np.tile([sigma, 0.0], (len(mesh.interface_nodes), 1))
    f = traction_to_nodal_forces(mesh, trac, mat)
    u = solve_displacement(K, f, mesh.fixed_nodes)

    tip = int(mesh.interface_nodes[-1])
    ux = u[2 * tip]
    expected = sigma * length / e

    # El confinamiento lateral (poisson) introduce una corrección pequeña.
    assert ux == pytest.approx(expected, rel=0.05)
