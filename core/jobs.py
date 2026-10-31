"""Trabajos: cada simulacion es un paquete con su propia carpeta.

    <datos>/jobs/<id>/job.json    estado del trabajo
    <datos>/jobs/<id>/case/       caso de OpenFOAM, ficha y resultados

La malla y el caso se generan en esta maquina; el calculo corre donde diga el
trabajo (Local o un servidor). El Dispatcher reparte los pendientes entre las
maquinas sin pasar de los procesos de cada una. No depende de Qt: lo usan la
ventana, la linea de comandos y el banco de validacion.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core import paths
from core.remote_runner import FichaDistinta, LogParser, RemoteError, RemoteJob

PENDIENTE = "pendiente"
MALLANDO = "mallando"
PREPARANDO = "preparando"
SUBIENDO = "subiendo"
CORRIENDO = "corriendo"
DESCARGANDO = "descargando"
TERMINADO = "terminado"
FALLIDO = "fallido"
DETENIDO = "detenido"
ACTIVOS = (MALLANDO, PREPARANDO, SUBIENDO, CORRIENDO, DESCARGANDO)
FINALES = (TERMINADO, FALLIDO, DETENIDO)

LOCAL = "local"
RC_DETENIDA = 143
MAX_FALLOS = 2000       # intentos sin respuesta antes de dejar de seguirlo: horas
ARRANQUE_MAX = 600.0    # segundos que puede tardar un trabajo lanzado en dar señales de vida
# Lo que define la malla. Con los mismos valores se reutiliza el mismo archivo:
# dos paquetes del mismo caso llevan exactamente la misma malla.
CLAVES_MALLA = ("profile_type", "naca", "chord", "aoa", "mesh_size_min", "mesh_size_max",
                "bl_dist_min", "mesh_growth_rate", "mesh_num_layers", "wake_length", "farfield",
                "nb_airfoil_pts", "depth", "mesh_strategy", "bl_fraction", "bl_total_height",
                "bl_growth_dist", "wake_incline", "wake_points", "surface_points", "normal_points",
                "mesher", "grid_level", "yplus_target", "mesh_file")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class JobError(RuntimeError):
    pass


def jobs_dir() -> str:
    d = os.path.join(paths.data_root(), "jobs")
    os.makedirs(d, exist_ok=True)
    return d


@dataclass
class Job:
    id: str
    label: str
    params: Dict[str, Any]
    host: str = ""              # "" = la primera maquina libre
    nproc: int = 0              # 0 = los de la maquina
    group: str = ""
    state: str = PENDIENTE
    step: str = ""
    remote_dir: str = ""
    rc: Optional[int] = None
    error: str = ""
    analysis: Optional[Dict[str, Any]] = None
    created: float = field(default_factory=time.time)
    started: Optional[float] = None
    finished: Optional[float] = None

    @property
    def folder(self) -> str:
        return os.path.join(jobs_dir(), self.id)

    @property
    def case_dir(self) -> str:
        return os.path.join(self.folder, "case")

    @property
    def transient(self) -> bool:
        return "pimpleFoam" in self.params.get("regime", "")

    def save(self) -> None:
        os.makedirs(self.folder, exist_ok=True)
        tmp = os.path.join(self.folder, "job.json.tmp")
        with open(tmp, "w") as f:
            json.dump(asdict(self), f, indent=1, ensure_ascii=False)
        os.replace(tmp, os.path.join(self.folder, "job.json"))


def new_job(params: Dict[str, Any], host: str = "", nproc: int = 0, group: str = "",
            label: str = "") -> Job:
    """Trabajo nuevo con carpeta propia. Dos en el mismo segundo no comparten nada."""
    etiqueta = label or f"{params.get('naca') or 'custom'}_a{params.get('aoa', 0)}"
    etiqueta = re.sub(r"[^A-Za-z0-9_.-]", "_", etiqueta)
    while True:
        identificador = f"{time.strftime('%Y%m%d_%H%M%S')}_{etiqueta}_{secrets.token_hex(2)}"
        carpeta = os.path.join(jobs_dir(), identificador)
        try:
            os.makedirs(carpeta)
            break
        except FileExistsError:
            continue
    job = Job(identificador, etiqueta, dict(params), host, nproc, group)
    job.save()
    return job


def load_jobs() -> List[Job]:
    """Trabajos guardados, del mas antiguo al mas reciente."""
    trabajos = []
    for nombre in os.listdir(jobs_dir()):
        try:
            with open(os.path.join(jobs_dir(), nombre, "job.json")) as f:
                trabajos.append(Job(**json.load(f)))
        except (OSError, ValueError, TypeError):
            continue
    return sorted(trabajos, key=lambda j: j.created)


def mesh_key(params: Dict[str, Any]) -> str:
    """Huella de lo que define la malla, incluido el codigo que la genera."""
    from core.package import sha256_file, _version

    from core.solve_script import angle_by_flow

    datos = {k: params[k] for k in CLAVES_MALLA if k in params}
    if angle_by_flow(params):
        datos.pop("aoa", None)  # el mismo archivo sirve para todos los angulos
    if params.get("mesher") == "cgrid":
        # La primera celda sale del Reynolds: otro Reynolds es otra malla.
        from core.cgrid import first_cell_of
        datos["primera_celda"] = first_cell_of(params)
    if "Custom" in params.get("profile_type", "") and params.get("file_path"):
        datos["perfil"] = sha256_file(params["file_path"])
    if params.get("mesh_file"):
        datos["mesh_file"] = sha256_file(params["mesh_file"])
    datos["gmsh"] = _version("gmsh")
    # El codigo que genera la malla es parte de su huella.
    datos["codigo"] = [sha256_file(os.path.join(RAIZ, "core", n))
                       for n in ("mesh_script.py", "cgrid.py", "structured_mesh.py")]
    return hashlib.sha256(json.dumps(datos, sort_keys=True).encode()).hexdigest()[:24]


_candados: Dict[str, threading.Lock] = {}
_candado_global = threading.Lock()


def ensure_mesh(params: Dict[str, Any], log: Callable[[str], None] = lambda _: None) -> str:
    """La malla de estos parametros: la genera una vez y la reutiliza."""
    clave = mesh_key(params)
    carpeta = os.path.join(paths.data_root(), "meshes")
    os.makedirs(carpeta, exist_ok=True)
    msh = os.path.join(carpeta, f"{clave}.msh")
    with _candado_global:
        candado = _candados.setdefault(clave, threading.Lock())
    with candado:
        if os.path.exists(msh):
            log(f"📐 Malla {clave[:8]} reutilizada")
            return msh
        log(f"📐 Generando malla {clave[:8]}...")
        entrada = os.path.join(carpeta, f"{clave}.json")
        with open(entrada, "w") as f:
            json.dump(params, f)
        temporal = msh + ".parcial.msh"
        if params.get("mesh_file"):
            from core.structured_mesh import import_plot3d
            import_plot3d(params["mesh_file"], temporal,
                          float(params.get("depth", 0.1)) * float(params.get("chord", 1.0)))
        elif params.get("mesher") == "cgrid":
            from core.cgrid import build_mesh
            build_mesh(params, temporal)
        else:
            from core.solve_script import angle_by_flow
            if angle_by_flow(params):
                with open(entrada, "w") as f:
                    json.dump(dict(params, aoa=0.0), f)
            env = dict(os.environ)
            env["PYTHONPATH"] = RAIZ + os.pathsep + env.get("PYTHONPATH", "")
            r = subprocess.run([sys.executable, "-m", "core.mesh_script", entrada, temporal],
                               capture_output=True, text=True, errors="replace", env=env, cwd=RAIZ,
                               stdin=subprocess.DEVNULL, timeout=1800)
            if r.returncode != 0:
                raise JobError(f"La malla no se pudo generar: {(r.stderr or r.stdout)[-400:]}")
            for aviso in r.stdout.splitlines():
                if aviso.startswith("⚠️"):
                    log(aviso)
        os.replace(temporal, msh)
        info = temporal + ".info.json"
        if os.path.exists(info):
            os.replace(info, msh + ".info.json")
        vtk = temporal.replace(".msh", ".vtk")
        if os.path.exists(vtk):
            os.replace(vtk, msh.replace(".msh", ".vtk"))
        return msh


def make_runner(job: Job):
    if job.host == LOCAL:
        from core.local_runner import LocalJob
        return LocalJob(job.case_dir, job.id, bool(job.params.get("native_foam")))
    # La carpeta lleva el id del trabajo: si ya existe, es de un intento anterior suyo.
    return RemoteJob(job.host, job_dir=job.remote_dir or f"openblade_jobs/{job.id}", carpeta_propia=True)


class Events:
    """Lo que un trabajo cuenta mientras corre."""

    def state(self, job: Job) -> None:
        pass

    def log(self, job: Job, texto: str) -> None:
        pass

    def residual(self, job: Job, campo: str, valor: float, t: float) -> None:
        pass

    def force(self, job: Job, nombre: str, valor: str) -> None:
        pass


MARGEN_TRANSITORIO = 10.0


class _Vigilancia:
    """Detecta en vivo una corrida que diverge, para no gastar el resto del calculo."""
    VENTANA = 500
    MINIMO = 1000

    # Para terminar antes de tiempo se exige mas que para dar por convergida la corrida.
    # Se mira cada CADA_CONVERGENCIA iteraciones y se termina MARGEN despues, en un multiplo
    # fijo: el final no depende de cuando llega la consulta ni de la velocidad de la
    # maquina, asi que el mismo paquete da el mismo archivo de fuerzas en todas.
    CADA_CONVERGENCIA = 1000
    MARGEN = 2000
    TOL_RANGO_CD = 0.008
    TOL_RANGO_CL = 0.005
    # Cambio de la media entre tramos de la corrida (verdict.tramo_final), algo mas estricto
    # que el del veredicto: una corrida que termina antes de tiempo sale CONVERGIDO.
    TOL_DERIVA_CD = 0.002
    TOL_DERIVA_CL = 0.001

    def __init__(self) -> None:
        self.n = 0
        self.cl: List[float] = []
        self.cd: List[float] = []

    def agrega(self, nombre: str, valor: str) -> None:
        try:
            v = float(valor)
        except ValueError:
            return
        if nombre == "Cl":
            self.cl.append(v)
            self.n += 1
        elif nombre == "Cd":
            self.cd.append(v)

    def divergio(self, margen: float = 1.0) -> bool:
        """Solo con valores imposibles: en un arranque lento Cd puede pasar por cero.

        El arranque impulsivo de un transitorio da Cl alrededor de 7 durante miles de pasos
        muy cortos: ahi se pide un margen sobre lo imposible.
        """
        from core.verdict import CD_IMPOSIBLE, CL_IMPOSIBLE
        if self.n < self.MINIMO:
            return False
        cl, cd = self.cl[-self.VENTANA:], self.cd[-self.VENTANA:]
        malos = sum(1 for x in cd if abs(x) > margen * CD_IMPOSIBLE)
        malos += sum(1 for x in cl if abs(x) > margen * CL_IMPOSIBLE)
        return malos > 0.2 * self.VENTANA

    def final_previsto(self) -> int:
        """Iteracion en la que termina el calculo si ahora se detecta la convergencia."""
        return (self.n // self.CADA_CONVERGENCIA + 1) * self.CADA_CONVERGENCIA + self.MARGEN

    def convergio(self) -> bool:
        """Las fuerzas ya no cambian: seguir solo gastaria maquina."""
        from core.verdict import tramo_final
        if self.n % self.CADA_CONVERGENCIA or self.n < self.MINIMO:
            return False
        ultimo_cd, ultimo_cl = self.cd[-self.VENTANA:], self.cl[-self.VENTANA:]
        media_cd = sum(ultimo_cd) / self.VENTANA
        media_cl = sum(ultimo_cl) / self.VENTANA
        if media_cd <= 0 or (max(ultimo_cd) - min(ultimo_cd)) / media_cd >= self.TOL_RANGO_CD:
            return False
        if max(ultimo_cl) - min(ultimo_cl) >= max(self.TOL_RANGO_CL * abs(media_cl), 2e-4):
            return False
        # La media tiene que haberse quedado quieta en un tramo proporcional a la corrida.
        reciente, previo = tramo_final(self.cd)
        if abs(reciente - previo) / media_cd >= self.TOL_DERIVA_CD:
            return False
        reciente, previo = tramo_final(self.cl)
        return abs(reciente - previo) < self.TOL_DERIVA_CL * max(abs(media_cl), 0.1)


# Lo que dice ssh o rsync cuando falla la conexion, no el trabajo
CORTES = ("timed out", "timeout", "not responding", "connection refused", "connection closed",
          "unexpectedly closed", "connection reset", "no route to host", "network is", "could not resolve",
          "unexpected end of file", "broken pipe", "mux_client", "protocol data stream", "socket io",
          "tailscale pide")


def es_corte(e: Exception) -> bool:
    """¿El fallo es de la conexion? Sin contrasena o sin espacio no sirve reintentar."""
    if isinstance(e, subprocess.TimeoutExpired):
        return True
    return isinstance(e, RemoteError) and any(c in str(e).lower() for c in CORTES)


def insiste(accion: Callable[[], None], avisar: Callable[[str], None], soltar: Callable[[], bool],
            poll_s: float = 4.0) -> bool:
    """Repite una accion hasta que haya conexion: sin red, un trabajo espera, no falla.

    Devuelve False si se pidio dejar de seguirlo antes de conseguirlo.
    """
    avisado = ""
    for _ in range(MAX_FALLOS):
        if soltar():
            return False
        try:
            accion()
            return True
        except (RemoteError, subprocess.TimeoutExpired) as e:
            if not es_corte(e):
                raise
            if str(e) != avisado:
                avisado = str(e)
                avisar(f"⚠️ Sin respuesta de la máquina; se reintenta. {e}")
        time.sleep(poll_s)
    raise RemoteError("Sin conexión con la máquina")


def follow(runner, on_event: Callable[[tuple], None], on_step: Callable[[str], None],
           should_stop: Callable[[], bool], poll_s: float = 4.0,
           on_notice: Callable[[str], None] = lambda _: None) -> Optional[Dict[str, Any]]:
    """Sigue un trabajo hasta que termina y devuelve su estado final.

    Un corte de red no lo detiene, sigue corriendo en su maquina: se reintenta durante
    horas y se avisa una vez. Devuelve None si se pidio dejar de seguirlo, o si tras esas
    horas se deja: el trabajo no esta perdido, se retoma al abrir de nuevo el programa.
    """
    parser = LogParser()
    paso, fallos, avisado = None, 0, ""
    inicio = time.time()
    while not should_stop():
        try:
            # Primero el estado: en una red lenta el log puede tardar en llegar, y un trabajo
            # terminado no debe quedarse esperando a que se lea todo.
            est = runner.estado()
            runner.comprobar_ficha(est)
            if est.get("state") == "running":
                for ev in parser.feed(runner.leer_log()):
                    on_event(ev)
            fallos = 0
            avisado = ""
        except FichaDistinta:
            raise
        except (RemoteError, subprocess.TimeoutExpired, OSError) as e:
            fallos += 1
            if str(e) != avisado:
                avisado = str(e)
                on_notice(f"⚠️ Sin respuesta de la máquina; el trabajo sigue allí. {e}")
            if fallos >= MAX_FALLOS:
                on_notice("⚠️ Sigue sin conexión: se deja de seguir. El trabajo sigue en su máquina "
                          "y se retoma al abrir de nuevo el programa.")
                return None
            time.sleep(poll_s)
            continue
        # Lanzado, pero sin rastro de su proceso: no va a arrancar ya.
        if est.get("step") == "inicio" and est.get("state") == "running" and time.time() - inicio > ARRANQUE_MAX:
            raise RemoteError("El trabajo no arrancó en su máquina: no dejó ningún rastro")
        if est.get("step") != paso:
            paso = est.get("step")
            on_step(paso or "")
        if est.get("state") != "running":
            # Lo que el solver escribio justo antes de terminar. Solo sirve para las graficas
            # en vivo: el resultado sale de las fuerzas que se descargan.
            try:
                for ev in parser.feed(runner.leer_log() + "\n"):
                    on_event(ev)
            except (RemoteError, subprocess.TimeoutExpired, OSError):
                pass
            return est
        time.sleep(poll_s)
    return None


def run_job(job: Job, ev: Events, should_detach: Callable[[], bool] = lambda: False,
            registrar: Callable[[Any], None] = lambda _: None,
            poll_s: float = 4.0, stop_on_divergence: bool = True) -> None:
    """Lleva un trabajo de principio a fin. Si ya estaba en marcha, se reengancha."""
    from core.solve_script import configure_case
    from core.verdict import analyze_case

    def cambia(estado: str, paso: str = "") -> None:
        job.state, job.step = estado, paso
        job.save()
        ev.state(job)

    runner = None
    try:
        if not job.remote_dir:
            job.started = time.time()
            cambia(MALLANDO)
            msh = ensure_mesh(job.params, lambda t: ev.log(job, t))
            cambia(PREPARANDO)
            transient = configure_case(job.case_dir, job.params)
            if job.params.get("campo_inicial"):
                from core.initial_field import start_from
                tiempo = start_from(job.params["campo_inicial"], job.case_dir, msh)
                ev.log(job, f"🔁 Arranca del campo de la iteración {tiempo} de {job.params['campo_inicial']}")
            if transient and job.params.get("mesher") == "cgrid":
                from core.cgrid import transient_notice
                ev.log(job, transient_notice(job.params))
            cambia(SUBIENDO)
            runner = make_runner(job)
            registrar(runner)
            if job.host != LOCAL:
                ev.log(job, f"📤 Subiendo a {job.host} ({job.nproc} procesos)...")
            aviso = lambda t: ev.log(job, t)
            if not insiste(lambda: runner.subir(job.case_dir, msh, job.nproc, transient, job.params),
                           aviso, should_detach, poll_s):
                return
            if not insiste(runner.lanzar, aviso, should_detach, poll_s):
                return
            job.remote_dir = runner.job_dir
        else:
            runner = make_runner(job)
            registrar(runner)
            ficha = os.path.join(job.case_dir, "ficha.json")
            if os.path.exists(ficha):
                from core.package import sha256_file
                runner.ficha_sha256 = sha256_file(ficha)
            ev.log(job, f"🔌 Reconectando con {job.host}:{job.remote_dir}")
        cambia(CORRIENDO)

        vigia = _Vigilancia()
        detenida = threading.Event()

        def evento(e: tuple) -> None:
            if e[0] == "residual":
                ev.residual(job, e[1], e[2], e[3])
                return
            ev.force(job, e[1], e[2])
            vigia.agrega(e[1], e[2])
            if e[1] != "Cl" or vigia.n % 100 or detenida.is_set():
                return
            if stop_on_divergence and vigia.divergio(MARGEN_TRANSITORIO if job.transient else 1.0):
                detenida.set()
                ev.log(job, "💥 Las fuerzas divergieron: se detiene el cálculo.")
                runner.detener()
            elif not job.transient and vigia.convergio():
                detenida.set()
                final = vigia.final_previsto()
                if final < int(job.params.get("max_iters", 0)):
                    ev.log(job, f"✅ Las fuerzas ya no cambian en la iteración {vigia.n}: termina en la {final}.")
                    runner.terminar_en(final)

        est = follow(runner, evento, lambda p: cambia(CORRIENDO, p), should_detach, poll_s,
                     lambda aviso: ev.log(job, aviso))
        if est is None:
            return

        job.rc = int(est.get("rc") or 0)
        job.error = est.get("error") or ""
        if job.error:
            ev.log(job, f"❌ {job.error}")
        cambia(DESCARGANDO)
        runner.descargar(job.case_dir)
        job.analysis = analyze_case(job.case_dir, job.transient, job.rc, job.host,
                                    job.remote_dir, job.error)
        job.finished = time.time()
        # Solo ahorra disco en el servidor: si falla, el resultado ya esta aqui y vale.
        try:
            runner.limpiar()
        except (RemoteError, subprocess.TimeoutExpired, OSError) as e:
            ev.log(job, f"⚠️ No se borraron los temporales en la máquina: {str(e)[:120]}")
        cambia(DETENIDO if job.rc == RC_DETENIDA else FALLIDO if job.rc else TERMINADO)
    except Exception as e:  # noqa: BLE001
        # Cualquier fallo termina el trabajo: sin esto, un error inesperado lo dejaba
        # en "mallando" para siempre y ocupando su maquina.
        job.error = str(e) or type(e).__name__
        job.finished = time.time()
        ev.log(job, f"❌ {job.error}")
        cambia(FALLIDO)


@dataclass
class Machine:
    host: str
    nproc: int
    slots: int = 1
    reparto: bool = True    # recibe paquetes sin maquina fija


class Dispatcher:
    """Reparte los trabajos pendientes entre las maquinas."""

    def __init__(self, events: Optional[Events] = None, poll_s: float = 4.0,
                 stop_on_divergence: bool = True) -> None:
        self.events = events or Events()
        self.poll_s = poll_s
        self.stop_on_divergence = stop_on_divergence
        self.machines: Dict[str, Machine] = {}
        self.jobs: Dict[str, Job] = {}
        self._cola: List[str] = []
        self._hilos: Dict[str, threading.Thread] = {}
        self._runners: Dict[str, Any] = {}
        self._soltar: set = set()
        self._detener: set = set()
        self._candado = threading.RLock()

    def set_machines(self, machines: List[Machine]) -> None:
        with self._candado:
            self.machines = {m.host: m for m in machines}
        self._tick()

    def submit(self, job: Job) -> None:
        with self._candado:
            self.jobs[job.id] = job
            self._cola.append(job.id)
        self.events.state(job)
        self._tick()

    def attach(self, job: Job) -> None:
        """Vuelve a seguir un trabajo que quedo corriendo al cerrar la ventana."""
        with self._candado:
            self.jobs[job.id] = job
            self._arranca(job)

    def _ocupados(self, host: str) -> int:
        return sum(1 for i in self._hilos if self.jobs[i].host == host)

    def _maquina_libre(self, job: Job) -> Optional[str]:
        if job.host:
            m = self.machines.get(job.host)
            return job.host if m is None or self._ocupados(job.host) < m.slots else None
        for m in self.machines.values():
            if m.reparto and self._ocupados(m.host) < m.slots:
                return m.host
        return None

    def _tick(self) -> None:
        with self._candado:
            for identificador in list(self._cola):
                job = self.jobs[identificador]
                host = self._maquina_libre(job)
                if host is None:
                    continue
                job.host = host
                if not job.nproc:
                    m = self.machines.get(host)
                    job.nproc = m.nproc if m else 1
                self._cola.remove(identificador)
                self._arranca(job)

    def _arranca(self, job: Job) -> None:
        hilo = threading.Thread(target=self._corre, args=(job,), daemon=True)
        self._hilos[job.id] = hilo
        hilo.start()

    def _corre(self, job: Job) -> None:
        def registrar(runner) -> None:
            self._runners[job.id] = runner

        try:
            run_job(job, self.events, lambda: job.id in self._soltar, registrar,
                    self.poll_s, self.stop_on_divergence)
            if job.id in self._detener:
                job.state = DETENIDO
                job.save()
                self.events.state(job)
        finally:
            with self._candado:
                self._hilos.pop(job.id, None)
                self._runners.pop(job.id, None)
            self._tick()

    def stop(self, job_id: str) -> None:
        with self._candado:
            job = self.jobs.get(job_id)
            if job is None:
                return
            if job_id in self._cola:
                self._cola.remove(job_id)
                job.state = DETENIDO
                job.save()
                self.events.state(job)
                return
            # Aun no ha llegado a su maquina, quiza esperando la red: ya no se envia.
            if not job.remote_dir:
                self._detener.add(job_id)
                self._soltar.add(job_id)
                return
            runner = self._runners.get(job_id)
        if runner is not None:
            runner.detener()

    def set_paused(self, job_id: str, pausado: bool) -> None:
        runner = self._runners.get(job_id)
        if runner is None:
            raise JobError("El trabajo no está corriendo")
        if pausado:
            runner.pausar()
        else:
            runner.reanudar()

    def detach_all(self) -> None:
        """Deja de seguir los trabajos sin detenerlos: siguen en su maquina."""
        with self._candado:
            self._soltar.update(self._hilos)
            hilos = list(self._hilos.values())
        for hilo in hilos:
            hilo.join(timeout=15)

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Espera a que no quede nada pendiente ni corriendo."""
        limite = None if timeout is None else time.time() + timeout
        while True:
            with self._candado:
                activos = bool(self._cola or self._hilos)
            if not activos:
                return True
            if limite is not None and time.time() > limite:
                return False
            time.sleep(0.2)

    def remove_local(self, job_id: str) -> None:
        """Borra la carpeta local de un trabajo terminado."""
        with self._candado:
            job = self.jobs.pop(job_id, None)
        if job is not None and job.state in FINALES:
            shutil.rmtree(job.folder, ignore_errors=True)
