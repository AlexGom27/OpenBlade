"""Ejecucion en esta maquina, con el mismo trabajo que en un servidor.

Corre core/remote_job.py sobre la carpeta del trabajo: los pasos, la ficha y
checkMesh son los mismos que en un servidor. OpenFOAM viene de la imagen de
Docker con la version fijada (docker/Dockerfile.openfoam12) o, en modo nativo,
de la instalacion del sistema.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import signal
import subprocess
from typing import Any, Dict, Optional

from core.remote_runner import FichaDistinta, RemoteError

# Misma version que los servidores: el paquete openfoam12 20250206 de Ubuntu 24.04.
IMAGEN = "openblade/openfoam12:20250206"
PLATAFORMA = "linux/amd64"
DOCKERFILE = os.path.join("docker", "Dockerfile.openfoam12")


def probar_docker() -> Dict[str, Any]:
    """Si Docker responde y si la imagen de OpenFOAM esta construida."""
    if not shutil.which("docker"):
        return {"docker": False, "imagen": False,
                "mensaje": "Docker no está instalado. Usa un servidor o el modo nativo."}
    try:
        r = subprocess.run(["docker", "image", "inspect", IMAGEN], capture_output=True,
                           text=True, stdin=subprocess.DEVNULL, timeout=20)
    except subprocess.TimeoutExpired:
        return {"docker": False, "imagen": False, "mensaje": "Docker no responde."}
    if "Cannot connect" in r.stderr or "failed to connect" in r.stderr:
        return {"docker": False, "imagen": False, "mensaje": "Abre Docker Desktop: no está corriendo."}
    if r.returncode != 0:
        return {"docker": True, "imagen": False,
                "mensaje": f"Falta la imagen {IMAGEN}. Constrúyela una vez con:\n"
                           f"docker build --platform {PLATAFORMA} -t {IMAGEN} -f {DOCKERFILE} docker"}
    return {"docker": True, "imagen": True, "mensaje": f"Docker listo con {IMAGEN}"}


class LocalJob:
    """Misma interfaz que RemoteJob, sobre la carpeta local del trabajo."""

    def __init__(self, case_dir: str, nombre: str, nativo: bool = False) -> None:
        self.host = "local"
        self.case_dir = case_dir
        self.job_dir = case_dir
        self.nombre = "openblade-" + nombre
        self.nativo = nativo
        self.offset = 0
        self.ficha_sha256 = None

    def _ruta(self, nombre: str) -> str:
        return os.path.join(self.case_dir, nombre)

    def subir(self, case_dir: str, msh_file: str, nproc: int, transient: bool,
              params: Dict[str, Any]) -> None:
        """El caso ya esta aqui: solo se completa el paquete y su ficha."""
        from core.package import FICHA, build_ficha, sha256_file

        shutil.copy2(msh_file, self._ruta("mesh.msh"))
        with open(self._ruta("job.json"), "w") as f:
            json.dump({"nproc": nproc, "transient": transient,
                       "sin_potencial": bool(params.get("campo_inicial"))}, f)
        shutil.copy2(os.path.join(os.path.dirname(os.path.abspath(__file__)), "remote_job.py"),
                     self._ruta("remote_job.py"))
        build_ficha(case_dir, params, msh_file)
        self.ficha_sha256 = sha256_file(self._ruta(FICHA))

    def lanzar(self) -> None:
        if self.nativo:
            with open(self._ruta("job.log"), "w") as log:
                subprocess.Popen(["python3", "remote_job.py"], cwd=self.case_dir,
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                 start_new_session=True)
            return
        estado = probar_docker()
        if not estado["imagen"]:
            raise RemoteError(estado["mensaje"])
        r = subprocess.run(
            ["docker", "run", "-d", "--rm", "--name", self.nombre, "--platform", PLATAFORMA,
             "-v", f"{os.path.abspath(self.case_dir)}:/caso", "-w", "/caso",
             "-e", "OMPI_ALLOW_RUN_AS_ROOT=1", "-e", "OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1",
             "--init", IMAGEN, "bash", "-c", "exec python3 remote_job.py > job.log 2>&1"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
        if r.returncode != 0:
            raise RemoteError(f"Docker no pudo lanzar el trabajo: {r.stderr.strip()[-300:]}")

    def _contenedor_vivo(self) -> bool:
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", self.nombre],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=20)
        return r.returncode == 0 and r.stdout.strip() == "true"

    def _leer_estado(self) -> Optional[Dict[str, Any]]:
        try:
            with open(self._ruta("status.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def estado(self) -> Dict[str, Any]:
        est = self._leer_estado()
        if est is not None and est.get("state") != "running":
            return est
        vivo = True
        if not self.nativo:
            vivo = self._contenedor_vivo()
        elif est and isinstance(est.get("pid"), int):
            try:
                os.kill(est["pid"], 0)
            except OSError:
                vivo = False
        if vivo:
            return est or {"state": "running", "step": "inicio"}
        # El proceso desaparecio sin dejar su estado final.
        try:
            with open(self._ruta("job.log"), errors="replace") as f:
                cola = f.read()[-300:]
        except OSError:
            cola = ""
        return {"state": "failed", "rc": 1, "step": (est or {}).get("step", "inicio"),
                "error": f"El trabajo se interrumpió. {cola}".strip()}

    def comprobar_ficha(self, estado: Dict[str, Any]) -> None:
        huella = estado.get("ficha_sha256")
        if self.ficha_sha256 and huella and huella != self.ficha_sha256:
            raise FichaDistinta("La ficha del trabajo no es la que se creó")

    def leer_log(self, maximo: int = 2_000_000) -> str:
        try:
            with open(self._ruta("run.log"), "rb") as f:
                f.seek(self.offset)
                datos = f.read(maximo)
        except OSError:
            return ""
        self.offset += len(datos)
        return datos.decode(errors="replace")

    def _senal(self, sig: signal.Signals) -> None:
        if not self.nativo:
            subprocess.run(["docker", "kill", "--signal", sig.name, self.nombre],
                           capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
            return
        est = self._leer_estado() or {}
        pgid = est.get("pgid")
        if not isinstance(pgid, int) or pgid <= 1:
            raise RemoteError("El trabajo aun no ha registrado su proceso")
        os.killpg(pgid, sig)

    def terminar_en(self, iteracion: int) -> None:
        """Adelanta el final del calculo a esa iteracion: las fuerzas ya no cambian."""
        ruta = os.path.join(self._ruta("system"), "controlDict")
        with open(ruta) as f:
            texto = f.read()
        with open(ruta, "w") as f:
            f.write(re.sub(r"(?m)^endTime .*$", f"endTime         {int(iteracion)};", texto))

    def detener(self) -> None:
        if not self.nativo:
            subprocess.run(["docker", "unpause", self.nombre], capture_output=True,
                           stdin=subprocess.DEVNULL, timeout=30)
        else:
            self._senal(signal.SIGCONT)
        self._senal(signal.SIGTERM)

    def pausar(self) -> None:
        if self.nativo:
            self._senal(signal.SIGSTOP)
        else:
            subprocess.run(["docker", "pause", self.nombre], capture_output=True,
                           stdin=subprocess.DEVNULL, timeout=30)

    def reanudar(self) -> None:
        if self.nativo:
            self._senal(signal.SIGCONT)
        else:
            subprocess.run(["docker", "unpause", self.nombre], capture_output=True,
                           stdin=subprocess.DEVNULL, timeout=30)

    def descargar(self, case_dir: str) -> None:
        """Los resultados ya estan en la carpeta del trabajo."""

    def limpiar(self) -> None:
        """Lo que solo hacia falta para calcular."""
        for ruta in glob.glob(self._ruta("processor*")):
            shutil.rmtree(ruta, ignore_errors=True)
        for nombre in ("mesh.msh", "remote_job.py"):
            if os.path.exists(self._ruta(nombre)):
                os.remove(self._ruta(nombre))
