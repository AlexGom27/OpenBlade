"""Valores por defecto de un caso, los mismos en la ventana y en la linea de comandos."""

from __future__ import annotations

from typing import Any, Dict

DEFAULT_PARAMS: Dict[str, Any] = {
    "profile_type": "NACA 4-dígitos",
    "naca": "0012",
    "file_path": "",
    "chord": 1.0,
    "analysis_mode": "Punto Único",
    "aoa": 0.0,
    "aoa_min": -4.0,
    "aoa_max": 24.0,
    "aoa_step": 2.0,
    "mesher": "cgrid",
    "grid_level": 2,
    "yplus_target": 0.5,
    "mesh_size_min": 0.006,
    "bl_dist_min": 0.00002,
    "mesh_growth_rate": 1.15,
    "nb_airfoil_pts": 0,
    "wake_length": 0.0,
    "farfield": 200.0,
    "regime": "Estacionario (simpleFoam)",
    "reynolds": 1000000.0,
    "u_inlet": 15.0,
    "p_outlet": 0.0,
    "tolerance": "1e-6",
    "turbulence": "k-Omega SST (RAS)",
    "turb_intensity": 0.052,
    "viscosity_ratio": 0.009,
    "momentum_scheme": "limitedLinearV",
    "delta_t": "1e-3",
    "end_time": "0.5",
    "write_interval": "0.01",
    "max_co": 10.0,
    "max_iters": 40000,
    "native_foam": False,
}


def case_params(**cambios: Any) -> Dict[str, Any]:
    """Parametros por defecto con los cambios indicados; una clave desconocida es un error."""
    extras = set(cambios) - set(DEFAULT_PARAMS) - OPCIONALES
    if extras:
        raise KeyError(f"Parametros desconocidos: {sorted(extras)}")
    return {**DEFAULT_PARAMS, **cambios}


# Se pueden fijar pero no tienen control en la ventana.
OPCIONALES = {"depth", "mesh_strategy", "bl_fraction", "bl_total_height", "bl_growth_dist",
              "wake_incline", "mesh_size_max", "mesh_num_layers", "wake_points", "surface_points",
              "normal_points", "mesh_file", "bc_type", "turb_scheme",
              "grad_scheme", "lap_correction", "alpha_mode", "relax_p", "relax_eq", "consistent",
              "campo_inicial"}
