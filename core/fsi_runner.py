"""Orquestador del acoplamiento FSI fluido-estructura.

Lanza dos procesos que hablan por preCICE:

  1. ``simpleFoam``/``pimpleFoam`` con el adaptador
     ``preciceAdapterFunctionObject`` (lado fluido).
  2. ``core/structural_solver.py`` (lado sólido, Python + pyprecice).

preCICE usa sockets, así que el orden de arranque importa poco: el
"acceptor" (fluido) espera a que el "connector" (sólido) se conecte.

Este módulo NO resuelve física: sólo prepara el caso, lanza los procesos y
recoge su salida. La lógica de cada lado vive en ``fsi_precice`` y
``structural_solver``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from core.fsi_precice import FsiCase, FsiConfig, validate_config
from core.openfoam_setup import OpenFoamSetup

DEFAULT_IMAGE = "openblade-fsi:dev"


@dataclass
class FsiRunResult:
    ok: bool
    exit_fluid: int = 0
    exit_solid: int = 0
    displacement_max: float = 0.0
    time_windows: int = 0
    log_fluid: str = ""
    log_solid: str = ""
    error: str = ""


class FsiRunner:
    """Ejecuta un caso FSI completo dentro de la imagen con preCICE."""

    def __init__(self, case_dir: str, params: Dict, image: str = DEFAULT_IMAGE,
                 log: Optional[Callable[[str], None]] = None) -> None:
        self.case_dir = os.path.abspath(case_dir)
        self.params = params
        self.image = image
        self.log = log or (lambda _m: None)

    # ------------------------------------------------------------------
    def _cfg(self) -> FsiConfig:
        p = self.params
        return FsiConfig(
            dt=float(p.get("fsi_dt", 1e-3)),
            end_time=float(p.get("fsi_end_time", 0.5)),
            coupling_scheme=p.get("fsi_coupling", "serial-implicit"),
            relaxation=p.get("fsi_relaxation", "aitken"),
            max_iterations=int(p.get("fsi_max_iter", 50)),
            convergence_limit=float(p.get("fsi_tol", 1e-4)),
        )

    # ------------------------------------------------------------------
    def prepare(self) -> Dict[str, str]:
        """Escribe el caso CFD y los archivos de preCICE."""
        cfg = self._cfg()
        problems = validate_config(cfg)
        if problems:
            raise ValueError("Configuración FSI inválida: " + "; ".join(problems))

        p = self.params
        setup = OpenFoamSetup(case_dir=self.case_dir)
        setup.create_case(
            u_inlet=float(p.get("u_inlet", 15.0)),
            p_outlet=float(p.get("p_outlet", 0.0)),
            chord=float(p.get("chord", 1.0)),
            transient=True,                      # FSI es transitorio por definición
            tolerance=str(p.get("tolerance", "1e-5")),
            turbulence=p.get("turbulence", "k-Omega SST (RAS)"),
            reynolds=float(p.get("reynolds", 2e6)),
            delta_t=str(p.get("fsi_dt", 1e-3)),
            end_time=str(p.get("fsi_end_time", 0.5)),
            write_interval=str(p.get("fsi_dt", 1e-3)),
            max_co=float(p.get("max_co", 1.0)),
            max_iters=int(p.get("fsi_max_iter", 50)),
            momentum_scheme=p.get("momentum_scheme", "linearUpwind"),
        )

        files = FsiCase(self.case_dir, cfg).prepare()
        self.log(f"preCICE: {files['precice-config']}")

        # Convertir la malla de Gmsh a OpenFOAM si aún no está hecha. Sin esto
        # el solver aborta con: Cannot find file "points" in directory "polyMesh".
        polymesh = os.path.join(self.case_dir, "constant", "polyMesh", "points")
        if not os.path.exists(polymesh):
            msh = p.get("msh_file") or "mesh.msh"
            if not os.path.isabs(msh):
                msh = os.path.join(self.case_dir, msh)
            if not os.path.exists(msh):
                raise FileNotFoundError(
                    f"No hay malla convertida ni archivo .msh en {self.case_dir}"
                )
            from core.solver import SolverRunner
            self.log("Convirtiendo malla (gmshToFoam)…")
            SolverRunner(case_dir=self.case_dir, native=False).run_gmshToFoam(
                msh, log_callback=self.log
            )

        # El adaptador FSI necesita el campo pointDisplacement en 0/
        self._ensure_point_displacement()

        return files

    def _ensure_point_displacement(self) -> None:
        """Crea 0/pointDisplacement si no existe (requisito de malla dinámica)."""
        path = os.path.join(self.case_dir, "0", "pointDisplacement")
        if os.path.exists(path):
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(
                # pointDisplacement es un campo de PUNTOS, no de celdas:
                # class debe ser pointVectorField o OpenFOAM aborta con
                # "unexpected class name volVectorField expected pointVectorField".
                "FoamFile { version 2.0; format ascii; class pointVectorField; "
                "object pointDisplacement; }\n"
                "dimensions      [0 1 0 0 0 0 0];\n"
                "internalField   uniform (0 0 0);\n"
                "boundaryField\n{\n"
                # fixedValue, NO calculated: el adaptador hace refCast a Field para
                # escribir el desplazamiento, y con `calculated` aborta con
                # "Attempt to cast type calculated to type Field".
                "    airfoil      { type fixedValue; value uniform (0 0 0); }\n"
                "    inlet        { type fixedValue; value uniform (0 0 0); }\n"
                "    outlet       { type fixedValue; value uniform (0 0 0); }\n"
                "    farfield     { type fixedValue; value uniform (0 0 0); }\n"
                "    frontAndBack { type empty; }\n"
                "}\n"
            )

    # ------------------------------------------------------------------
    def run(self, timeout_s: int = 3600) -> FsiRunResult:
        """Lanza fluido y sólido bajo la misma red de Docker."""
        p = self.params

        try:
            self.prepare()
        except Exception as e:  # noqa: BLE001
            return FsiRunResult(ok=False, error=str(e))

        # IMPORTANTE: fluido y sólido deben correr en el MISMO contenedor.
        # En contenedores separados preCICE anuncia 127.0.0.1 en el archivo de
        # conexión y el otro participante no puede alcanzarlo (limitación
        # conocida de m2n:sockets con bridge networking).
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{self.case_dir}:/data", "-w", "/data",
            "-v", f"{os.path.dirname(os.path.abspath(__file__))}:/core:ro",
            self.image, "bash", "-lc",
            ". /usr/lib/openfoam/openfoam2512/etc/bashrc && cd /data && "
            "(pimpleFoam -case /data > /data/log.fluid 2>&1 &) && "
            "sleep 8 && "
            "python3 /core/structural_solver.py "
            "--config /data/precice-config.xml --participant Solid "
            f"--E {float(p.get('fsi_E', 2e6)):g} "
            f"--nu {float(p.get('fsi_nu', 0.3)):g} "
            f"--thickness {float(p.get('fsi_thickness', 0.1)):g} "
            f"--nx {int(p.get('fsi_nx', 40))} --ny {int(p.get('fsi_ny', 8))} "
            "> /data/log.solid 2>&1 ; "
            "sleep 3",
        ]

        self.log("Lanzando fluido y sólido bajo preCICE (mismo contenedor)…")
        t0 = time.time()
        try:
            run = subprocess.run(cmd, capture_output=True, text=True,
                                 errors="replace", timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return FsiRunResult(ok=False, error=f"timeout tras {timeout_s}s")

        out_f = self._read_log("log.fluid")
        out_s = self._read_log("log.solid")
        elapsed = round(time.time() - t0, 1)
        self.log(f"FSI terminado en {elapsed}s")

        # Indicadores de que el acoplamiento ocurrió de verdad
        coupled = ('Mapping "Stress"' in out_s) and ('Mapping "Displacement"' in out_s)
        windows = out_s.count("time-window")

        # El sólido imprime un JSON al final
        disp_max = 0.0
        try:
            tail = out_s[out_s.rindex("{"):]
            data = json.loads(tail[:tail.rindex("}") + 1])
            disp_max = float(data.get("max_displacement", 0.0))
        except Exception:
            pass

        ok = coupled and run.returncode == 0
        if not ok and not coupled:
            self.log("⚠️ No se detectó intercambio de datos: revisar log.fluid")

        return FsiRunResult(
            ok=ok,
            exit_fluid=0 if coupled else run.returncode,
            exit_solid=run.returncode,
            displacement_max=disp_max,
            time_windows=windows,
            log_fluid=out_f[-4000:],
            log_solid=out_s[-4000:],
        )

    def _read_log(self, name: str) -> str:
        path = os.path.join(self.case_dir, name)
        if not os.path.exists(path):
            return ""
        with open(path, errors="replace") as f:
            return f.read()


def check_image(image: str = DEFAULT_IMAGE) -> bool:
    """True si la imagen FSI está construida."""
    if not shutil.which("docker"):
        return False
    r = subprocess.run(["docker", "image", "inspect", image],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


if __name__ == "__main__":
    print("imagen FSI disponible:", check_image())
