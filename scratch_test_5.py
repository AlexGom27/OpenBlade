import gmsh
import numpy as np

gmsh.initialize()
factory = gmsh.model.occ

chord = 1.0
aoa = 12.0
naca_code = "2412"
n_points = 100

m, p, t = int(naca_code[0])/100.0, int(naca_code[1])/10.0, int(naca_code[2:])/100.0
beta = np.linspace(0, np.pi, n_points)
x = chord * (0.5 * (1 - np.cos(beta)))
yt = 5 * t * chord * (0.2969 * np.sqrt(x / chord) - 0.1260 * (x / chord) - 0.3516 * (x / chord)**2 + 0.2843 * (x / chord)**3 - 0.1015 * (x / chord)**4)
yc = np.zeros_like(x)
if p > 0:
    for i in range(n_points):
        xc = x[i] / chord
        if xc <= p: yc[i] = chord * (m / p**2) * (2 * p * xc - xc**2)
        else: yc[i] = chord * (m / (1 - p)**2) * ((1 - 2 * p) + 2 * p * xc - xc**2)

xu, yu = x, yc + yt
xl, yl = x, yc - yt
x_rot, y_rot = np.concatenate([xu[::-1], xl[1:]]), np.concatenate([yu[::-1], yl[1:]])
rad = np.radians(-aoa)
x_rot, y_rot = x_rot*np.cos(rad) - y_rot*np.sin(rad), x_rot*np.sin(rad) + y_rot*np.cos(rad)

foil_pts = [factory.addPoint(xi, yi, 0.0) for xi, yi in zip(x_rot, y_rot)]
try:
    s1 = factory.addSpline(foil_pts)
    l1 = factory.addLine(foil_pts[-1], foil_pts[0])
    foil_loop = factory.addCurveLoop([s1, l1])
    foil_surf = factory.addPlaneSurface([foil_loop])
    print("Foil surface:", foil_surf)
except Exception as e:
    print("Error foil:", e)

R, x_max = 10 * chord, 20 * chord
tunnel_surf = factory.addRectangle(-R, -R, 0, x_max + R, 2*R)

try:
    res, err = factory.cut([(2, tunnel_surf)], [(2, foil_surf)])
    gmsh.model.occ.synchronize()
    print("Result of cut:", res)
except Exception as e:
    print("Error cut:", e)

gmsh.finalize()
