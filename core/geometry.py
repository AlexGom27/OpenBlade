import numpy as np
import gmsh
import os
from typing import Tuple, Optional

class NacaGeometry:
    def __init__(self, naca_code: str = "0012", chord: float = 1.0, aoa: float = 0.0, custom_profile_path: Optional[str] = None) -> None:
        self.naca_code = str(naca_code)
        self.chord = float(chord)
        self.aoa = float(aoa)
        self.custom_profile_path = custom_profile_path
        self.z_thickness = 0.05

    def get_points(self, n_points: int = 150) -> Tuple[np.ndarray, np.ndarray]:
        if self.custom_profile_path and os.path.exists(self.custom_profile_path):
            data = np.loadtxt(self.custom_profile_path)
            x, y = data[:, 0], data[:, 1]
            rad = np.radians(-self.aoa)
            return x * np.cos(rad) - y * np.sin(rad), x * np.sin(rad) + y * np.cos(rad)
        else:
            if len(self.naca_code) != 4 or not self.naca_code.isdigit():
                raise ValueError(
                    "Falla de Validación: el código NACA debe tener exactamente 4 dígitos numéricos "
                    f"(recibido: '{self.naca_code}')"
                )
            m, p, t = int(self.naca_code[0])/100.0, int(self.naca_code[1])/10.0, int(self.naca_code[2:])/100.0
            beta = np.linspace(0, np.pi, n_points)
            x = self.chord * (0.5 * (1 - np.cos(beta)))
            yt = 5 * t * self.chord * (0.2969 * np.sqrt(x / self.chord) - 0.1260 * (x / self.chord) - 0.3516 * (x / self.chord)**2 + 0.2843 * (x / self.chord)**3 - 0.1036 * (x / self.chord)**4)
            yc = np.zeros_like(x)
            if p > 0:
                for i in range(n_points):
                    xc = x[i] / self.chord
                    if xc <= p: yc[i] = self.chord * (m / p**2) * (2 * p * xc - xc**2)
                    else: yc[i] = self.chord * (m / (1 - p)**2) * ((1 - 2 * p) + 2 * p * xc - xc**2)
            
            xu, yu = x, yc + yt
            xl, yl = x, yc - yt
            # Contorno cerrado SIN punto duplicado.
            #
            # `xu[::-1]` empieza por el borde de salida (x=1) y `xl[1:]` termina
            # también en el borde de salida. Al concatenar, el último punto
            # repetía el primero. `addSpline` no admite puntos coincidentes y
            # OCC aborta con "Could not create spline".
            #
            # Se recorta el último punto: el borde de salida queda representado
            # una sola vez y `build_geometry` cierra el contorno con una recta.
            x_rot = np.concatenate([xu[::-1], xl[1:-1]])
            y_rot = np.concatenate([yu[::-1], yl[1:-1]])
            
            # Rotación sobre el centro aerodinámico (25% de la cuerda)
            rad = np.radians(-self.aoa)
            cx, cy = 0.25 * self.chord, 0.0
            
            x_final = (x_rot - cx) * np.cos(rad) - (y_rot - cy) * np.sin(rad) + cx
            y_final = (x_rot - cx) * np.sin(rad) + (y_rot - cy) * np.cos(rad) + cy
            
            return x_final, y_final

    def build_geometry(self, mesh_extrusion: bool = False, preview: bool = False) -> None:
        """Genera la geometría con un hueco garantizado usando motor OCC."""
        factory = gmsh.model.occ
        
        # 1. Crear el Túnel (Fluido) como un rectángulo grande
        if preview:
            R, x_max = 1.0 * self.chord, 2.0 * self.chord
        else:
            R, x_max = 10 * self.chord, 20 * self.chord
        # Simplificamos el túnel a un bloque para que el hueco sea obvio
        tunnel_surf = factory.addRectangle(-R, -R, 0, x_max + R, 2*R)
        
        # 2. Crear el Perfil
        x_pts, y_pts = self.get_points(n_points=100)
        foil_pts = [factory.addPoint(xi, yi, 0.0) for xi, yi in zip(x_pts, y_pts)]
        foil_loop = factory.addCurveLoop([factory.addSpline(foil_pts), factory.addLine(foil_pts[-1], foil_pts[0])])
        foil_surf = factory.addPlaneSurface([foil_loop])
        
        # 3. RESTA BOOLEANA (Garantiza el hueco)
        res, _ = factory.cut([(2, tunnel_surf)], [(2, foil_surf)])
        self.fluid_surf = res[0][1]
        
        factory.synchronize()
        if mesh_extrusion:
            factory.extrude([(2, self.fluid_surf)], 0, 0, self.z_thickness, [1], [1.0], True)
            factory.synchronize()
