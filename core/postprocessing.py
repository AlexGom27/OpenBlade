import pyvista as pv
import os
import numpy as np

from typing import List, Optional, Any

class PostProcessor:
    def __init__(self, case_dir: str = "openfoam_case") -> None:
        self.case_dir = case_dir
        self.foam_file = os.path.join(self.case_dir, "case.foam")
        
        # OpenFOAMReader requires a .foam file
        if not os.path.exists(self.case_dir):
            os.makedirs(self.case_dir, exist_ok=True)
        with open(self.foam_file, "w") as f:
            pass
            
        self.reader = None
        self._mesh_cache = {}  # {time_index: vtkMesh}
        self._current_time_idx = -1

    def _ensure_reader(self) -> bool:
        if not os.path.exists(os.path.join(self.case_dir, "system", "controlDict")):
            return False
        if self.reader is None:
            try:
                self.reader = pv.OpenFOAMReader(self.foam_file)
            except Exception as e:
                print(f"Error initializing PyVista OpenFOAMReader: {e}")
                return False
        return True

    def get_time_values(self) -> List[float]:
        if not self._ensure_reader():
            return []
        return self.reader.time_values

    def get_mesh_at_index(self, index: int) -> Any:
        if not self._ensure_reader():
            return None
        try:
            if self.reader.time_values:
                idx = max(0, min(index, len(self.reader.time_values) - 1))
                if idx == self._current_time_idx and idx in self._mesh_cache:
                    return self._mesh_cache[idx]
                    
                self.reader.set_active_time_value(self.reader.time_values[idx])
                self._current_time_idx = idx
            
            mesh = self.reader.read()
            internal = mesh["internalMesh"]
            self._mesh_cache[idx] = internal
            return internal
            
        except Exception as e:
            print(f"Error loading OpenFOAM results at index {index}: {e}")
            return None

    def get_latest_mesh(self) -> Any:
        """
        Reads the OpenFOAM case and returns a 2D slice 
        of the internal mesh for the latest time step.
        """
        time_vals = self.get_time_values()
        idx = len(time_vals) - 1 if time_vals else 0
        return self.get_mesh_at_index(idx)

    def get_cp_on_surface(self, u_inf: float = 15.0, rho: float = 1.225) -> Optional[tuple]:
        """
        Extracts pressure on the airfoil surface and calculates Cp.
        Returns (x_upper, cp_upper, x_lower, cp_lower).
        """
        if not self._ensure_reader():
            return None
            
        try:
            # Set latest time
            times = self.reader.time_values
            if times:
                self.reader.set_active_time_value(times[-1])
            
            # Read only the airfoil patch to be efficient
            self.reader.disable_all_patch_arrays()
            if "airfoil" in self.reader.patch_array_names:
                self.reader.enable_patch_array("airfoil")
            else:
                # Fallback to internal mesh if patch not found (though less accurate for surface)
                mesh = self.reader.read()
                return None

            full_mesh = self.reader.read()
            # Extract the airfoil surface from the multi-block dataset
            # PyVista OpenFOAMReader returns a MultiBlock
            airfoil = None
            for i in range(full_mesh.n_blocks):
                block = full_mesh.get_block(i)
                # In PyVista 0.44+, some versions return blocks with names
                if "airfoil" in full_mesh.get_block_name(i).lower():
                    airfoil = block
                    break
            
            if airfoil is None:
                # If block names are not available or don't match, try to find 2D surface
                for i in range(full_mesh.n_blocks):
                    block = full_mesh.get_block(i)
                    if block.n_points > 0:
                        airfoil = block
                        break
            
            if airfoil is None: return None

            # OpenFOAM pressure for simpleFoam is p/rho (m^2/s^2)
            # Cp = (p - p_inf) / (0.5 * rho * U_inf^2)
            # If p is kinematic: Cp = (p_kin - p_kin_inf) / (0.5 * U_inf^2)
            p_kin = airfoil.point_data["p"]
            dyn_head = 0.5 * (u_inf ** 2)
            cp = p_kin / dyn_head if dyn_head > 0 else p_kin
            
            points = airfoil.points
            x = points[:, 0]
            y = points[:, 1]
            
            # Basic sorting into upper and lower surfaces
            # Assume chord from x=0 to x=c
            # Find the leading edge (roughly min x)
            le_idx = np.argmin(x)
            
            # This is a bit simplified: split by y relative to chord line
            # For a better approach, split at LE
            # Upper surface: points from LE to TE with higher y
            # Lower surface: points from LE to TE with lower y
            
            # Shift x to be x/c (normalized by max x)
            c = np.max(x) - np.min(x)
            x_norm = (x - np.min(x)) / c if c > 0 else x
            
            upper_mask = y >= 0
            lower_mask = y < 0
            
            x_up = x_norm[upper_mask]
            cp_up = cp[upper_mask]
            x_low = x_norm[lower_mask]
            cp_low = cp[lower_mask]
            
            # Sort by x
            idx_up = np.argsort(x_up)
            idx_low = np.argsort(x_low)
            
            return x_up[idx_up], cp_up[idx_up], x_low[idx_low], cp_low[idx_low]
            
        except Exception as e:
            print(f"Error extracting Cp: {e}")
            return None
