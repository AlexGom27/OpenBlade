"""Ficha del paquete: lo que hace comprobable una simulacion.

Antes de enviar un caso se escribe ficha.json con el sha256 de la malla y de
cada diccionario, las versiones y los parametros. El trabajo la verifica en el
servidor antes de calcular (core/remote_job.py) y rechaza un paquete alterado.
Al terminar se le agregan la ejecucion, checkMesh y el resultado.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import time
from typing import Any, Dict, List, Optional

FICHA = "ficha.json"
# Lo que define el calculo. La malla de polyMesh sale de mesh.msh en el servidor.
CARPETAS = ("0", "constant", "system")
OMITIR = (os.path.join("constant", "polyMesh"),)
# Lo que no cambia la fisica y no debe confundir al comparar dos fichas.
PARAMETROS_AJENOS = ("exec_mode", "server_host", "server_nproc", "native_foam")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sha256_file(ruta: str) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def package_files(case_dir: str) -> List[str]:
    """Archivos del paquete, relativos al caso y en orden estable."""
    archivos = []
    for carpeta in CARPETAS:
        for base, dirs, nombres in os.walk(os.path.join(case_dir, carpeta)):
            relativa = os.path.relpath(base, case_dir)
            dirs[:] = sorted(d for d in dirs if os.path.join(relativa, d) not in OMITIR)
            archivos += [os.path.join(relativa, n).replace(os.sep, "/") for n in sorted(nombres)]
    return archivos


def _version(paquete: str) -> Optional[str]:
    from importlib import metadata
    try:
        return metadata.version(paquete)
    except metadata.PackageNotFoundError:
        return None


def program_version() -> Dict[str, Any]:
    """Commit del programa y si la copia de trabajo tiene cambios sin guardar."""
    try:
        commit = subprocess.run(["git", "-C", RAIZ, "rev-parse", "HEAD"], capture_output=True,
                                text=True, stdin=subprocess.DEVNULL, timeout=20)
        estado = subprocess.run(["git", "-C", RAIZ, "status", "--porcelain", "--", "core", "gui"],
                                capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "modificados": []}
    if commit.returncode != 0:
        return {"commit": None, "modificados": []}
    return {"commit": commit.stdout.strip(),
            "modificados": [l[3:] for l in estado.stdout.splitlines()]}


def build_ficha(case_dir: str, params: Dict[str, Any],
                msh_file: Optional[str] = None) -> Dict[str, Any]:
    """Escribe ficha.json con el contenido actual del paquete."""
    archivos = {r: sha256_file(os.path.join(case_dir, r)) for r in package_files(case_dir)}
    for extra in ("mesh.msh", "job.json", "remote_job.py"):
        if os.path.exists(os.path.join(case_dir, extra)):
            archivos[extra] = sha256_file(os.path.join(case_dir, extra))
    ficha = {
        "esquema": 1,
        "creada": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "programa": program_version(),
        "versiones": {"python": platform.python_version(),
                      "gmsh": _version("gmsh"),
                      "gmshairfoil2d": _version("gmshairfoil2d"),
                      "numpy": _version("numpy")},
        "plataforma": platform.platform(),
        "parametros": {k: v for k, v in params.items()
                       if k not in PARAMETROS_AJENOS and not k.startswith("fsi_")},
        "malla": read_mesh_info(msh_file) if msh_file else None,
        "archivos": archivos,
    }
    write_ficha(case_dir, ficha)
    return ficha


def read_mesh_info(msh_file: str) -> Optional[Dict[str, Any]]:
    """Lo que mesh_script dejo junto a la malla: con que metodo se genero."""
    try:
        with open(msh_file + ".info.json") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_ficha(case_dir: str, ficha: Dict[str, Any]) -> None:
    with open(os.path.join(case_dir, FICHA), "w") as f:
        json.dump(ficha, f, indent=1, ensure_ascii=False, sort_keys=True)


def read_ficha(case_dir: str) -> Optional[Dict[str, Any]]:
    try:
        with open(os.path.join(case_dir, FICHA)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def parse_checkmesh(texto: str) -> Dict[str, Any]:
    """Lo que importa de la salida de checkMesh."""
    def numero(patron: str, tipo=float):
        m = re.search(patron.replace("NUM", r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"), texto)
        return tipo(m.group(1)) if m else None

    ok = re.search(r"^Mesh OK\.", texto, re.M) is not None
    return {
        "ok": ok,
        "fallos": numero(r"Failed NUM mesh checks", int) or 0,
        "celdas": numero(r"(?m)^\s*cells:\s+NUM", int),
        "aspecto_max": numero(r"[Mm]ax aspect ratio\s*[:=]\s*NUM"),
        "no_ortogonalidad_max": numero(r"non-orthogonality Max:\s*NUM"),
        "no_ortogonalidad_media": numero(r"non-orthogonality Max:\s*\S+ average:\s*NUM"),
        "caras_no_ortogonales": numero(r"severely non-orthogonal \(> 70 degrees\) faces:\s*NUM", int) or 0,
        "sesgo_max": numero(r"Max skewness = NUM"),
        "volumen_min": numero(r"Min volume = NUM"),
        "caja": (re.search(r"bounding box (\(.*?\) \(.*?\))", texto) or [None, None])[1],
        "solo_aspecto": _solo_aspecto(texto),
    }


def _solo_aspecto(texto: str) -> bool:
    """El unico fallo de checkMesh es el aspecto de las celdas."""
    fallos = re.findall(r"^\s*\*\*\*(.*)$", texto, re.M)
    return len(fallos) == 1 and "aspect ratio" in fallos[0]


def mesh_notice(cm: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Nivel y texto de checkMesh para el usuario."""
    if not cm:
        return None
    datos = (f"{cm['celdas']} celdas, no ortogonalidad máx {cm['no_ortogonalidad_max']:.1f}°, "
             f"sesgo máx {cm['sesgo_max']:.2f}")
    if cm["volumen_min"] is not None and cm["volumen_min"] <= 0:
        return {"level": "mal", "text": f"Malla con volúmenes negativos. {datos}"}
    # Celdas muy alargadas son normales en una capa límite con y+ ~ 1.
    if cm["fallos"] > (1 if cm.get("solo_aspecto") else 0):
        return {"level": "mal", "text": f"checkMesh: {cm['fallos']} comprobaciones fallidas. {datos}"}
    if cm["caras_no_ortogonales"]:
        return {"level": "aviso", "text": f"Malla: {cm['caras_no_ortogonales']} caras con "
                                          f"no ortogonalidad > 70°. {datos}"}
    return {"level": "ok", "text": f"Malla: {datos}"}


