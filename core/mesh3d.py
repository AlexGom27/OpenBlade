"""Parche: generar la malla del Plan B directamente en 3D con HXT.

Motivo
------
La malla no estructurada sale con 434 caras de no-ortogonalidad > 70 grados
(maximo 85.7). Eso hace inestable linearUpwind: el campo se desvia de
Cl=-0.01 a Cl=-61 950 en 150 iteraciones.

Se probo optimizar los triangulos 2D con Laplace2D y Netgen (hasta 8 pasadas
de 200 iteraciones). Las metricas no cambian: mismos 434 caras, misma
skewness 1.86755. La razon es que esas caras nacen en la EXTRUSION, despues
de que la optimizacion 2D ya actuo. Optimizar antes de extruir no puede
tocar caras que aun no existen.

Solucion
--------
Construir el volumen cerrado y mallarlo con el algoritmo 3D de gmsh (HXT,
Mesh.Algorithm3D=10), que si puede optimizar en 3D. Se conserva la capa
limite como campo de malla, que gmsh respeta en 3D.

Este modulo contiene la funcion que reemplaza al extrude.
"""

from __future__ import annotations


def generar_3d_directo(gmsh, fluid_surface, depth, lines, first_layer,
                       ratio, n_layers, mesh_size, farfield_size,
                       grow_dist):
    """Malla el volumen directamente en 3D con HXT.

    Devuelve (volumenes, superficies_front_back) para que el codigo que
    clasifica parches siga funcionando igual.

    Parametros
    ----------
    fluid_surface : tag de la superficie 2D (dominio con hueco del perfil)
    depth : espesor en z
    lines : curvas del contorno del perfil (para el campo de capa limite)
    """
    occ = gmsh.model.occ
    geo = gmsh.model.geo

    # Extruir la superficie para crear el volumen (necesario para tener
    # topologia 3D), pero SIN mallar todavia.
    res = geo.extrude([(2, fluid_surface)], 0, 0, depth, [1], [1.0], True)
    gmsh.model.geo.synchronize()

    volumenes = [t for d, t in res if d == 3]
    superficies_lat = [t for d, t in res if d == 2]
    frente = fluid_surface
    atras = res[0][1] if res else None

    # Campo de tamano por distancia al perfil, igual que en 2D.
    dist = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(dist, "CurvesList", lines)
    gmsh.model.mesh.field.setNumber(dist, "Sampling", 200)

    thr = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(thr, "InField", dist)
    gmsh.model.mesh.field.setNumber(thr, "SizeMin", mesh_size)
    gmsh.model.mesh.field.setNumber(thr, "SizeMax", farfield_size)
    gmsh.model.mesh.field.setNumber(thr, "DistMin", 0.0)
    gmsh.model.mesh.field.setNumber(thr, "DistMax", grow_dist)

    # Capa limite: gmsh la soporta tambien en 3D.
    bl = gmsh.model.mesh.field.add("BoundaryLayer")
    gmsh.model.mesh.field.setNumbers(bl, "CurvesList", lines)
    gmsh.model.mesh.field.setNumber(bl, "Size", first_layer)
    gmsh.model.mesh.field.setNumber(bl, "Ratio", ratio)
    gmsh.model.mesh.field.setNumber(bl, "NbLayers", n_layers)
    gmsh.model.mesh.field.setAsBoundaryLayer(bl)

    fmin = gmsh.model.mesh.field.add("Min")
    gmsh.model.mesh.field.setNumbers(fmin, "FieldsList", [thr])
    gmsh.model.mesh.field.setAsBackgroundMesh(fmin)

    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)

    # Algoritmo 3D: HXT (10) es el mas robusto y el unico que optimiza
    # bien en volumen. Alternativas: 1=Delaunay, 4=Frontal, 7=MMG3D.
    gmsh.option.setNumber("Mesh.Algorithm3D", 10)
    gmsh.option.setNumber("Mesh.Optimize", 1)
    gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)
    gmsh.option.setNumber("Mesh.OptimizeThreshold", 0.3)

    gmsh.model.mesh.generate(3)

    # Optimizacion 3D real: aqui SI existen las caras que hay que arreglar.
    for _ in range(3):
        gmsh.model.mesh.optimize("Netgen")
        gmsh.model.mesh.optimize("Laplace2D")

    return volumenes, [frente, atras], superficies_lat
