import gmsh
from typing import Dict, Any

class NacaMesher:
    def __init__(self, params: Dict[str, Any]) -> None:
        """
        Clase para gestionar el mallado no estructurado de alta fidelidad.
        params: Diccionario con parámetros de malla y geometría.
        """
        self.p = params
        self.chord = float(params.get("chord", 1.0))
        
        # Tamaños característicos escalados por la cuerda
        self.cl_min = float(params.get("mesh_size_min", 0.005)) * self.chord
        self.cl_max = float(params.get("mesh_size_max", 0.1)) * self.chord
        
        # Parámetros de capa límite
        self.bl_dist_min = float(params.get("bl_dist_min", 0.001)) * self.chord
        self.num_layers = int(params.get("mesh_num_layers", 15))
        self.growth_rate = float(params.get("mesh_growth_rate", 1.2))

    def generate_mesh(self) -> None:
        """Aplica campos de refinamiento y genera la malla 2D."""
        factory = gmsh.model.mesh
        
        # 1. Campo de Distancia al perfil (airfoil)
        # El airfoil en el fallback tiene el ID de curva 1 y 2 habitualmente
        # pero para ser robustos, buscamos todas las curvas actuales.
        curves = gmsh.model.getEntities(1)
        curve_tags = [c[1] for c in curves]
        
        # Filtrar curvas que pertenecen al airfoil (están cerca del origen)
        airfoil_curves = []
        for c in curve_tags:
            bbox = gmsh.model.getBoundingBox(1, c)
            if bbox[0] < self.chord * 1.5 and bbox[3] > -self.chord * 0.5:
                airfoil_curves.append(c)

        d_field = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(d_field, "CurvesList", airfoil_curves)
        gmsh.model.mesh.field.setNumber(d_field, "Sampling", 100)

        # 2. Campo de Capa Límite (Threshold)
        # Refinamiento cerca del perfil
        t_field = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(t_field, "InField", d_field)
        gmsh.model.mesh.field.setNumber(t_field, "SizeMin", self.cl_min)
        gmsh.model.mesh.field.setNumber(t_field, "SizeMax", self.cl_max)
        gmsh.model.mesh.field.setNumber(t_field, "DistMin", self.bl_dist_min)
        gmsh.model.mesh.field.setNumber(t_field, "DistMax", self.chord * 0.5)

        # 3. Campo de Estela (Wake)
        # Refinamiento detrás del perfil
        w_field = gmsh.model.mesh.field.add("Box")
        gmsh.model.mesh.field.setNumber(w_field, "VIn", self.cl_min * 2)
        gmsh.model.mesh.field.setNumber(w_field, "VOut", self.cl_max)
        gmsh.model.mesh.field.setNumber(w_field, "XMin", 0)
        gmsh.model.mesh.field.setNumber(w_field, "XMax", self.chord * 5)
        gmsh.model.mesh.field.setNumber(w_field, "YMin", -self.chord * 0.2)
        gmsh.model.mesh.field.setNumber(w_field, "YMax", self.chord * 0.2)
        gmsh.model.mesh.field.setNumber(w_field, "Thickness", self.chord * 0.5)

        # 4. Campo Min (Combinar todo)
        min_field = gmsh.model.mesh.field.add("Min")
        gmsh.model.mesh.field.setNumbers(min_field, "FieldsList", [t_field, w_field])
        
        gmsh.model.mesh.field.setAsBackgroundMesh(min_field)
        
        # Opciones globales de Gmsh
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        
        # Algoritmo de mallado (Frontal-Delaunay es robusto para 2D)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
