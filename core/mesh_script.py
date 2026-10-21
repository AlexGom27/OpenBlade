"""
Mesh generation script for HAWT CFD workbench.

Uses gmshairfoil2d for professional-grade structured C-grid mesh generation,
then extrudes to 3D (1 cell thick) for OpenFOAM 2D simulations.
"""

import sys
import os
import json
import math
import gmsh
import numpy as np

try:
    from gmshairfoil2d.airfoil_func import four_digit_naca_airfoil, read_airfoil_from_file
    from gmshairfoil2d.geometry_def import AirfoilSpline, CType
    GMSH_AIRFOIL_AVAILABLE = True
except ImportError:
    GMSH_AIRFOIL_AVAILABLE = False
    
    # Simple NACA 4-digit generator fallback if library is missing
    def four_digit_naca_airfoil(naca, n=100):
        m = int(naca[0]) / 100.0
        p = int(naca[1]) / 10.0
        t = int(naca[2:]) / 100.0
        x = np.linspace(0, 1, n)
        y_t = 5 * t * (0.2969 * np.sqrt(x) - 0.1260 * x - 0.3516 * x**2 + 0.2843 * x**3 - 0.1015 * x**4)
        y_c = np.where(x < p, m / p**2 * (2 * p * x - x**2), m / (1 - p)**2 * ((1 - 2 * p) + 2 * p * x - x**2)) if p > 0 else np.zeros_like(x)
        dyc_dx = np.where(x < p, 2 * m / p**2 * (p - x), 2 * m / (1 - p)**2 * (p - x)) if p > 0 else np.zeros_like(x)
        theta = np.arctan(dyc_dx)
        xu = x - y_t * np.sin(theta)
        yu = y_c + y_t * np.cos(theta)
        xl = x + y_t * np.sin(theta)
        yl = y_c - y_t * np.cos(theta)
        # Combine upper and lower, avoiding duplicate trailing edge
        pts = [[xx, yy, 0.0] for xx, yy in zip(xu[::-1], yu[::-1])] + [[xx, yy, 0.0] for xx, yy in zip(xl[1:], yl[1:])]
        return pts

    def read_airfoil_from_file(path):
        pts = []
        with open(path, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    try: pts.append([float(parts[0]), float(parts[1]), 0.0])
                    except ValueError: pass
        return pts


def main():
    if len(sys.argv) < 3:
        print("Uso: python3 mesh_script.py params.json output.msh")
        sys.exit(1)
        
    json_path = sys.argv[1]
    output_msh = sys.argv[2]
    
    with open(json_path, 'r') as f:
        p = json.load(f)
    
    try:
        naca = p.get("naca", "0012")
        chord = p.get("chord", 1.0)
        aoa_deg = p.get("aoa", 0.0)
        aoa_rad = aoa_deg * (math.pi / 180)
        print(f"DEBUG: Generando malla para AoA = {aoa_deg} deg")
        
        is_custom = "Custom" in p.get("profile_type", "")
        
        # Parámetros de malla (corregidos para leer de la UI)
        mesh_size = p.get("mesh_size_min", 0.02) * chord
        first_layer = p.get("bl_dist_min", 0.001) * chord # Ahora sí usa el parámetro de capa límite
        ratio = p.get("mesh_growth_rate", 1.15)
        farfield_size = p.get("mesh_size_max", 1.0) * chord # Para que no quede tupido lejos
        wake_length = p.get("wake_length", 5.0) * chord
        # Radio/caja del dominio exterior en cuerdas. Configurable para poder
        # hacer estudios de sensibilidad (NASA TMR recomienda >100c sin
        # corrección de vórtice lejano; con 10c el bloqueo altera Cl y Cd).
        farfield = float(p.get("farfield", 10.0)) * chord
        depth = float(p.get("depth", 0.1)) * chord
        
        gmsh.initialize()
        gmsh.model.add("NACA")
        
        # 2. CREAR GEOMETRÍA DEL PERFIL
        nb_points = p.get("mesh_nb_points", 100)
        
        if is_custom and p.get("file_path"):
            cloud_points = read_airfoil_from_file(p["file_path"])
        else:
            cloud_points = four_digit_naca_airfoil(str(naca), nb_points=nb_points)
        
        le = min(pt[0] for pt in cloud_points)
        for pt in cloud_points:
            if pt[0] == le:
                debut = cloud_points.index(pt)
        cloud_points = cloud_points[debut:] + cloud_points[:debut]
        if cloud_points[1][1] < cloud_points[0][1]:
            cloud_points.reverse()
            cloud_points = cloud_points[-1:] + cloud_points[:-1]
        
        # Escalar y rotar puntos manualmente
        c_rot = 0.25 * chord
        angle = -aoa_rad 
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        
        rotated_points = []
        for pt in cloud_points:
            x = pt[0] * chord
            y = pt[1] * chord
            dx = x - c_rot
            dy = y
            nx = c_rot + (dx * cos_a - dy * sin_a)
            ny = (dx * sin_a + dy * cos_a)
            rotated_points.append([nx, ny, 0.0])
            
        volumes = []
        front_back_surfaces = []
        extrusion_map = []

        # Estrategia de mallado:
        #   auto         -> intenta C-Grid estructurado y cae a Gmsh nativo
        #   structured   -> solo C-Grid (falla si no es válido)
        #   unstructured -> solo Gmsh nativo (no estructurado)
        strategy = p.get("mesh_strategy", "auto")
        if strategy == "unstructured":
            raise_fallback = RuntimeError("estrategia 'unstructured' solicitada")
        else:
            raise_fallback = None

        try:
            if raise_fallback is not None:
                raise raise_fallback
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("error", RuntimeWarning)
                
                # PLAN A: GmshAirfoil2D (Estructurado C-Grid)
                airfoil = AirfoilSpline(rotated_points, mesh_size, name="airfoil")
                gmsh.model.geo.synchronize()
                
                # OJO: el 4o argumento de CType es el tamaño de malla del
                # PERFIL, no del farfield. Pasar `farfield_size` (mesh_size_max,
                # ~1.0c) dejaba el perfil con 3 puntos -> 11 caras en el patch
                # `airfoil` y el resto de la superficie acababa en defaultFaces.
                mesh = CType(airfoil, wake_length, farfield,
                             mesh_size, first_layer, ratio, 0.0,
                             structured=True)
                gmsh.model.geo.synchronize()
                
            gmsh.model.mesh.generate(2)
            
            for s_tag in mesh.surfaces:
                res = gmsh.model.geo.extrude([(2, s_tag)], 0, 0, depth, [1], [1], True)
                volumes.append(res[0][1])
                front_back_surfaces.append(s_tag)
                front_back_surfaces.append(res[1][1])
                side_tags = [r[1] for r in res[2:]]
                extrusion_map.append((s_tag, side_tags))
                
        except Exception as e:
            print(f"⚠️ Aviso: gmshairfoil2d CType falló ({e}). Usando PLAN B (Mallado Nativo No Estructurado).")
            # PLAN B: Malla no estructurada nativa de Gmsh
            gmsh.clear()
            gmsh.model.add("NACA_Fallback")
            
            pts = []
            for pt in rotated_points:
                pts.append(gmsh.model.geo.addPoint(pt[0], pt[1], 0, mesh_size))
            
            lines = []
            for i in range(len(pts)-1):
                lines.append(gmsh.model.geo.addLine(pts[i], pts[i+1]))
            lines.append(gmsh.model.geo.addLine(pts[-1], pts[0]))
            airfoil_loop = gmsh.model.geo.addCurveLoop(lines)
            
            # Farfield: C-Grid Shape (Semicírculo frontal + Caja trasera)
            center = gmsh.model.geo.addPoint(0, 0, 0, farfield_size)
            
            p_top = gmsh.model.geo.addPoint(0, farfield, 0, farfield_size)
            p_front = gmsh.model.geo.addPoint(-farfield, 0, 0, farfield_size)
            p_bottom = gmsh.model.geo.addPoint(0, -farfield, 0, farfield_size)
            
            p_tr = gmsh.model.geo.addPoint(wake_length, farfield, 0, farfield_size)
            p_br = gmsh.model.geo.addPoint(wake_length, -farfield, 0, farfield_size)
            
            # Arco frontal superior
            arc1 = gmsh.model.geo.addCircleArc(p_top, center, p_front)
            # Arco frontal inferior
            arc2 = gmsh.model.geo.addCircleArc(p_front, center, p_bottom)
            
            # Líneas rectas
            l_bottom = gmsh.model.geo.addLine(p_bottom, p_br)
            l_back = gmsh.model.geo.addLine(p_br, p_tr)
            l_top = gmsh.model.geo.addLine(p_tr, p_top)
            
            farfield_loop = gmsh.model.geo.addCurveLoop([arc1, arc2, l_bottom, l_back, l_top])
            
            fluid_surface = gmsh.model.geo.addPlaneSurface([farfield_loop, airfoil_loop])
            gmsh.model.geo.synchronize()
            
            # Capa límite nativa
            gmsh.model.mesh.field.add("BoundaryLayer", 1)
            gmsh.model.mesh.field.setNumbers(1, "CurvesList", lines)
            gmsh.model.mesh.field.setNumber(1, "Size", first_layer)
            gmsh.model.mesh.field.setNumber(1, "Ratio", ratio)
            gmsh.model.mesh.field.setNumber(1, "NbLayers", p.get("mesh_num_layers", 15))
            gmsh.model.mesh.field.setAsBoundaryLayer(1)
            
            gmsh.model.mesh.generate(2)
            
            res = gmsh.model.geo.extrude([(2, fluid_surface)], 0, 0, depth, [1], [1], True)
            front_back_surfaces.extend([fluid_surface, res[0][1]])
            side_tags = [r[1] for r in res[2:]]
            extrusion_map.append((fluid_surface, side_tags))
            
        gmsh.model.geo.synchronize()
        
        # Clasificar superficies
        bbox_all = gmsh.model.getBoundingBox(-1, -1)
        xmin_d, ymin_d, zmin_d, xmax_d, ymax_d, zmax_d = bbox_all
        
        inlet_surfaces = []
        outlet_surfaces = []
        walls_surfaces = []
        airfoil_surfaces = []
        
        for s_tag, side_tags in extrusion_map:
            for side_tag in side_tags:
                bbox = gmsh.model.getBoundingBox(2, side_tag)
                xc = (bbox[0] + bbox[3]) / 2
                yc = (bbox[1] + bbox[4]) / 2
                
                # C-Grid robust classification:
                # Outlet is the straight vertical line at the far right
                if xc > xmax_d - 0.05 * (xmax_d - xmin_d):
                    outlet_surfaces.append(side_tag)
                # Airfoil is very close to the origin (chord is approx 1.0)
                elif abs(xc) < 2.0 * chord and abs(yc) < 2.0 * chord:
                    airfoil_surfaces.append(side_tag)
                # Everything else on the outer boundary is the inlet (top, bottom, and front semi-circle)
                else:
                    inlet_surfaces.append(side_tag)
        
        # Grupos físicos
        gmsh.model.addPhysicalGroup(2, front_back_surfaces, name="frontAndBack")
        gmsh.model.addPhysicalGroup(2, inlet_surfaces, name="inlet")
        gmsh.model.addPhysicalGroup(2, outlet_surfaces, name="outlet")
        gmsh.model.addPhysicalGroup(2, walls_surfaces, name="walls_TB")
        gmsh.model.addPhysicalGroup(2, airfoil_surfaces, name="airfoil")
        
        final_volumes = [t for d, t in gmsh.model.getEntities(3)]
        gmsh.model.addPhysicalGroup(3, final_volumes, name="fluid")
        
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.option.setNumber("Mesh.Binary", 0)
        gmsh.model.mesh.generate(3)
        
        gmsh.write(output_msh)
        gmsh.write(output_msh.replace(".msh", ".vtk"))
        print(f"✅ Malla estructurada generada: {output_msh}")
        
    finally:
        if gmsh.isInitialized(): gmsh.finalize()

if __name__ == "__main__":
    main()
