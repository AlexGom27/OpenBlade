import gmsh
import math
from gmshairfoil2d.airfoil_func import four_digit_naca_airfoil
from gmshairfoil2d.geometry_def import AirfoilSpline, CType

gmsh.initialize()
cloud_points = four_digit_naca_airfoil("0012")
airfoil = AirfoilSpline(cloud_points, 0.1, name="airfoil")
mesh = CType(airfoil, 1.0, 5.0, 0.1, 0.01, 1.1, 0.0)

print("Attributes of mesh object:")
for attr in dir(mesh):
    if not attr.startswith("__"):
        val = getattr(mesh, attr)
        print(f"- {attr}: {type(val)}")

gmsh.finalize()
