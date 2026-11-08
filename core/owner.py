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

import json
import os
import socket
import subprocess
import time
from typing import Any, Dict, Optional

ARCHIVO = "dueno.json"


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


def de_otro(job) -> Optional[Dict[str, Any]]:
    """Dueno vivo que no es este proceso, o None si el trabajo esta libre."""
    d = leer(job)
    if not d or not vivo(d):
        return None
    if d.get("pid") == os.getpid() and d.get("maquina") == MAQUINA:
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
        if "core.cli" not in linea:
            continue
        try:
            pid = int(linea.split(None, 1)[0])
        except (IndexError, ValueError):
            continue
        if pid != os.getpid() and _existe(pid):
            return True
    return False


def describir(dueno: Dict[str, Any]) -> str:
    return f"lo lleva otro proceso (pid {dueno.get('pid')} en {dueno.get('maquina')})"


def reclamar(job) -> Dict[str, Any]:
    """Toma el trabajo. Falla si lo lleva otro proceso vivo."""
    otro = de_otro(job)
    if otro is not None:
        raise OwnerError(f"{job.label}: {describir(otro)}")
    d = yo()
    os.makedirs(job.folder, exist_ok=True)
    tmp = _ruta(job) + ".tmp"
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
