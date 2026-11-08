"""Ejecucion de simulaciones en un servidor por SSH.

El caso se prepara en esta maquina con el mismo codigo que una corrida local,
se sube con rsync y lo ejecuta core/remote_job.py en el servidor. Requiere una
clave SSH sin contrasena y rsync en ambos extremos.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

_SSH_BASE = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
             # Si la Mac se duerme o cambia de red, la conexion muere sin avisar: sin esto
             # una descarga se queda colgada para siempre.
             "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4",
             # El log es texto: comprimido pasa por una red lenta, como la del telefono.
             "-o", "Compression=yes"]

# Una conexion por tarea y servidor, no una sola para todo. Antes, consultas, subidas y
# descargas compartian el mismo canal SSH (mismo ControlPath), asi que un rsync de varios
# minutos llenaba el canal: la subida del paquete siguiente esperaba a la descarga del
# anterior (medido en el 6e6: gci_a15_n2 subio de 31877 s a 35142 s, con 1427 s solapados
# con la descarga de gci_a0_n1), y las consultas de estado se quedaban sin respuesta
# durante las descargas. Con canales distintos, una subida no hace cola detras de una
# descarga. El ancho de banda sigue siendo el mismo para todos.
def _ssh_opts(canal: str) -> List[str]:
    return _SSH_BASE + ["-o", "ControlMaster=auto",
                        "-o", f"ControlPath=~/.ssh/openblade-{canal}-%C",
                        "-o", "ControlPersist=120"]


SSH_OPTS = _ssh_opts("ssh")            # consultas cortas: estado, log, señales
SSH_OPTS_SUBIDA = _ssh_opts("sube")
SSH_OPTS_BAJADA = _ssh_opts("baja")
JOBS_DIR = "openblade_jobs"
INTENTOS_RSYNC = 5
ESPERA_RSYNC = 5.0
# Un calculo terminado no se pierde por un corte: la descarga insiste durante horas.
INTENTOS_DESCARGA = 240
ESPERA_MAX_RSYNC = 60.0
TIEMPO_RSYNC = 120      # segundos sin transferir nada antes de dar la conexion por muerta
BLOQUE_MINIMO = 32_000  # lo minimo que se pide de run.log en cada lectura
EXCLUIR_BAJADA = ["processor*", "mesh.msh", "remote_job.py", "job.json",
                  "status.json", "job.log"]


class RemoteError(RuntimeError):
    pass


class FichaDistinta(RemoteError):
    """El servidor verifico otra ficha: no es un corte de red, no se reintenta."""


def _aviso_tailscale(salida) -> str:
    """Tailscale SSH puede pedir autenticarse: ssh se queda esperando y solo da un enlace."""
    if isinstance(salida, bytes):
        salida = salida.decode(errors="replace")
    m = re.search(r"https://login\.tailscale\.com/\S+", salida or "")
    return f"Tailscale pide autenticarse: abre {m.group(0)}" if m else ""


def validar_host(host: str) -> str:
    """Admite usuario@host; un '-' inicial se interpretaria como opcion de ssh."""
    host = (host or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:\-]*", host):
        raise RemoteError("Servidor no valido: usa usuario@host")
    return host


def _ssh(host: str, comando: str, timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["ssh"] + SSH_OPTS + [host, comando],
                              capture_output=True, text=True, errors="replace",
                              stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        aviso = _aviso_tailscale(e.stdout) or _aviso_tailscale(e.stderr)
        if aviso:
            raise RemoteError(aviso) from None
        raise


def probar_servidor(host: str) -> Dict[str, Any]:
    """Nucleos, carga y OpenFOAM del servidor. Lanza RemoteError si no conecta."""
    host = validar_host(host)
    cmd = ("nproc; cut -d' ' -f1 /proc/loadavg; "
           "command -v rsync >/dev/null && echo rsync || echo sin-rsync; "
           "command -v python3 >/dev/null && echo python3 || echo sin-python3; "
           "ls -d /opt/openfoam*/etc/bashrc /usr/lib/openfoam/openfoam*/etc/bashrc "
           "/opt/OpenFOAM/OpenFOAM-*/etc/bashrc 2>/dev/null | tail -1; echo fin; "
           "lscpu -b -p=Core,Socket 2>/dev/null | grep -v '^#' | sort -u | wc -l")
    try:
        r = _ssh(host, cmd, timeout=25)
    except subprocess.TimeoutExpired:
        raise RemoteError(f"{host} no responde") from None
    if r.returncode != 0:
        raise RemoteError(f"No se pudo conectar a {host}: {r.stderr.strip()[-200:]}")
    v = r.stdout.split("\n")
    nucleos, carga = int(v[0]), float(v[1])
    # nproc cuenta hilos. Un i5-14500 da 20, y mpirun rechaza mas de sus 14 nucleos fisicos.
    tras_fin = v[v.index("fin") + 1:] if "fin" in v else []
    fisicos = int(tras_fin[0]) if tras_fin and tras_fin[0].strip().isdigit() and int(tras_fin[0]) > 0 else nucleos
    return {"host": host, "nucleos": nucleos, "fisicos": fisicos, "carga": carga,
            "libres": max(0, int(fisicos - carga)),
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
        except subprocess.TimeoutExpired as e:
            aviso = _aviso_tailscale(e.stdout) or _aviso_tailscale(e.stderr)
            raise RemoteError(aviso or f"{host} no responde") from None
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


def script_cola(ranuras: int) -> str:
    """Espera una ranura libre del servidor y corre el paquete en ella.

    Las ranuras son cerrojos flock en openblade_jobs: los comparten todos los paquetes
    de esa cuenta, se lancen desde la computadora que sea, y el sistema los suelta si el
    proceso muere. Mientras espera, status.json dice "en cola" con el grupo de procesos,
    asi que detenerlo funciona igual que con un paquete que ya corre.
    """
    return f"""echo '{{"state": "running", "step": "en cola", "rc": null, "pid": '$$', "pgid": '$$'}}' > status.json
