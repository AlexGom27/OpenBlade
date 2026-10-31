#!/usr/bin/env python3
"""Trabajo de OpenFOAM que corre EN EL SERVIDOR, desacoplado de la GUI.

remote_runner.py lo sube junto al caso y lo lanza con setsid, asi que sigue
corriendo aunque se cierre la app o se corte la red. Solo usa la biblioteca
estandar: el servidor no necesita tener instalado OpenBlade.

Lee job.json del directorio actual y deja su estado en status.json. Antes de
calcular comprueba el paquete contra ficha.json y rechaza uno alterado.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

BASHRC = ("/opt/openfoam*/etc/bashrc", "/usr/lib/openfoam/openfoam*/etc/bashrc",
          "/opt/OpenFOAM/OpenFOAM-*/etc/bashrc")
ESTADO = {"state": "running", "step": "inicio", "rc": None}


def guardar_estado(**cambios):
    ESTADO.update(cambios, updated=time.time())
    tmp = "status.json.tmp"
    with open(tmp, "w") as f:
        json.dump(ESTADO, f)
    os.replace(tmp, "status.json")


def _sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def verificar_paquete():
    """Compara cada archivo con la ficha. Devuelve el sha256 de la ficha."""
    if not os.path.exists("ficha.json"):
        raise RuntimeError("Paquete rechazado: no trae ficha.json")
    huella = _sha256("ficha.json")
    with open("ficha.json") as f:
        esperados = json.load(f)["archivos"]
    malos = []
    for ruta, sha in esperados.items():
        if not os.path.exists(ruta):
            malos.append(f"{ruta} (falta)")
        elif _sha256(ruta) != sha:
            malos.append(f"{ruta} (cambió)")
    for carpeta in ("0", "constant", "system"):
        for base, dirs, nombres in os.walk(carpeta):
            if base == "constant":
                dirs[:] = [d for d in dirs if d != "polyMesh"]
            malos += [f"{os.path.join(base, n)} (sobra)" for n in nombres
                      if os.path.join(base, n).replace(os.sep, "/") not in esperados]
    if malos:
        raise RuntimeError("Paquete alterado, no se calcula: " + ", ".join(sorted(malos)[:6]))
    return huella


def env_foam():
    if shutil.which("foamRun") or shutil.which("simpleFoam"):
        return os.environ.copy()
    candidatos = [c for patron in BASHRC for c in sorted(glob.glob(patron))]
    if not candidatos:
        raise RuntimeError("No se encontro una instalacion de OpenFOAM")
    r = subprocess.run(["bash", "-c", f"source '{candidatos[-1]}' >/dev/null 2>&1; env -0"],
                       capture_output=True, text=True, check=True)
    env = {}
    for par in r.stdout.split("\0"):
        if "=" in par:
            k, v = par.split("=", 1)
            env[k] = v
    return env


def correr(cmd, env, log, obligatorio=True):
    with open(log, "w") as fh:
        rc = subprocess.run(cmd, env=env, stdout=fh, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL).returncode
    if rc != 0 and obligatorio:
        raise RuntimeError(f"{cmd[0]} fallo (rc={rc}), revisa {log}")
    return rc


def ajustar_boundary():
    ruta = os.path.join("constant", "polyMesh", "boundary")
    t = open(ruta).read()
    for nombre, tipo in (("frontAndBack", "empty"), ("defaultFaces", "empty"),
                         ("airfoil", "wall")):
        t = re.sub(r"(" + nombre + r"\s*\{[^}]*?type\s+)\w+(\s*;)",
                   r"\g<1>" + tipo + r"\g<2>", t, count=1, flags=re.S)
    open(ruta, "w").write(t)


def comando_solver(job, env):
    """foamRun en OpenFOAM >= 11; simpleFoam/pimpleFoam en las demas."""
    if shutil.which("foamRun", path=env.get("PATH")):
        return ["foamRun", "-solver", "incompressibleFluid"]
    return ["pimpleFoam" if job.get("transient") else "simpleFoam"]


def al_terminar(_sig, _frame):
    # El TERM llega a todo el grupo (mpirun incluido): basta con registrarlo.
    guardar_estado(state="stopped", rc=143)
    sys.exit(143)


def main():
    job = json.load(open("job.json"))
    nproc = int(job.get("nproc", 1))
    signal.signal(signal.SIGTERM, al_terminar)
    guardar_estado(pid=os.getpid(), pgid=os.getpgid(0))

    try:
        guardar_estado(step="verificando")
        guardar_estado(ficha_sha256=verificar_paquete())
        env = env_foam()
        guardar_estado(step="gmshToFoam")
        correr(["gmshToFoam", "mesh.msh"], env, "log.gmshToFoam")
        ajustar_boundary()
        guardar_estado(step="checkMesh")
        correr(["checkMesh", "-noFunctionObjects"], env, "log.checkMesh", obligatorio=False)

        # Igual que en local: si falla, la simulacion aun puede continuar.
        guardar_estado(step="potentialFoam")
        correr(["potentialFoam", "-writep"], env, "log.potentialFoam",
               obligatorio=False)

        cmd = comando_solver(job, env)
        if nproc > 1:
            guardar_estado(step="decomposePar")
            with open(os.path.join("system", "decomposeParDict"), "w") as f:
                f.write("FoamFile { version 2.0; format ascii; class dictionary; "
                        f"object decomposeParDict; }}\nnumberOfSubdomains {nproc};\n"
                        "method scotch;\n")
            correr(["decomposePar", "-force"], env, "log.decomposePar")
            # --bind-to none: puede haber otras campanas en el servidor y un
            # segundo mpirun no debe fijarse a sus mismos nucleos.
            cmd = ["mpirun", "--bind-to", "none", "-np", str(nproc)] + cmd + ["-parallel"]

        guardar_estado(step="solver")
        rc = correr(cmd, env, "run.log", obligatorio=False)
        if rc == 0 and nproc > 1:
            guardar_estado(step="reconstructPar")
            extra = [] if job.get("transient") else ["-latestTime"]
            correr(["reconstructPar"] + extra, env, "log.reconstructPar")
        guardar_estado(state="done" if rc == 0 else "failed", rc=rc, step="fin")
    except Exception as e:  # noqa: BLE001
        guardar_estado(state="failed", rc=1, error=str(e)[:400])
        sys.exit(1)


if __name__ == "__main__":
    main()
