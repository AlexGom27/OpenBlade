import sys
import gmsh
from core.geometry import NacaGeometry

def main():
    if len(sys.argv) < 5:
        print("Uso: python3 geom_script.py naca chord aoa output.stl")
        sys.exit(1)
        
    naca = sys.argv[1]
    chord = float(sys.argv[2])
    aoa = float(sys.argv[3])
    output_stl = sys.argv[4]
    
    try:
        # Iniciar sesión única para este script
        gmsh.initialize()
        
        geom = NacaGeometry(naca_code=naca, chord=chord, aoa=aoa)
        geom.build_geometry(mesh_extrusion=False, preview=True)
        
        # Forzar tamaños de malla para que el hueco se resuelva correctamente
        gmsh.option.setNumber("Mesh.MeshSizeMax", 0.02)
        gmsh.option.setNumber("Mesh.MeshSizeMin", 0.002)
        
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
