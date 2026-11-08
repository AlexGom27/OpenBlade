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


# --- cuando terminar, aqui mismo ------------------------------------------------
# Antes lo decidia la Mac leyendo run.log mientras estaba conectada. Con la maquina
# inalcanzable (Tailscale caido 2 h 13 min en el 6e6) nadie veia la convergencia y el
# solver seguia hasta max_iters: a 0 grados, una maquina acabo en 16000 y la otra en
# 40000, con las fuerzas identicas hasta donde coinciden. El caso de control exige el
# mismo archivo en las dos maquinas, asi que la decision no puede depender de la red.

def _re_veces(nombre):
    return re.compile(r"^\s*" + nombre + r"\s*[:=]\s*([0-9eE.+\-]+)\s*$")


_RE_FUERZA = {n: _re_veces(n) for n in ("Cd", "Cl")}
# Mismos valores que core.jobs._Vigilancia: si aqui y alli discrepan, el mismo paquete
# daria un final distinto segun quien lo pare.
CADA_CONVERGENCIA = 1000
MARGEN = 2000
MINIMO = 1000
VENTANA = 500
TOL_RANGO_CD = 0.008
TOL_RANGO_CL = 0.005
TOL_DERIVA_CD = 0.002
TOL_DERIVA_CL = 0.001
FRACCION_TRAMO = 10