trap 'grep -q "en cola" status.json && echo "{{\\"state\\": \\"stopped\\", \\"step\\": \\"en cola\\", \\"rc\\": 143}}" > status.json; exit 143' TERM INT
while :; do
  for k in $(seq 1 {int(ranuras)}); do
    flock -n -E 75 "$HOME/{JOBS_DIR}/.ranura_$k" python3 remote_job.py
    r=$?
    [ "$r" -ne 75 ] && exit "$r"
  done
  sleep 20
done
"""


def interpret_status(estado_txt: str, vivo: str, log: str) -> Dict[str, Any]:
    """Estado a partir de status.json, si su proceso sigue vivo y job.log."""
    try:
        est = json.loads(estado_txt)
    except ValueError:
        if estado_txt.strip():
            return {"state": "failed", "rc": 1, "step": "inicio",
                    "error": "status.json no se puede leer"}
        if log:
            return {"state": "failed", "rc": 1, "step": "inicio",
                    "error": f"El trabajo no arrancó: {log[-300:]}"}
        return {"state": "running", "step": "inicio"}
    if est.get("state") == "running" and vivo == "muerto":
        return dict(est, state="failed", rc=1,
                    error=f"El proceso del trabajo desapareció en el paso {est.get('step')}. {log[-200:]}".strip())
    return est


class RemoteJob:
    def __init__(self, host: str, job_dir: Optional[str] = None,
                 etiqueta: str = "caso", carpeta_propia: bool = False, ranuras: int = 0) -> None:
        self.host = validar_host(host)
        # Con ranuras > 0 la cola vive en el servidor: el paquete se sube ya y espera alli a
        # que haya una de las ranuras libre, aunque la computadora que lo lanzo se apague.
        self.ranuras = int(ranuras)
        self.carpeta_propia = carpeta_propia
        limpia = re.sub(r"[^A-Za-z0-9_.-]", "_", etiqueta)
        # El sufijo evita que dos lanzamientos en el mismo segundo compartan carpeta.
        self.job_dir = job_dir or (
            f"{JOBS_DIR}/{time.strftime('%Y%m%d_%H%M%S')}_{limpia}_{secrets.token_hex(2)}")
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", self.job_dir) or ".." in self.job_dir:
            raise RemoteError(f"Directorio de trabajo no valido: {self.job_dir}")
        self.offset = 0
        self.ficha_sha256 = None

    def _run(self, comando: str, timeout: int = 60) -> str:
        r = _ssh(self.host, f"cd ~/{self.job_dir} && {comando}", timeout=timeout)
        if r.returncode != 0:
            raise RemoteError(r.stderr.strip()[-300:] or f"rc={r.returncode}")
        return r.stdout

    def _rsync(self, origen: str, destino: str, excluir: List[str],
               intentos: int = INTENTOS_RSYNC, opts: Optional[List[str]] = None) -> None:
        """Copia con reintentos: un corte no debe perder un calculo ya hecho."""
        cmd = ["rsync", "-az", f"--timeout={TIEMPO_RSYNC}",
               "-e", "ssh " + " ".join(opts or SSH_OPTS_SUBIDA)]
        cmd += [f"--exclude={e}" for e in excluir] + [origen, destino]
        for intento in range(intentos):
            r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                               stdin=subprocess.DEVNULL)
            if r.returncode == 0:
                return
            time.sleep(min(ESPERA_RSYNC * (intento + 1), ESPERA_MAX_RSYNC))
        raise RemoteError("rsync: " + r.stderr.strip()[-300:])

    def subir(self, case_dir: str, msh_file: str, nproc: int, transient: bool,
              params: Dict[str, Any]) -> None:
        """Sube el paquete con su ficha, sin lanzarlo."""
        from core.package import FICHA, build_ficha, sha256_file

        # mkdir sin -p: si la carpeta ya existe es de otro trabajo y no se toca. Salvo que
        # sea de un intento anterior de este, que pudo crearla antes de cortarse la conexion.
        padre = os.path.dirname(self.job_dir)
        propia = self.carpeta_propia
        self.carpeta_propia = True
        r = _ssh(self.host, f"mkdir -p ~/{padre} && mkdir ~/{self.job_dir}")
        if r.returncode != 0 and not (propia and "File exists" in r.stderr):
            raise RemoteError(f"No se pudo crear el trabajo: {r.stderr.strip()[-200:]}")

        malla = os.path.join(case_dir, "mesh.msh")
        shutil.copy2(msh_file, malla)
        with open(os.path.join(case_dir, "job.json"), "w") as f:
            # max_iters: sin el, el servidor no sabe cuando podria recortar la corrida y
            # seguiria hasta el final aunque las fuerzas ya no cambien (remote_job.py).
            json.dump({"nproc": nproc, "transient": transient,
                       "max_iters": int(params.get("max_iters") or 0),
                       "sin_potencial": bool(params.get("campo_inicial"))}, f)
        shutil.copy2(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "remote_job.py"),
                     os.path.join(case_dir, "remote_job.py"))
        build_ficha(case_dir, params, msh_file)
        self.ficha_sha256 = sha256_file(os.path.join(case_dir, FICHA))
        try:
            self._rsync(case_dir.rstrip("/") + "/", f"{self.host}:{self.job_dir}/",
                        ["processor*", "*.log", "log.*", "*.foam"], opts=SSH_OPTS_SUBIDA)
        finally:
            for nombre in ("mesh.msh", "job.json", "remote_job.py"):
                ruta = os.path.join(case_dir, nombre)
                if os.path.exists(ruta):
                    os.remove(ruta)

    def lanzar(self) -> None:
        # Los parentesis importan: un "cd && x &" dejaria un subshell con la
        # salida conectada al canal y ssh no volveria hasta que acabe el trabajo.
        # set -C crea job.log solo si no existe: si la conexion se corta justo aqui y se
        # reintenta, el calculo no se lanza dos veces.
        orden = "python3 remote_job.py" if self.ranuras <= 0 else "bash cola.sh"
        if self.ranuras > 0:
            self._run(f"cat > cola.sh <<'FIN'\n{script_cola(self.ranuras)}FIN", timeout=30)
        self._run("if (set -C; : > job.log) 2>/dev/null; then "
                  f"(setsid nohup {orden} >> job.log 2>&1 < /dev/null &); fi",
                  timeout=30)

    def subir_y_lanzar(self, case_dir: str, msh_file: str, nproc: int, transient: bool,
                       params: Dict[str, Any]) -> None:
        self.subir(case_dir, msh_file, nproc, transient, params)
        self.lanzar()

    def comprobar_ficha(self, estado: Dict[str, Any]) -> None:
        """El servidor verifico la misma ficha que se envio."""
        huella = estado.get("ficha_sha256")
        if self.ficha_sha256 and huella and huella != self.ficha_sha256:
            raise FichaDistinta("La ficha del servidor no es la que se envió")

    def estado(self) -> Dict[str, Any]:
        """Estado del trabajo, comprobando que su proceso siga vivo.

        Si el servidor se reinicia o el proceso muere de golpe, status.json se queda
        en "running" para siempre y seguir el trabajo no terminaria nunca. Tampoco
        queda como "running" el que no llego a arrancar: job.log cuenta por que.
        """
        salida = self._run(
            'cat status.json 2>/dev/null; echo; echo ---P; '
            'p=$(grep -o \'"pid": [0-9]*\' status.json 2>/dev/null | grep -o "[0-9]*$"); '
            'if [ -n "$p" ]; then kill -0 "$p" 2>/dev/null && echo vivo || echo muerto; fi; '
            'echo ---L; tail -c 400 job.log 2>/dev/null; true', timeout=30)
        estado_txt, _, resto = salida.partition("---P\n")
        vivo, _, log = resto.partition("---L\n")
        return interpret_status(estado_txt, vivo.strip(), log.strip())

    def leer_log(self, maximo: int = 2_000_000) -> str:
        """Texto nuevo de run.log desde la ultima lectura.

        Si en una red lenta el trozo no llega a tiempo, se pide la mitad la vez siguiente:
        con un trozo fijo la lectura se agotaria siempre en el mismo sitio y no avanzaria.
        """
        bloque = min(maximo, getattr(self, "_bloque", maximo))
        try:
            salida = subprocess.run(
                ["ssh"] + SSH_OPTS + [
                    self.host,
                    f"tail -c +{self.offset + 1} ~/{self.job_dir}/run.log 2>/dev/null "
                    f"| head -c {bloque}"],
                capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
        except subprocess.TimeoutExpired as e:
            self._bloque = max(bloque // 2, BLOQUE_MINIMO)
            aviso = _aviso_tailscale(e.stdout) or _aviso_tailscale(e.stderr)
            if aviso:
                raise RemoteError(aviso) from None
            raise
        if salida.returncode != 0:
            raise RemoteError(salida.stderr.decode(errors="replace").strip()[-200:])
        self._bloque = min(bloque * 2, maximo)
        self.offset += len(salida.stdout)
        return salida.stdout.decode(errors="replace")

    def _senal(self, sig: str) -> None:
        estado = self.estado()
        pgid = estado.get("pgid")
        if not isinstance(pgid, int) or pgid <= 1:
            raise RemoteError("El trabajo aun no ha registrado su proceso")
        # Solo el grupo de este trabajo: nunca afecta a otras campanas.
        self._run(f"kill -{sig} -- -{pgid}", timeout=20)

    def terminar_en(self, iteracion: int) -> None:
        """Adelanta el final del calculo a esa iteracion: las fuerzas ya no cambian.

        El servidor decide lo mismo por su cuenta (core/remote_job.py), porque la Mac
        puede estar desconectada justo cuando convergen las fuerzas. Nunca se alarga:
        si alli ya se recorto mas, se deja como esta.
        """
        r = self._run("grep -m1 '^endTime' system/controlDict 2>/dev/null", timeout=30)
        actual = None
        for trozo in (r.stdout or "").replace(";", " ").split():
            try:
                actual = int(float(trozo))
            except ValueError:
                continue
        if actual is not None and actual <= int(iteracion):
            return
        self._run(f"sed -i 's/^endTime .*/endTime         {int(iteracion)};/' system/controlDict", timeout=30)

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
                    EXCLUIR_BAJADA, INTENTOS_DESCARGA, opts=SSH_OPTS_BAJADA)


    def limpiar(self) -> None:
        """Lo que solo hacia falta para calcular; la ficha y los resultados quedan."""
        self._run("rm -rf processor* mesh.msh", timeout=120)


def instantanea(host: str, caso: str) -> Dict[str, Any]:
    """Estado de un caso y del servidor. Allá basta el shell: nada se instala.

    Las fuerzas se traen en crudo y se leen aqui con el lector unico.
    """
    from core.forces import ForceDataError, ForceHistory, parse_force_lines, remote_tail_command
    from core.verdict import VENTANA, evaluate

    host = validar_host(host)
    if not re.fullmatch(r"[~A-Za-z0-9_./-]+", caso) or ".." in caso:
        raise RemoteError(f"Caso no valido: {caso}")
    r = _ssh(host, f"""cd {caso} 2>/dev/null || {{ echo sin-caso; exit 0; }}
