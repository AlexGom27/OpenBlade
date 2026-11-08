"""De quien es cada trabajo: un solo proceso lo lleva a la vez.

La ventana y la linea de comandos (`python3 -m core.cli polar|banco|control`)
comparten `~/.openblade/jobs`. Si los dos creen que un trabajo es suyo, el
paquete se envia dos veces, corre dos veces y los dos procesos descargan y
escriben el mismo `job.json`.

Cada trabajo deja su dueno en `<trabajo>/dueno.json`: pid, maquina y hora de
arranque del proceso. Se puede retomar cuando ese proceso ya no existe. El pid
solo no basta, porque el sistema los reutiliza: por eso se compara tambien la
hora de arranque.

Si el dueno dice ser de otra maquina no se puede comprobar desde aqui (el
directorio de datos es local, asi que solo pasa si alguien copio la carpeta).
En ese caso se trata como libre y quien lo retoma lo anota.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import socket
import subprocess
import time
from typing import Any, Dict, Optional

ARCHIVO = "dueno.json"
# Subcomandos que llevan trabajos: son los unicos que pueden tener uno en curso.
LLEVAN_TRABAJOS = ("polar", "banco", "control")
CANDADO = "dueno.lock"
CANDADO_VIEJO = 30.0      # s: mas que esto dentro de la seccion critica = proceso muerto
ESPERA_CANDADO = 2.0      # s: lo que se espera a que el otro acabe de anotar


def _maquina() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return ""


MAQUINA = _maquina()


class OwnerError(RuntimeError):
    """El trabajo lo lleva otro proceso que sigue vivo."""


def _arranque(pid: int) -> Optional[float]:
    """Hora de arranque del proceso, para distinguirlo de otro con el mismo pid."""
    if os.name == "nt":
        return None
    try:
        salida = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                                capture_output=True, text=True, timeout=5,
                                stdin=subprocess.DEVNULL,
                                env={**os.environ, "LC_ALL": "C", "LANG": "C"})
    except (OSError, subprocess.SubprocessError):
        return None
    texto = " ".join(salida.stdout.split())
    if salida.returncode != 0 or not texto:
        return None
    try:
        return time.mktime(time.strptime(texto, "%a %b %d %H:%M:%S %Y"))
    except ValueError:
        return None


def yo() -> Dict[str, Any]:
    """Lo que este proceso escribe como dueno."""
    pid = os.getpid()
    return {"pid": pid, "maquina": MAQUINA, "arranque": _arranque(pid), "desde": time.time()}


def _existe(pid: int) -> bool:
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except (AttributeError, OSError):
            return False
    try:
        os.kill(pid, 0)          # en POSIX, la senal 0 solo comprueba
    except ProcessLookupError:
        return False
    except PermissionError:
        return True              # existe, pero es de otro usuario
    except OSError:
        return False
    return True


def vivo(dueno: Optional[Dict[str, Any]]) -> bool:
    """Si el proceso que figura como dueno sigue existiendo."""
    if not dueno:
        return False
    if dueno.get("maquina") != MAQUINA:
        return False
    pid = dueno.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if not _existe(pid):
        return False
    arranque = dueno.get("arranque")
    if arranque is None:
        return True              # no se pudo leer: el pid vivo es lo unico que hay
    actual = _arranque(pid)
    if actual is None:
        return True
    return abs(actual - float(arranque)) <= 1.0


def _ruta(job) -> str:
    return os.path.join(job.folder, ARCHIVO)


def leer(job) -> Optional[Dict[str, Any]]:
    """Dueno anotado, o None si el trabajo no tiene ninguno."""
    try:
        with open(_ruta(job)) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def es_mio(dueno: Optional[Dict[str, Any]]) -> bool:
    """Si el dueno anotado es este mismo proceso."""
    return bool(dueno) and dueno.get("pid") == os.getpid() and dueno.get("maquina") == MAQUINA


def de_otro(job) -> Optional[Dict[str, Any]]:
    """Dueno vivo que no es este proceso, o None si el trabajo esta libre."""
    d = leer(job)
    if not d or not vivo(d) or es_mio(d):
        return None
    return d


def hay_cli_vivo() -> bool:
    """Si hay un `python3 -m core.cli ...` vivo que pueda estar llevando trabajos.

    Los trabajos lanzados antes de que existiera el archivo de dueno no lo
    tienen. Con un proceso de la linea de ordenes vivo no se puede saber si
    alguno es suyo, asi que se avisa en vez de reenviar a ciegas.
    """
    if os.name == "nt":
        return False
    try:
        salida = subprocess.run(["ps", "-Ao", "pid=,command="], capture_output=True,
                                text=True, timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    for linea in salida.stdout.splitlines():
        trozos = linea.split()
        if len(trozos) < 3:
            continue
        # Tiene que ser un interprete Python: si no, el texto de un `sh -c` o de un editor
        # que mencione el comando contaria como campana viva.
        if not os.path.basename(trozos[1]).lower().startswith("python"):
            continue
        # `doctor`, `estado` y demas no llevan trabajos: no bloquean nada.
        resto = " ".join(trozos[1:])
        if not any(re.search(rf"-m\s+core\.cli\s+{c}\b", resto) for c in LLEVAN_TRABAJOS):
            continue
        try:
            pid = int(trozos[0])
        except ValueError:
            continue
        if pid != os.getpid() and _existe(pid):
            return True
    return False


def describir(dueno: Dict[str, Any]) -> str:
    return f"lo lleva otro proceso (pid {dueno.get('pid')} en {dueno.get('maquina')})"


@contextlib.contextmanager
def _candado(job):
    """Deja pasar a un solo proceso a la vez por comprobar-y-anotar.

    Sin esto, dos procesos que retoman a la vez leen "libre" los dos y los dos se
    anotan: el paquete corre dos veces, que es justo lo que el archivo de dueno
    viene a evitar. La seccion critica son microsegundos, asi que un candado de
    mas de CANDADO_VIEJO segundos es de un proceso que murio dentro de ella.
    """
    ruta = os.path.join(job.folder, CANDADO)
    arranque = time.time()
    while True:
        try:
            fd = os.open(ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            try:
                viejo = time.time() - os.stat(ruta).st_mtime > CANDADO_VIEJO
            except OSError:
                viejo = False        # se libero mientras mirábamos: se reintenta
            if viejo:
                try:
                    os.remove(ruta)
                except OSError:
                    pass
                continue
            if time.time() - arranque > ESPERA_CANDADO:
                raise OwnerError(f"{job.label}: otro proceso lo esta tomando ahora mismo") from None
            time.sleep(0.01)
    marca = f"{os.getpid()}:{time.time()}"
    try:
        os.write(fd, marca.encode())
        yield
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        # Solo se quita el candado propio: si otro lo dio por muerto y creo el suyo,
        # el de el no se toca.
        try:
            with open(ruta) as f:
                sigue_siendo_mio = f.read() == marca
        except OSError:
            sigue_siendo_mio = False
        if sigue_siendo_mio:
            try:
                os.remove(ruta)
            except OSError:
                pass


def reclamar(job) -> Dict[str, Any]:
    """Toma el trabajo. Falla si lo lleva otro proceso vivo.

    Comprobar y anotar van bajo el candado: si no, dos procesos que retoman a la
    vez pasan los dos por "libre" y los dos se creen duenos.
    """
    os.makedirs(job.folder, exist_ok=True)
    with _candado(job):
        otro = de_otro(job)
        if otro is not None:
            raise OwnerError(f"{job.label}: {describir(otro)}")
        d = yo()
        tmp = _ruta(job) + f".{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, _ruta(job))
    return d


def liberar(job) -> None:
    """Suelta el trabajo, si es este proceso el que lo lleva."""
    d = leer(job)
    if d is None:
        return
    if d.get("pid") != os.getpid() or d.get("maquina") != MAQUINA:
        return
    try:
        os.remove(_ruta(job))
    except OSError:
        pass