def _tramo_final(x):
    """Media del ultimo tramo y del anterior, igual que core.verdict.tramo_final."""
    n = len(x)
    w = min(max(VENTANA, n // FRACCION_TRAMO), n // 2)
    if w < 1:
        return None, None
    return sum(x[n - w:]) / w, sum(x[n - 2 * w:n - w]) / w


class _Convergencia:
    """Lo mismo que core.jobs._Vigilancia, sin depender de OpenBlade."""

    def __init__(self):
        self.n = 0
        self.cl = []
        self.cd = []

    def final_previsto(self):
        return (self.n // CADA_CONVERGENCIA + 1) * CADA_CONVERGENCIA + MARGEN

    def convergio(self):
        if self.n % CADA_CONVERGENCIA or self.n < MINIMO:
            return False
        ultimo_cd, ultimo_cl = self.cd[-VENTANA:], self.cl[-VENTANA:]
        if len(ultimo_cd) < VENTANA or len(ultimo_cl) < VENTANA:
            return False
        media_cd = sum(ultimo_cd) / VENTANA
        media_cl = sum(ultimo_cl) / VENTANA
        if media_cd <= 0 or (max(ultimo_cd) - min(ultimo_cd)) / media_cd >= TOL_RANGO_CD:
            return False
        if max(ultimo_cl) - min(ultimo_cl) >= max(TOL_RANGO_CL * abs(media_cl), 2e-4):
            return False
        reciente, previo = _tramo_final(self.cd)
        if reciente is None or abs(reciente - previo) / media_cd >= TOL_DERIVA_CD:
            return False
        reciente, previo = _tramo_final(self.cl)
        return reciente is not None and abs(reciente - previo) < TOL_DERIVA_CL * max(abs(media_cl), 0.1)


def correr_vigilado(cmd, env, log, max_iters, transient):
    """Corre el solver y, en paralelo, mira si ya convergio para acortarlo."""
    import threading

    with open(log, "w") as fh:
        proceso = subprocess.Popen(cmd, env=env, stdout=fh, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL)
        # En transitorio manda el tiempo fisico, no las vueltas: no se recorta.
        if max_iters > 0 and not transient:
            hilo = threading.Thread(target=vigilar_y_parar, args=(proceso, max_iters),
                                    daemon=True)
            hilo.start()
        rc = proceso.wait()
    return rc


def vigilar_y_parar(proceso, max_iters):
    """Sigue run.log mientras el solver corre y adelanta su final si converge.

    Se llama desde un hilo aparte: el solver no se entera de nada hasta que se le
    reescribe endTime, y entonces OpenFOAM termina solo, escribiendo sus campos.
    """
    vigia = _Convergencia()
    posicion = 0
    resto = ""
    while proceso.poll() is None:
        time.sleep(2.0)
        try:
            with open("run.log", errors="replace") as f:
                f.seek(posicion)
                datos = f.read()
                posicion = f.tell()
        except OSError:
            continue
        if not datos:
            continue
        for linea in (resto + datos).split("\n")[:-1]:
            for nombre, patron in _RE_FUERZA.items():
                m = patron.match(linea)
                if not m:
                    continue
                try:
                    valor = float(m.group(1))
                except ValueError:
                    continue
                if nombre == "Cl":
                    vigia.cl.append(valor)
                    vigia.n += 1
                else:
                    vigia.cd.append(valor)
            if vigia.n and vigia.n % 100 == 0 and vigia.convergio():
                final = vigia.final_previsto()
                if final >= max_iters:
                    return
                recortar_final(final)
                guardar_estado(convergio_en=vigia.n, final=final)
                return
        resto = (resto + datos).split("\n")[-1]


def recortar_final(iteracion):
    """Adelanta endTime del controlDict: OpenFOAM termina solo, sin matarlo."""
    ruta = os.path.join("system", "controlDict")
    t = open(ruta).read()
    nuevo = re.sub(r"^endTime\s+.*$", f"endTime         {int(iteracion)};", t, count=1, flags=re.M)
    open(ruta, "w").write(nuevo)


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


class Detenido(Exception):
    pass


def al_terminar(_sig, _frame):
    # El TERM llega a todo el grupo (mpirun incluido): basta con registrarlo.
    raise Detenido()


def main():
    job = json.load(open("job.json"))
    nproc = int(job.get("nproc", 1))
    signal.signal(signal.SIGTERM, al_terminar)
    guardar_estado(pid=os.getpid(), pgid=os.getpgid(0))
    env = None

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
        # Si el caso arranca del campo de otra corrida, no hay que pisarlo.
        if not job.get("sin_potencial"):
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
            # --oversubscribe: sin el, mpirun rechaza mas procesos que nucleos fisicos, aunque
            # los pida quien sabe que hay hilos libres. Ira mas lento, pero no se pierde el envio.
            cmd = ["mpirun", "--bind-to", "none", "--oversubscribe", "-np", str(nproc)] + cmd + ["-parallel"]

        guardar_estado(step="solver")
        rc = correr_vigilado(cmd, env, "run.log", int(job.get("max_iters", 0)),
                             bool(job.get("transient")))
        # El calculo ya acabo: lo que queda no se interrumpe a medias.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if rc == 0 and nproc > 1:
            guardar_estado(step="reconstructPar")
            extra = [] if job.get("transient") else ["-latestTime"]
            correr(["reconstructPar"] + extra, env, "log.reconstructPar")
        if rc == 0:
            guardar_estado(state="done", rc=0, step="fin")
        else:
            # Lo que dijo el solver: sin esto solo se veia "SIN DATOS".
            with open("run.log", errors="replace") as f:
                cola = f.read()[-300:]
            guardar_estado(state="failed", rc=rc, step="fin", error=f"El solver terminó con código {rc}: {cola}")
    except Detenido:
        # Lo calculado hasta aqui tambien se quiere ver: sin esto quedaba en processor*,
        # que no se descarga, y una corrida detenida no tenia campos.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if env is not None and nproc > 1 and os.path.isdir("processor0"):
            extra = [] if job.get("transient") else ["-latestTime"]
            guardar_estado(step="reconstructPar")
            correr(["reconstructPar"] + extra, env, "log.reconstructPar", obligatorio=False)
        guardar_estado(state="stopped", rc=143)
        sys.exit(143)
    except Exception as e:  # noqa: BLE001
        guardar_estado(state="failed", rc=1, error=str(e)[:400])
        sys.exit(1)


if __name__ == "__main__":
    main()
