from qtpy.QtCore import QThread, Signal
import os
import sys
import json
import subprocess
from typing import Dict, Any


def app_root() -> str:
    """Raíz del repo (donde viven `core/` y `main.py`)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def subprocess_env() -> Dict[str, str]:
    """Entorno con la raíz del repo en PYTHONPATH.

    Los scripts se lanzan como `-m core.<script>`; si el CWD de la GUI no es la
    raíz del repo (p. ej. abierta desde Finder), el import fallaba.
    """
    env = os.environ.copy()
    root = app_root()
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root + (os.pathsep + current if current else "")
    return env


class MeshWorker(QThread):
    finished = Signal(str, str)
    error = Signal(str)
    log_msg = Signal(str)
    def __init__(self, params: Dict[str, Any], msh_file: str, case_dir: str) -> None:
        super().__init__()
        self.p = params
        self.msh_file = msh_file
        self.case_dir = case_dir
        self._proc = None

    def cancel(self) -> None:
        """Mata el gmsh en curso; sin esto el cierre de la app deja huérfanos."""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        
    def run(self) -> None:
        try:
            self.log_msg.emit("⏳ Iniciando mallado aislado...")
            from core import paths
            json_path = paths.temp_path("temp_params_mesh.json")
            with open(json_path, 'w') as f:
                json.dump(self.p, f)
            
            cmd = [sys.executable, "-m", "core.mesh_script", json_path, self.msh_file]
            # stdin=DEVNULL: si la GUI se lanzó con nohup, el fd 0 está
            # cerrado y el hijo muere con "can't initialize sys standard
            # streams". Con DEVNULL hereda un descriptor válido.
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace',
                env=subprocess_env()
            )
            try:
                out, err = self._proc.communicate()
            finally:
                rc = self._proc.returncode
                self._proc = None
            self.log_msg.emit(out)
            if rc == 0:
                self.finished.emit(self.msh_file, self.msh_file.replace(".msh", ".vtk"))
            else:
                self.error.emit(err)
        except Exception as e:
            self.error.emit(str(e))
