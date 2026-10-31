"""Ejecucion de simulaciones en un servidor por SSH.

El caso se prepara en esta maquina con el mismo codigo que una corrida local,
se sube con rsync y lo ejecuta core/remote_job.py en el servidor. Requiere una
clave SSH sin contrasena y rsync en ambos extremos.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            # Reutilizar la conexion: el avance se consulta cada pocos segundos.
            "-o", "ControlMaster=auto",
            "-o", "ControlPath=~/.ssh/openblade-%C",
            "-o", "ControlPersist=120"]
JOBS_DIR = "openblade_jobs"
EXCLUIR_BAJADA = ["processor*", "mesh.msh", "remote_job.py", "job.json",
                  "status.json", "job.log"]


class RemoteError(RuntimeError):
    pass


def validar_host(host: str) -> str:
    """Admite usuario@host; un '-' inicial se interpretaria como opcion de ssh."""
    host = (host or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:\-]*", host):
        raise RemoteError("Servidor no valido: usa usuario@host")
    return host


def _ssh(host: str, comando: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh"] + SSH_OPTS + [host, comando],
                          capture_output=True, text=True, errors="replace",
                          stdin=subprocess.DEVNULL, timeout=timeout)


def probar_servidor(host: str) -> Dict[str, Any]:
    """Nucleos, carga y OpenFOAM del servidor. Lanza RemoteError si no conecta."""
    host = validar_host(host)
    cmd = ("nproc; cut -d' ' -f1 /proc/loadavg; "
           "command -v rsync >/dev/null && echo rsync || echo sin-rsync; "
           "command -v python3 >/dev/null && echo python3 || echo sin-python3; "
           "ls -d /opt/openfoam*/etc/bashrc /usr/lib/openfoam/openfoam*/etc/bashrc "
           "/opt/OpenFOAM/OpenFOAM-*/etc/bashrc 2>/dev/null | tail -1; echo fin")
    try:
        r = _ssh(host, cmd, timeout=25)
    except subprocess.TimeoutExpired:
        raise RemoteError(f"{host} no responde") from None
    if r.returncode != 0:
        raise RemoteError(f"No se pudo conectar a {host}: {r.stderr.strip()[-200:]}")
    v = r.stdout.split("\n")
    nucleos, carga = int(v[0]), float(v[1])
    return {"host": host, "nucleos": nucleos, "carga": carga,
            "libres": max(0, int(nucleos - carga)),
            "rsync": v[2] == "rsync", "python3": v[3] == "python3",
            "openfoam": v[4] if v[4] != "fin" else ""}


def _clave_publica() -> str:
    """Devuelve la clave publica por defecto; si no hay ninguna, crea una."""
    ssh_dir = os.path.expanduser("~/.ssh")
    for nombre in ("id_ed25519", "id_ecdsa", "id_rsa"):
        pub = os.path.join(ssh_dir, nombre + ".pub")
        if os.path.exists(pub) and os.path.exists(pub[:-4]):
            break
    else:
        os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
        pub = os.path.join(ssh_dir, "id_ed25519.pub")
        r = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "",
                            "-f", pub[:-4]], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=30)
        if r.returncode != 0:
            raise RemoteError(f"No se pudo crear la clave SSH: {r.stderr.strip()[-200:]}")
    with open(pub) as f:
        return f.read().strip()


def configurar_acceso(host: str, contrasena: str) -> None:
    """Instala la clave SSH en el servidor usando la contrasena una sola vez.

    La contrasena llega a ssh por SSH_ASKPASS, desde el entorno de ese proceso:
    no aparece en la linea de comandos ni se escribe en disco.
    """
    host = validar_host(host)
    if os.name == "nt":
        raise RemoteError("En Windows configura la clave desde WSL")
    if not shutil.which("ssh") or not shutil.which("ssh-keygen"):
        raise RemoteError("Esta computadora no tiene el cliente de OpenSSH")
    clave = _clave_publica()
    remoto = ('umask 077; mkdir -p ~/.ssh; f=~/.ssh/authorized_keys; touch "$f"; '
              'k=$(cat); [ -z "$(tail -c1 "$f")" ] || echo >> "$f"; '
              'grep -qxF "$k" "$f" || printf \'%s\\n\' "$k" >> "$f"; '
              'chmod 700 ~/.ssh; chmod 600 "$f"')
    with tempfile.TemporaryDirectory() as tmp:
        askpass = os.path.join(tmp, "askpass.sh")
        with open(askpass, "w") as f:
            f.write('#!/bin/sh\nprintf \'%s\\n\' "$OPENBLADE_SSH_PASS"\n')
        os.chmod(askpass, 0o700)
        env = dict(os.environ, SSH_ASKPASS=askpass, SSH_ASKPASS_REQUIRE="force",
                   DISPLAY=os.environ.get("DISPLAY", ":0"),
                   OPENBLADE_SSH_PASS=contrasena)
        try:
            r = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=10", "-o", "ControlPath=none",
                 "-o", "StrictHostKeyChecking=accept-new",
                 "-o", "NumberOfPasswordPrompts=1", host, remoto],
                input=clave + "\n", capture_output=True, text=True, errors="replace",
                env=env, start_new_session=True, timeout=40)
        except subprocess.TimeoutExpired:
            raise RemoteError(f"{host} no responde") from None
    if r.returncode != 0:
        if "IDENTIFICATION HAS CHANGED" in r.stderr:
            raise RemoteError(f"La identidad de {host} cambio; no se envio la clave. "
                              "Confirma que sea el servidor correcto.")
        if "Permission denied" in r.stderr:
            raise RemoteError("Usuario o contrasena incorrectos")
        raise RemoteError(f"No se pudo conectar a {host}: {r.stderr.strip()[-200:]}")
    if _ssh(host, "true", timeout=25).returncode != 0:
        raise RemoteError("La clave se instalo pero no permite entrar; "
                          "si tiene frase de contrasena, cargala en ssh-agent")


class RemoteJob:
    def __init__(self, host: str, job_dir: Optional[str] = None,
                 etiqueta: str = "caso") -> None:
        self.host = validar_host(host)
        limpia = re.sub(r"[^A-Za-z0-9_.-]", "_", etiqueta)
        self.job_dir = job_dir or (
            f"{JOBS_DIR}/{time.strftime('%Y%m%d_%H%M%S')}_{limpia}")
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", self.job_dir) or ".." in self.job_dir:
            raise RemoteError(f"Directorio de trabajo no valido: {self.job_dir}")
        self.offset = 0
        self.ficha_sha256 = None

    def _run(self, comando: str, timeout: int = 60) -> str:
        r = _ssh(self.host, f"cd ~/{self.job_dir} && {comando}", timeout=timeout)
        if r.returncode != 0:
            raise RemoteError(r.stderr.strip()[-300:] or f"rc={r.returncode}")
        return r.stdout

    def _rsync(self, origen: str, destino: str, excluir: List[str]) -> None:
        cmd = ["rsync", "-az", "-e", "ssh " + " ".join(SSH_OPTS)]
        cmd += [f"--exclude={e}" for e in excluir] + [origen, destino]
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            raise RemoteError("rsync: " + r.stderr.strip()[-300:])

    def subir(self, case_dir: str, msh_file: str, nproc: int, transient: bool,
              params: Dict[str, Any]) -> None:
        """Sube el paquete con su ficha, sin lanzarlo."""
        from core.package import FICHA, build_ficha, sha256_file

        r = _ssh(self.host, f"mkdir -p ~/{self.job_dir}")
        if r.returncode != 0:
            raise RemoteError(f"No se pudo crear el trabajo: {r.stderr.strip()[-200:]}")

        malla = os.path.join(case_dir, "mesh.msh")
        shutil.copy2(msh_file, malla)
        with open(os.path.join(case_dir, "job.json"), "w") as f:
            json.dump({"nproc": nproc, "transient": transient}, f)
        shutil.copy2(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "remote_job.py"),
                     os.path.join(case_dir, "remote_job.py"))
        build_ficha(case_dir, params, msh_file)
        self.ficha_sha256 = sha256_file(os.path.join(case_dir, FICHA))
        try:
            self._rsync(case_dir.rstrip("/") + "/", f"{self.host}:{self.job_dir}/",
                        ["processor*", "*.log", "log.*", "*.foam"])
        finally:
            for nombre in ("mesh.msh", "job.json", "remote_job.py"):
                ruta = os.path.join(case_dir, nombre)
                if os.path.exists(ruta):
                    os.remove(ruta)

    def lanzar(self) -> None:
        # Los parentesis importan: un "cd && x &" dejaria un subshell con la
        # salida conectada al canal y ssh no volveria hasta que acabe el trabajo.
        self._run("(setsid nohup python3 remote_job.py > job.log 2>&1 < /dev/null &)",
                  timeout=30)

    def subir_y_lanzar(self, case_dir: str, msh_file: str, nproc: int, transient: bool,
                       params: Dict[str, Any]) -> None:
        self.subir(case_dir, msh_file, nproc, transient, params)
        self.lanzar()

    def comprobar_ficha(self, estado: Dict[str, Any]) -> None:
        """El servidor verifico la misma ficha que se envio."""
        huella = estado.get("ficha_sha256")
        if self.ficha_sha256 and huella and huella != self.ficha_sha256:
            raise RemoteError("La ficha del servidor no es la que se envió")

    def estado(self) -> Dict[str, Any]:
        """Estado del trabajo. Sin status.json aun no ha arrancado o no arrancara.

        Si python3 falla antes de escribir nada, job.log lo cuenta y el trabajo se
        da por fallido: antes quedaba como "running" para siempre.
        """
        salida = self._run('cat status.json 2>/dev/null || { echo; echo "--"; '
                           'tail -c 400 job.log 2>/dev/null; }', timeout=30)
        try:
            return json.loads(salida)
        except ValueError:
            pass
        _, _, log = salida.partition("--\n")
        if log.strip():
            return {"state": "failed", "rc": 1, "step": "inicio",
                    "error": f"El trabajo no arrancó: {log.strip()[-300:]}"}
        return {"state": "running", "step": "inicio"}

    def leer_log(self, maximo: int = 2_000_000) -> str:
        """Texto nuevo de run.log desde la ultima lectura."""
        salida = subprocess.run(
            ["ssh"] + SSH_OPTS + [
                self.host,
                f"tail -c +{self.offset + 1} ~/{self.job_dir}/run.log 2>/dev/null "
                f"| head -c {maximo}"],
            capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
        if salida.returncode != 0:
            raise RemoteError(salida.stderr.decode(errors="replace").strip()[-200:])
        self.offset += len(salida.stdout)
        return salida.stdout.decode(errors="replace")

    def _senal(self, sig: str) -> None:
        estado = self.estado()
        pgid = estado.get("pgid")
        if not isinstance(pgid, int) or pgid <= 1:
            raise RemoteError("El trabajo aun no ha registrado su proceso")
        # Solo el grupo de este trabajo: nunca afecta a otras campanas.
        self._run(f"kill -{sig} -- -{pgid}", timeout=20)

    def detener(self) -> None:
        self._senal("CONT")
        self._senal("TERM")

    def pausar(self) -> None:
        self._senal("STOP")

    def reanudar(self) -> None:
        self._senal("CONT")

    def descargar(self, case_dir: str) -> None:
        """Trae los resultados al caso local, donde los lee 'Ver Resultados'."""
        self._rsync(f"{self.host}:{self.job_dir}/", case_dir.rstrip("/") + "/",
                    EXCLUIR_BAJADA)


class LogParser:
    """Convierte texto de run.log en los mismos eventos que una corrida local."""
    _time = re.compile(r"^Time = ([0-9.eE+\-]+)")
    _res = re.compile(r"Solving for (\w+), Initial residual = ([0-9eE.+\-]+)")
    _fuerza = re.compile(r"^\s*(Cd|Cl|Cm|CmPitch)\s*[:=]\s*([0-9eE.+\-]+)\s*$")

    def __init__(self) -> None:
        self._resto = ""
        self.t = 0.0

    def feed(self, texto: str) -> List[Tuple]:
        eventos: List[Tuple] = []
        lineas = (self._resto + texto).split("\n")
        self._resto = lineas.pop()
        for l in lineas:
            m = self._time.match(l)
            if m:
                self.t = float(m.group(1))
                continue
            m = self._res.search(l)
            if m:
                if self.t > 0:
                    eventos.append(("residual", m.group(1), float(m.group(2)), self.t))
                continue
            m = self._fuerza.match(l)
            if m:
                nombre = "Cm" if m.group(1) == "CmPitch" else m.group(1)
                eventos.append(("fuerza", nombre, m.group(2)))
        return eventos
