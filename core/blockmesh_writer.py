import os
import numpy as np
from core.geometry import NacaGeometry

class BlockMeshGenerator:
    def __init__(self, case_dir: str, naca_code: str, chord: float, aoa: float) -> None:
        self.case_dir = case_dir
        self.naca_code = naca_code
        self.chord = chord
        self.aoa = aoa
        self.dict_path = os.path.join(self.case_dir, "system", "blockMeshDict")

    def write_dict(self, radius: float = 10.0) -> None:
        """
        Crea un blockMeshDict sintácticamente válido para OpenFOAM.
        Genera un dominio rectangular simple (Inlet, Outlet, Walls).
        NOTA: Para mallas de alta fidelidad sobre el perfil, usar el motor de Gmsh.
        Este generador es para simulaciones de caja negra rápidas.
        """
        z1, z2 = 0, 0.05
        x_min, x_max = -radius, radius + self.chord
        y_min, y_max = -radius, radius

        content = f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      blockMeshDict;
}}

vertices
(
    ({x_min} {y_min} {z1})  // 0
    ({x_max} {y_min} {z1})  // 1
    ({x_max} {y_max} {z1})  // 2
    ({x_min} {y_max} {z1})  // 3
    ({x_min} {y_min} {z2})  // 4
    ({x_max} {y_min} {z2})  // 5
    ({x_max} {y_max} {z2})  // 6
    ({x_min} {y_max} {z2})  // 7
);

blocks
(
    hex (0 1 2 3 4 5 6 7) (50 40 1) simpleGrading (1 1 1)
);

edges
(
);

boundary
(
    inlet
    {{
        type patch;
        faces
        (
            (0 3 7 4)
        );
    }}
    outlet
    {{
        type patch;
        faces
        (
            (1 5 6 2)
        );
    }}
    walls_TB
    {{
        type patch;
        faces
        (
            (0 4 5 1)
            (3 2 6 7)
        );
    }}
    frontAndBack
    {{
        type empty;
        faces
        (
            (0 1 2 3)
            (4 7 6 5)
        );
    }}
);

mergePatchPairs
(
);
"""
        os.makedirs(os.path.dirname(self.dict_path), exist_ok=True)
        with open(self.dict_path, "w") as f:
            f.write(content)