def _cabecera_foam(ruta: str) -> Dict[str, str]:
    """Build, maquina y procesos de la cabecera de un log de OpenFOAM."""
    datos: Dict[str, str] = {}
    try:
        with open(ruta, errors="replace") as f:
            for _ in range(40):
                m = re.match(r"^(Build|Host|nProcs)\s*:\s*\"?([^\"\n]+)\"?", f.readline())
                if m:
                    datos[m.group(1)] = m.group(2).strip()
    except OSError:
        pass
    return datos


def complete_ficha(case_dir: str, analisis: Dict[str, Any], rc: int = 0,
                   host: str = "", job_dir: str = "") -> Optional[Dict[str, Any]]:
    """Agrega a la ficha la ejecucion, checkMesh y el resultado de la corrida."""
    ficha = read_ficha(case_dir)
    if ficha is None:
        return None
    cabecera = _cabecera_foam(os.path.join(case_dir, "run.log"))
    ficha["ejecucion"] = {"maquina": host or cabecera.get("Host"), "trabajo": job_dir, "rc": rc,
                          "openfoam_build": cabecera.get("Build"),
                          "procesos": cabecera.get("nProcs", "1"),
                          "host_openfoam": cabecera.get("Host"),
                          "terminada": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    log = os.path.join(case_dir, "log.checkMesh")
    if os.path.exists(log):
        with open(log, errors="replace") as f:
            ficha["checkmesh"] = parse_checkmesh(f.read())
    from core.forces import find_force_files
    fuerzas = find_force_files(case_dir)
    ficha["fuerzas_sha256"] = {os.path.relpath(r, case_dir): sha256_file(r) for r in fuerzas}
    ficha["resultado"] = analisis
    write_ficha(case_dir, ficha)
    return ficha
