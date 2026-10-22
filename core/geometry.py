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

    # --- Dimensionamiento del volumen de control ---------------------------
    #
    # Criterio de la literatura
    # ------------------------
    # NASA Turbulence Modeling Resource, "2D NACA 0012 Airfoil Validation —
    # Effect of Farfield Boundary" (tmbwg.github.io/turbmodels/
    # naca0012_val_ffeffect.html):
    #
    #   "A farfield extent of 500 c is far enough for the finite boundary to
    #    have only a minimal influence on the solution. With smaller farfield
    #    boundary extents such as 30 c, the boundary influence on the forces
    #    is greater (especially for drag) unless one employs a 'farfield point
    #    vortex' boundary condition correction."
    #
    #   Thomas & Salas, AIAA Journal 24(7):1074-1080, 1986,
    #   doi:10.2514/3.9394  (corrección de vórtice lejano).
    #
    # Consecuencias prácticas:
    #   * 500c libres de bloqueo pero inalcanzables con malla estructurada
    #     (el C-Grid genera celdas de aspect ratio >1e5, ver PLAN_FSI.md).
    #   * 30c sesga el Cd salvo que se aplique la corrección PV.
    #   * 50c es el compromiso validado en este proyecto: error de Cd < 2%
    #     en el NACA 0012 a Re=6e6 (CAMPANA_VALIDACION.md).
    #
    # La estela, además, necesita longitud propia: para visualizarla y para
    # que la depresión de la estela se disipe antes del contorno. Se toma
    # 6c aguas arriba, 12c aguas abajo y 8c a los lados para la previsualización,
    # y los valores de producción configurables para el cálculo real.

    # Dominio por defecto, en cuerdas. Se puede sobrescribir con
    # `self.domain` (dict) desde la GUI.
    DOMAIN_DEFAULT = {
        "upstream": 6.0,    # aguas arriba del borde de ataque
        "downstream": 12.0,  # aguas abajo del borde de salida (estela)
        "lateral": 8.0,     # por arriba y por abajo
    }

    def __init_domain(self):
        d = getattr(self, "domain", None) or self.DOMAIN_DEFAULT
        return (float(d["upstream"]), float(d["downstream"]), float(d["lateral"]))

    def build_geometry(self, mesh_extrusion: bool = False, preview: bool = False) -> None:
        """Genera la geometría con un hueco garantizado usando motor OCC.

        El volumen de control se dimensiona según el criterio del NASA TMR
        (ver comentario de clase): la estela necesita longitud suficiente para
        que el contorno no la trunque, y el dominio lateral debe alejar la
        frontera de la depresión del extradós.
        """
        factory = gmsh.model.occ

        # 1. Túnel (fluido). Dimensiones en cuerdas desde el perfil.
        up, down, lat = self.__init_domain()
        if preview:
            # La previsualización mantiene la proporción pero escala para que
            # el perfil siga siendo visible; si no, el alabe queda en un píxel.
            k = 0.28
            up, down, lat = up * k, down * k, lat * k

        x_le = 0.0
        x_te = 1.0 * self.chord
        R = lat * self.chord
        x0 = x_le - up * self.chord
        x1 = x_te + down * self.chord
        tunnel_surf = factory.addRectangle(x0, -R, 0, x1 - x0, 2 * R)
        
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