cat status.json 2>/dev/null; echo; echo ---F
{remote_tail_command()}
echo ---L; tail -c 6000 run.log 2>/dev/null
echo ---E; grep -m1 -E '^endTime' system/controlDict 2>/dev/null; grep -m1 -E '^application' system/controlDict 2>/dev/null
echo ---S; cat /proc/loadavg; nproc; grep -E 'MemTotal|MemAvailable' /proc/meminfo
df -k . | tail -1; pgrep -c 'foamRun|simpleFoam|pimpleFoam'; true""", timeout=40)
    if r.returncode != 0:
        raise RemoteError(r.stderr.strip()[-200:] or f"rc={r.returncode}")
    salida = r.stdout
    if salida.startswith("sin-caso"):
        raise RemoteError(f"{caso} no existe en {host}")
    estado_txt, _, resto = salida.partition("---F\n")
    fuerzas_txt, _, resto = resto.partition("---L\n")
    log, _, resto = resto.partition("---E\n")
    fin_txt, _, servidor = resto.partition("---S\n")

    try:
        status = json.loads(estado_txt)
    except ValueError:
        status = {}
    d: Dict[str, Any] = {"caso": os.path.basename(caso.rstrip("/")), "status": status,
                         "error": status.get("error")}

    d["t"] = None
    tiempos = re.findall(r"^Time = ([-+0-9.eE]+)", log, re.M)
    if tiempos:
        d["t"] = float(tiempos[-1])
    d["residuales"] = {m.group(1): float(m.group(2)) for m in re.finditer(
        r"Solving for (\w+), Initial residual = ([-+0-9.eE]+)", log)}
    m = re.search(r"endTime\s+([0-9.eE+\-]+);", fin_txt)
    d["endTime"] = float(m.group(1)) if m else None
    d["estacionario"] = "simpleFoam" in fin_txt
    d["pct"] = 100.0 * d["t"] / d["endTime"] if d["t"] is not None and d["endTime"] else None

    d["coeffs"] = None
    d["veredicto"] = None
    try:
        columnas = parse_force_lines(fuerzas_txt.splitlines(), ("Time", "Cl", "Cd", "Cm"), caso)
        if columnas["Time"]:
            h = ForceHistory(columnas, [])
            paso = max(1, len(h) // 400)
            filas = list(zip(h.time, h.cd, h.cl))
            d["coeffs"] = {"t": h.time[-1], "Cd": h.cd[-1], "Cl": h.cl[-1], "n": len(h),
                           "serie": filas[-1::-paso][::-1]}
            if len(h) >= 2 * VENTANA:
                d["veredicto"] = evaluate(h).state
    except ForceDataError:
        pass

    v = servidor.split("\n")
    srv: Dict[str, Any] = {}
    try:
        carga = [float(x) for x in v[0].split()[:3]]
        nucleos = int(v[1])
        srv = {"carga": carga, "cores": nucleos, "cpu_pct": min(100.0, 100.0 * carga[0] / nucleos)}
        mem = {l.split(":")[0]: int(l.split()[1]) for l in v[2:4]}
        total, libre = mem["MemTotal"] / 2**20, mem["MemAvailable"] / 2**20
        srv.update(ram_total_gb=total, ram_usada_gb=total - libre,
                   ram_pct=100.0 * (total - libre) / total)
        srv["disco_libre_gb"] = int(v[4].split()[3]) / 2**20
        d["procesos"] = int(v[5])
    except (IndexError, ValueError, KeyError):
        d.setdefault("procesos", 0)
    d["servidor"] = srv
    return d


def resumen_servidor(host: str, horas: float = 48.0) -> Dict[str, Any]:
    """Carga del servidor y todos los casos de openblade_jobs tocados en esas horas, en una conexion."""
    host = validar_host(host)
    minutos = int(horas * 60)
    r = _ssh(host, f"""cat /proc/loadavg; nproc; grep -E 'MemTotal|MemAvailable' /proc/meminfo
