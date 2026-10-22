import sys
import gmsh
from core.geometry import NacaGeometry

def main():
    if len(sys.argv) < 5:
        print("Uso: python3 geom_script.py naca chord aoa output.stl [perfil_custom.txt]")
        sys.exit(1)

    naca = sys.argv[1]
    chord = float(sys.argv[2])
    aoa = float(sys.argv[3])
    output_stl = sys.argv[4]
    custom_path = sys.argv[5] if len(sys.argv) > 5 else None

    try:
        # Iniciar sesión única para este script
        gmsh.initialize()

        geom = NacaGeometry(naca_code=naca, chord=chord, aoa=aoa,
                            custom_profile_path=custom_path)
        geom.build_geometry(mesh_extrusion=False, preview=True)
        
        # --- Tamaños de malla proporcionales al dominio --------------------
        #
        # Antes eran fijos (0.02 / 0.002). Con el dominio ampliado a 6c-12c-8c
        # eso genera millones de nodos en la previsualización y ahoga la app.
        # Ahora se escalan con la extensión real del volumen de control y se
        # refina la estela, que es lo que el usuario necesita ver.
        bb = gmsh.model.getBoundingBox(2, geom.fluid_surf)
        ancho = bb[3] - bb[0]
        alto = bb[4] - bb[1]

        size_far = max(ancho, alto) / 45.0
        size_near = chord / 300.0
        gmsh.option.setNumber("Mesh.MeshSizeMax", size_far)
        gmsh.option.setNumber("Mesh.MeshSizeMin", size_near)

        # --- Refinamiento en el perfil Y en la estela -----------------------
        #
        # Un único campo de distancia al perfil refina radialmente y deja la
        # estela sin resolver: se ve como una nube uniforme y no se distingue
        # el gradiente que el usuario quiere visualizar. Se añade un segundo
        # campo de distancia a la línea central de la estela (y = 0 desde el
        # borde de salida hasta el contorno de salida) y se combinan con Min.
        perfiles = [c for (d, c) in gmsh.model.getEntities(1)]

        dist_foil = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(dist_foil, "CurvesList", perfiles)
        gmsh.model.mesh.field.setNumber(dist_foil, "Sampling", 200)

        thr_foil = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(thr_foil, "InField", dist_foil)
        gmsh.model.mesh.field.setNumber(thr_foil, "SizeMin", size_near)
        gmsh.model.mesh.field.setNumber(thr_foil, "SizeMax", size_far)
        gmsh.model.mesh.field.setNumber(thr_foil, "DistMin", 0.0)
        gmsh.model.mesh.field.setNumber(thr_foil, "DistMax", 0.45 * chord)

        # Franja de estela refinada.
        #
        # El campo `Distance` de gmsh mide a entidades geométricas o a una
        # lista de TAGS de puntos, no a coordenadas sueltas: pasarle una lista
        # vacía deja el campo inerte. Para una región rectangular lo correcto
        # es un campo `Box`, que refina dentro de la caja y transiciona hacia
        # fuera en `Thickness`.
        box = gmsh.model.mesh.field.add("Box")
        gmsh.model.mesh.field.setNumber(box, "VIn", size_near * 2.0)
        gmsh.model.mesh.field.setNumber(box, "VOut", size_far)
        gmsh.model.mesh.field.setNumber(box, "XMin", chord)
        gmsh.model.mesh.field.setNumber(box, "XMax", bb[3])
        gmsh.model.mesh.field.setNumber(box, "YMin", -0.06 * chord)
        gmsh.model.mesh.field.setNumber(box, "YMax", 0.06 * chord)
        gmsh.model.mesh.field.setNumber(box, "ZMin", -1.0)
        gmsh.model.mesh.field.setNumber(box, "ZMax", 1.0)
        gmsh.model.mesh.field.setNumber(box, "Thickness", 0.35 * chord)

        fmin = gmsh.model.mesh.field.add("Min")
        gmsh.model.mesh.field.setNumbers(fmin, "FieldsList", [thr_foil, box])
        gmsh.model.mesh.field.setAsBackgroundMesh(fmin)

        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)

        # Generar malla ligera solo para previsualización (no es la malla CFD)
        gmsh.model.mesh.generate(2)
        
        # Exportar y finalizar
        gmsh.write(output_stl)
        gmsh.finalize()
        print("SUCCESS")
    except Exception as e:
        print(f"ERROR: {e}")
        if gmsh.isInitialized():
            gmsh.finalize()
        sys.exit(1)

if __name__ == "__main__":
    main()
