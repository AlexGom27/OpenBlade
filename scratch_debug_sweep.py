import json
import subprocess
import sys
import os

params = {
    "naca": "0012",
    "chord": 1.0,
    "aoa": 4.0,
    "u_inlet": 15.0,
    "p_outlet": 0.0,
    "regime": "Estacionario (simpleFoam)",
    "tolerance": "1e-4",
    "turbulence": "k-Omega SST (RAS)",
    "reynolds": 1000000.0,
    "mesh_size_min": 0.01,
    "mesh_growth_rate": 1.1,
    "wake_length": 5.0
}

with open("temp_debug.json", "w") as f:
    json.dump(params, f)

print("--- RUNNING MESH SCRIPT ---")
res_mesh = subprocess.run([sys.executable, "-m", "core.mesh_script", "temp_debug.json", "debug.msh"], capture_output=True, text=True)
print(res_mesh.stdout)
print(res_mesh.stderr)

print("--- RUNNING SOLVE SCRIPT ---")
res_solve = subprocess.run([sys.executable, "-m", "core.solve_script", "temp_debug.json", "debug.msh"], capture_output=True, text=True)
print(res_solve.stdout)
print(res_solve.stderr)
