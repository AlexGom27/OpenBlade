"""Pruebas del parseo de stdout del solver (regresión: líneas partidas)."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gui.workers import SimWorker


class _SolverStub:
    """Solo satisface la firma de SimWorker; no se usa en estas pruebas."""


def _make_worker():
    return SimWorker(_SolverStub(), {}, "dummy.msh")


def test_partial_lines_are_buffered_and_parsed():
    w = _make_worker()
    residual, forces = [], []
    w.residual_data.connect(lambda f, v, t: residual.append((f, v, t)))
    w.force_data.connect(lambda n, v: forces.append((n, v)))

    # El proceso escribe una línea en dos bloques (caso real en macOS)
    w.consume_text("RESIDUAL_DATA|p|1.2e-")
    assert residual == []
    w.consume_text("03|7\n")

    assert residual == [("p", 1.2e-3, 7.0)]


def test_multiple_lines_in_one_block():
    w = _make_worker()
    residual = []
    w.residual_data.connect(lambda f, v, t: residual.append((f, v, t)))

    w.consume_text("RESIDUAL_DATA|Ux|0.1|1\nRESIDUAL_DATA|p|0.2|1\n")

    assert residual == [("Ux", 0.1, 1.0), ("p", 0.2, 1.0)]


def test_force_data_and_noise_filtering():
    w = _make_worker()
    forces, logs = [], []
    w.force_data.connect(lambda n, v: forces.append((n, v)))
    w.log_msg.connect(logs.append)

    w.consume_text("FORCE_DATA|Cl|0.421\nlinea irrelevante\nTime = 12\n")

    assert forces == [("Cl", "0.421")]
    assert logs == ["Time = 12"]


def test_find_block_in_nested_multiblock():
    """OpenFOAMReader anida los patches en un bloque 'boundary'."""
    import pyvista as pv
    from core.postprocessing import PostProcessor

    airfoil = pv.PolyData([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    airfoil.point_data["p"] = [1.0, 2.0]
    boundary = pv.MultiBlock({"airfoil": airfoil, "inlet": pv.PolyData()})
    root = pv.MultiBlock({"internalMesh": pv.PolyData(), "boundary": boundary})

    found = PostProcessor._find_block(root, "airfoil")

    assert found is not None
    assert found.n_points == 2
    assert found.point_data["p"].tolist() == [1.0, 2.0]
