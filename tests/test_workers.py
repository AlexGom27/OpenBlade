"""Lectura de bloques de un caso de OpenFOAM."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


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
