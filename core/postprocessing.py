import pyvista as pv
import os
import numpy as np

from typing import List, Optional, Any

class PostProcessor:
    def __init__(self, case_dir: str = "openfoam_case") -> None:
        # Cache de tiempos que realmente contienen campos (ver _has_fields).
        self._valid_times = None
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

    def _has_fields(self, t: float) -> bool:
        """¿El directorio de este tiempo contiene los campos del flujo?

        OpenFOAM crea un directorio cada vez que CUALQUIER functionObject
        escribe. `yPlus` lo hace cada 100 pasos de tiempo, mientras el solver
        escribe U/p/k/... según `writeInterval`. Resultado: decenas de
        directorios que sólo contienen `yPlus`, sin campos.

        Si el reproductor los recorre, en esos tiempos no hay nada que pintar y
        se dibuja la malla gris como respaldo: eso producía los destellos en el
        vídeo.
        """
        if abs(t) < 1e-12:
            return True          # el tiempo 0 (condición inicial) siempre vale
        # pyvista puede devolver el tiempo con distinta representación textual
        for cand in (f"{t:g}", f"{t:.6f}", repr(t)):
            d = os.path.join(self.case_dir, cand)
            if os.path.isdir(d):
                return any(os.path.exists(os.path.join(d, f))
                           for f in ("U", "p"))
        return False

    def get_time_values(self) -> List[float]:
        if not self._ensure_reader():
            return []
        if self._valid_times is not None:
            return self._valid_times
        valid = [t for t in self.reader.time_values if self._has_fields(t)]
        # Si el filtro se comiera todo (caso raro), se usa la lista original
        # para no dejar la interfaz sin tiempos.
        self._valid_times = valid if valid else list(self.reader.time_values)
        return self._valid_times

    def get_mesh_at_index(self, index: int) -> Any:
        if not self._ensure_reader():
            return None
        try:
            times = self.get_time_values()
            idx = 0
            if times:
                idx = max(0, min(index, len(times) - 1))
                if idx == self._current_time_idx and idx in self._mesh_cache:
                    return self._mesh_cache[idx]

                self.reader.set_active_time_value(times[idx])
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

    @staticmethod
    def _find_block(mesh: Any, name_fragment: str) -> Any:
        """Busca un bloque por nombre en un MultiBlock (posiblemente anidado).

        El OpenFOAMReader de PyVista devuelve `[internalMesh, boundary]`, y los
        patches reales viven un nivel más abajo en `boundary`.
        """
        try:
            if mesh is None or not hasattr(mesh, "n_blocks"):
                return None
            for i in range(mesh.n_blocks):
                block = mesh.get_block(i)
                if block is None:
                    continue
                name = (mesh.get_block_name(i) or "").lower()
                if name_fragment in name and hasattr(block, "point_data"):
                    return block
                nested = PostProcessor._find_block(block, name_fragment)
                if nested is not None:
                    return nested
        except Exception:
            return None
        return None

    def _airfoil_patch_name(self) -> Optional[str]:
        """Devuelve el nombre real del patch del perfil tal como lo reporta VTK.

        PyVista expone los patches como 'patch/<nombre>', no como '<nombre>'.
        """
        try:
            for name in self.reader.patch_array_names:
                if "airfoil" in name.lower():
                    return name
        except Exception:
            return None
        return None

    def get_cp_on_surface(self, u_inf: float = 15.0, rho: float = 1.225) -> Optional[tuple]:
        """
        Extrae la presión sobre la superficie del perfil y calcula Cp.

        Devuelve (x_upper, cp_upper, x_lower, cp_lower) con x normalizado 0..1.
        """
        if not self._ensure_reader():
            return None

        try:
            times = self.reader.time_values
            if times:
                self.reader.set_active_time_value(times[-1])

            patch_name = self._airfoil_patch_name()
            if patch_name is None:
                return None

            # Leer solo el patch del perfil para no cargar todo el dominio.
            self.reader.enable_patch_array(patch_name)
            full_mesh = self.reader.read()

            airfoil = self._find_block(full_mesh, "airfoil")

            if airfoil is None or airfoil.n_points == 0:
                return None
            if "p" not in airfoil.point_data:
                return None

            p_kin = np.asarray(airfoil.point_data["p"], dtype=float)
            points = np.asarray(airfoil.points, dtype=float)
            if points.shape[0] < 4:
                return None

            x, y = points[:, 0], points[:, 1]

            # Separar extradós/intradós respecto a la línea de cuerda real.
            # Se usa PCA para tolerar perfiles rotados (ángulo de ataque).
            xy = np.column_stack([x, y])
            centered = xy - xy.mean(axis=0)
            try:
                _, _, vt = np.linalg.svd(centered, full_matrices=False)
                chord_dir = vt[0]
                normal = np.array([-chord_dir[1], chord_dir[0]])
            except np.linalg.LinAlgError:
                chord_dir = np.array([1.0, 0.0])
                normal = np.array([0.0, 1.0])

            # Orientar la cuerda de LE (x mínimo) a TE (x máximo).
            if chord_dir[0] < 0:
                chord_dir = -chord_dir
                normal = -normal

            s_proj = centered @ chord_dir
            n_proj = centered @ normal

            chord = s_proj.max() - s_proj.min()
            if chord <= 0:
                return None
            x_norm = (s_proj - s_proj.min()) / chord

            # El extradós está del lado positivo de la normal.
            upper_mask = n_proj >= 0
            lower_mask = ~upper_mask
            if not upper_mask.any() or not lower_mask.any():
                # Fallback para perfiles casi simétricos con n_proj ~ 0
                upper_mask = y >= np.median(y)
                lower_mask = ~upper_mask

            dyn_head = 0.5 * (float(u_inf) ** 2)
            cp = p_kin / dyn_head if dyn_head > 0 else p_kin

            def _sorted(mask):
                xs, cps = x_norm[mask], cp[mask]
                order = np.argsort(xs)
                return xs[order], cps[order]

            x_up, cp_up = _sorted(upper_mask)
            x_low, cp_low = _sorted(lower_mask)
            return x_up, cp_up, x_low, cp_low

        except Exception as e:
            print(f"Error extracting Cp: {e}")
            return None