pgrep -c 'foamRun|simpleFoam|pimpleFoam'; echo ---C
cd {JOBS_DIR} 2>/dev/null || exit 0
for d in $(find . -mindepth 1 -maxdepth 1 -type d -mmin -{minutos} | sort); do
  echo "@@ $d"; cat "$d/status.json" 2>/dev/null; echo
  grep -m1 -E '^endTime' "$d/system/controlDict" 2>/dev/null
  tail -c 3000 "$d/run.log" 2>/dev/null | grep -E '^Time = ' | tail -1
done; true""", timeout=40)
    if r.returncode != 0:
        raise RemoteError(r.stderr.strip()[-200:] or f"rc={r.returncode}")
    cabeza, _, casos_txt = r.stdout.partition("---C\n")
    v = cabeza.split("\n")
    srv: Dict[str, Any] = {}
    try:
        carga = [float(x) for x in v[0].split()[:3]]
        nucleos = int(v[1])
        mem = {l.split(":")[0]: int(l.split()[1]) for l in v[2:4]}
        total, libre = mem["MemTotal"] / 2**20, mem["MemAvailable"] / 2**20
        srv = {"carga": carga[0], "cpu_pct": min(100.0, 100.0 * carga[0] / nucleos),
               "ram_pct": 100.0 * (total - libre) / total, "procesos": int(v[4])}
    except (IndexError, ValueError, KeyError):
        pass
    casos = []
    for bloque in casos_txt.split("@@ ")[1:]:
        lineas = bloque.split("\n")
        nombre = lineas[0].strip().lstrip("./")
        resto = "\n".join(lineas[1:])
        try:
            estado = json.loads(lineas[1]) if lineas[1].strip() else {}
        except ValueError:
            estado = {}
        fin = re.search(r"endTime\s+([0-9.eE+\-]+);", resto)
        t = re.findall(r"^Time = ([-+0-9.eE]+)", resto, re.M)
        caso = {"caso": nombre, "ruta": f"~/{JOBS_DIR}/{nombre}", "estado": estado.get("state"),
                "paso": estado.get("step"), "t": float(t[-1]) if t else None,
                "fin": float(fin.group(1)) if fin else None}
        caso["pct"] = 100.0 * caso["t"] / caso["fin"] if caso["t"] is not None and caso["fin"] else None
        casos.append(caso)
    return {"host": host, "servidor": srv, "casos": casos}


def friendly_error(texto: str) -> str:
    """Lo que se le dice al usuario cuando la conexion falla, sin la orden ssh entera."""
    t = texto or ""
    if "login.tailscale.com" in t:
        enlace = re.search(r"https://login\.tailscale\.com/\S+", t)
        return "Tailscale pide autenticarse" + (f": abre {enlace.group(0)}" if enlace else "")
    if "timed out" in t.lower() or "no responde" in t:
        return "Sin respuesta del servidor; se reintenta solo"
    if "Permission denied" in t:
        return "El servidor no acepta la clave SSH"
    if "Could not resolve" in t or "No route" in t:
        return "No se encuentra el servidor en la red"
    return t.strip().splitlines()[-1][:160] if t.strip() else "Sin respuesta"


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
