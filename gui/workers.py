from qtpy.QtCore import QThread, Signal, QProcess, QObject
import os
import sys
import json
import time
import subprocess
import numpy as np
from typing import Dict, Any, List


def app_root() -> str:
    """Raíz del repo (donde viven `core/` y `main.py`)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def subprocess_env() -> Dict[str, str]:
    """Entorno con la raíz del repo en PYTHONPATH.

    Los scripts se lanzan como `-m core.<script>`; si el CWD de la GUI no es la
    raíz del repo (p. ej. abierta desde Finder), el import fallaba.
    """
    env = os.environ.copy()
    root = app_root()
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root + (os.pathsep + current if current else "")
    return env


class MeshWorker(QThread):
    finished = Signal(str, str)
    error = Signal(str)
    log_msg = Signal(str)
    def __init__(self, params: Dict[str, Any], msh_file: str, case_dir: str) -> None:
        super().__init__()
        self.p = params
        self.msh_file = msh_file
        self.case_dir = case_dir
        self._proc = None

    def cancel(self) -> None:
        """Mata el gmsh en curso; sin esto el cierre de la app deja huérfanos."""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        
    def run(self) -> None:
        try:
            self.log_msg.emit("⏳ Iniciando mallado aislado...")
            from core import paths
            json_path = paths.temp_path("temp_params_mesh.json")
            with open(json_path, 'w') as f:
                json.dump(self.p, f)
            
            cmd = [sys.executable, "-m", "core.mesh_script", json_path, self.msh_file]
            # stdin=DEVNULL: si la GUI se lanzó con nohup, el fd 0 está
            # cerrado y el hijo muere con "can't initialize sys standard
            # streams". Con DEVNULL hereda un descriptor válido.
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace',
                env=subprocess_env()
            )
            try:
                out, err = self._proc.communicate()
            finally:
                rc = self._proc.returncode
                self._proc = None
            self.log_msg.emit(out)
            if rc == 0:
                self.finished.emit(self.msh_file, self.msh_file.replace(".msh", ".vtk"))
            else:
                self.error.emit(err)
        except Exception as e:
            self.error.emit(str(e))


class SimWorker(QObject):
    """
    Ejecuta el solver CFD usando QProcess (event-loop based).
    No hereda QThread porque QProcess ya es asíncrono y necesita
    correr en el hilo principal del event loop de Qt.
    """
    finished = Signal(int)
    error = Signal(str)
    log_msg = Signal(str)
    force_data = Signal(str, str)
    residual_data = Signal(str, float, float)
    
    def __init__(self, solver_runner, params: Dict[str, Any], msh_file: str, parent=None) -> None:
        super().__init__(parent)
        self.p = params
        self.msh_file = msh_file
        self.process = None
        # Buffer para líneas partidas entre dos lecturas del QProcess.
        # Sin esto se pierden RESIDUAL_DATA / FORCE_DATA que llegan a medias.
        self._stdout_buffer = ""

    def start_sim(self):
        from core import paths
        json_path = paths.temp_path("temp_params_solve.json")
        with open(json_path, 'w') as f:
            json.dump(self.p, f)
            
        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.on_output)
        self.process.finished.connect(self.on_finished)
        
        cmd = sys.executable
        args = ["-m", "core.solve_script", json_path, self.msh_file]
        self.log_msg.emit("🚀 Lanzando simulador nativo (QProcess)...")
        self.process.start(cmd, args)

    def on_output(self):
        data = self.process.readAllStandardOutput().data().decode(errors='replace')
        self.consume_text(data)

    def consume_text(self, data: str) -> None:
        """Procesa un bloque de stdout conservando la línea incompleta final."""
        data = self._stdout_buffer + data
        lines = data.split("\n")
        # La última entrada puede ser una línea incompleta: se guarda para el próximo bloque.
        self._stdout_buffer = lines.pop()

        for line in lines:
            clean = line.strip()
            if not clean:
                continue
            try:
                if clean.startswith("RESIDUAL_DATA|"):
                    p = clean.split("|")
                    if len(p) == 4: self.residual_data.emit(p[1], float(p[2]), float(p[3]))
                elif clean.startswith("FORCE_DATA|"):
                    p = clean.split("|")
                    # Cm se emite siempre (último valor) para que la GUI no
                    # muestre un 0.0 de una corrida anterior.
                    if len(p) == 3:
                        self.force_data.emit(p[1], p[2])
                elif clean.startswith("SIM_DONE|"):
                    pass
                else:
                    # Emitir cualquier otra cosa al log (incluyendo errores, setup, gmshToFoam, etc)
                    # Limitamos para no inundar si es iteración sin Time =
                    if "Time =" in clean or "ClockTime =" in clean or "Ejecutando" in clean or "DEBUG" in clean or clean.startswith("✅") or clean.startswith("❌") or clean.startswith("🌊") or clean.startswith("🚀") or clean.startswith("📝") or clean.startswith("🔄") or clean.startswith("⚠️") or "FOAM" in clean or "error" in clean.lower():
                        self.log_msg.emit(clean)
            except Exception:
                pass

    def stop(self) -> None:
        """Detiene la simulación de verdad, contenedor incluido.

        Matar sólo el QProcess deja huérfano el contenedor Docker: el cliente
        muere, el contenedor sigue consumiendo CPU. Es lo que ocurrió con una
        corrida que siguió viva dos horas después de pulsar detener.

        Orden:
          1. Pedir al script que aborte (SIGTERM al QProcess).
          2. Matar el contenedor de OpenFOAM por imagen, que es la única forma
             fiable de pararlo desde fuera del proceso hijo.
        """
        if self.process is not None:
            try:
                if self.process.state() != QProcess.NotRunning:
                    self.process.terminate()
                    if not self.process.waitForFinished(3000):
                        self.process.kill()
            except Exception:
                pass

        # Limpieza del contenedor, independiente del QProcess.
        try:
            import subprocess as _sp
            ids = _sp.run(["docker", "ps", "-q", "--filter",
                           "ancestor=opencfd/openfoam-default"],
                          capture_output=True, text=True, timeout=15).stdout.split()
            for cid in ids:
                _sp.run(["docker", "kill", cid], capture_output=True,
                        text=True, timeout=15)
            if ids:
                self.log_msg.emit(
                    f"🛑 {len(ids)} contenedor(es) de OpenFOAM detenido(s).")
        except Exception as e:  # noqa: BLE001
            self.log_msg.emit(f"⚠️ No se pudo limpiar el contenedor: {e}")

    def on_finished(self, exit_code):
        # Volcar la última línea si el proceso no terminó con salto de línea
        if self._stdout_buffer.strip():
            tail, self._stdout_buffer = self._stdout_buffer, ""
            self.consume_text(tail + "\n")
        self.finished.emit(exit_code)
        if os.path.exists("temp_params_solve.json"):
            os.remove("temp_params_solve.json")


class SweepWorker(QThread):
    """
    Ejecuta un barrido paramétrico de ángulos de ataque (polar).
    Para cada ángulo:
      1. Genera una nueva malla con el ángulo actual
      2. Configura el caso OpenFOAM
      3. Ejecuta la simulación en estado estacionario
      4. Extrae Cl y Cd del postprocessing
    
    Emite finished(aoa_list, cl_list, cd_list, cm_list) al terminar.
    """
    finished = Signal(list, list, list, list)
    error = Signal(str)
    log_msg = Signal(str)
    progress = Signal(int, int)  # (current, total)
    mesh_generated = Signal(str) # Ruta al VTK para previsualización
    
    def __init__(self, params: Dict[str, Any], case_dir: str) -> None:
        super().__init__()
        self.p = params.copy()
        self.case_dir = case_dir
        self._stop_requested = False
        self._current_proc = None

    def request_stop(self):
        """Solicitar detención segura del barrido.

        Además de marcar la bandera, mata el subproceso en curso: si no,
        'Detener Barrido' podía tardar hasta 20 minutos (timeout del solver).
        """
        self._stop_requested = True
        proc = self._current_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def _run_cmd(self, cmd, timeout):
        """Ejecuta un subproceso cancelable. Devuelve un CompletedProcess-like."""
        # stdin=DEVNULL por el mismo motivo que en MeshWorker: sin un fd 0
        # válido el intérprete hijo aborta en init_sys_streams.
        self._current_proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace',
            env=subprocess_env()
        )
        try:
            out, err = self._current_proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._current_proc.kill()
            out, err = self._current_proc.communicate()
            raise
        finally:
            rc = self._current_proc.returncode
            self._current_proc = None
        return subprocess.CompletedProcess(cmd, rc, out, err)
        
    def run(self) -> None:
        aoa_min = self.p.get("aoa_min", -4.0)
        aoa_max = self.p.get("aoa_max", 24.0)
        aoa_step = self.p.get("aoa_step", 2.0)
        
        # Generar lista de ángulos
        angles = []
        aoa = aoa_min
        while aoa <= aoa_max + 1e-6:
            angles.append(round(aoa, 2))
            aoa += aoa_step
        
        total = len(angles)
        self.log_msg.emit(f"📊 Barrido de ángulos: {total} puntos de {aoa_min}° a {aoa_max}° (paso {aoa_step}°)")
        
        aoa_results = []
        cl_results = []
        cd_results = []
        cm_results = []
        
        naca = self.p.get("naca", "0012")
        
        for i, angle in enumerate(angles):
            if self._stop_requested:
                self.log_msg.emit("⚠️ Barrido detenido por el usuario.")
                break
                
            self.progress.emit(i + 1, total)
            self.log_msg.emit(f"━━━ [{i+1}/{total}] AoA = {angle}° ━━━")
            
            # Actualizar AoA en parámetros
            sweep_params = self.p.copy()
            sweep_params["aoa"] = angle
            # Forzar estacionario para barrido
            sweep_params["regime"] = "Estacionario (simpleFoam)"
            
            try:
                # Paso 1: Generar malla con nuevo AoA
                from core import paths
                msh_file = os.path.join(os.path.dirname(paths.mesh_path(naca)),
                                        f"perfil_{naca}_sweep.msh")
                self.log_msg.emit(f"  🔧 Generando malla (AoA={angle}°)...")
                
                json_path = paths.temp_path("temp_params_sweep.json")
                with open(json_path, 'w') as f:
                    json.dump(sweep_params, f)
                
                result = self._run_cmd(
                    [sys.executable, "-m", "core.mesh_script", json_path, msh_file],
                    timeout=300
                )
                if self._stop_requested:
                    break
                
                if result.returncode != 0:
                    self.log_msg.emit(f"  ❌ Error en malla: {result.stderr[:200]}")
                    continue
                
                # Emitir señal para actualizar la vista 3D en la interfaz
                vtk_file = msh_file.replace(".msh", ".vtk")
                if os.path.exists(vtk_file):
                    self.mesh_generated.emit(vtk_file)
                
                # Paso 2: Configurar y ejecutar simulación
                self.log_msg.emit(f"  🚀 Simulando...")
                cl, cd, cm = self._solve_angle(sweep_params, json_path, msh_file, angle)
                if self._stop_requested:
                    break

                aoa_results.append(angle)
                cl_results.append(cl)
                cd_results.append(cd)
                cm_results.append(cm)
                self.log_msg.emit(f"  ✅ AoA={angle}°: Cl={cl:.4f}, Cd={cd:.4f}")

            except subprocess.TimeoutExpired:
                self.log_msg.emit(f"  ⏱️ Timeout en AoA={angle}°, saltando...")
                continue
            except Exception as e:
                self.log_msg.emit(f"  ❌ Error en AoA={angle}°: {e}")
                continue
        
        # Limpiar archivos temporales
        for f in ["temp_params_sweep.json", f"perfil_{naca}_sweep.msh", 
                   f"perfil_{naca}_sweep.vtk"]:
            if os.path.exists(f):
                try: os.remove(f)
                except: pass
        
        self.log_msg.emit(f"📊 Barrido completado: {len(aoa_results)}/{total} puntos exitosos")
        self.finished.emit(aoa_results, cl_results, cd_results, cm_results)
    
    def _solve_angle(self, params, json_path, msh_file, angle):
        """Resuelve un angulo y devuelve (cl, cd, cm); local por defecto."""
        from core.forces import final_coefficients

        self._run_cmd(
            [sys.executable, "-m", "core.solve_script", json_path, msh_file],
            timeout=1200
        )
        return final_coefficients(self.case_dir)


def _follow_remote_job(worker, job, parser_events, should_stop, poll_s=4.0):
    """Sigue un trabajo remoto hasta que termina. Devuelve su estado final.

    Un corte de red no detiene el trabajo: se reintenta durante unos minutos
    y, si no vuelve, se avisa de que sigue corriendo en el servidor.
    """
    from core.remote_runner import LogParser, RemoteError

    parser = LogParser()
    paso, fallos = None, 0
    while not should_stop():
        try:
            for ev in parser.feed(job.leer_log()):
                parser_events(ev)
            est = job.estado()
            fallos = 0
        except (RemoteError, subprocess.TimeoutExpired, OSError) as e:
            fallos += 1
            if fallos >= 45:
                raise RemoteError(f"Sin conexión con el servidor: {e}") from e
            time.sleep(poll_s)
            continue
        if est.get("step") != paso:
            paso = est.get("step")
            worker.log_msg.emit(f"🖥️ Servidor: {paso}")
        if est.get("state") != "running":
            # Lo que el solver escribio justo antes de terminar
            for ev in parser.feed(job.leer_log() + "\n"):
                parser_events(ev)
            return est
        time.sleep(poll_s)
    return None


class RemoteSimWorker(QThread):
    """Corre un punto unico en un servidor. Mismas senales que SimWorker."""
    finished = Signal(int)
    error = Signal(str)
    log_msg = Signal(str)
    force_data = Signal(str, str)
    residual_data = Signal(str, float, float)
    job_started = Signal(str, str)  # host, directorio del trabajo

    def __init__(self, params, msh_file, case_dir, attach_dir=None, parent=None):
        super().__init__(parent)
        self.p = params
        self.msh_file = msh_file
        self.case_dir = case_dir
        self.attach_dir = attach_dir
        self.job = None
        self._detached = False

    def start_sim(self):
        self.start()

    def _evento(self, ev):
        if ev[0] == "residual":
            self.residual_data.emit(ev[1], ev[2], ev[3])
        else:
            self.force_data.emit(ev[1], ev[2])

    def run(self):
        from core.remote_runner import RemoteError, RemoteJob
        from core import paths
        from core.solve_script import configure_case

        estado_local = paths.temp_path("remote_job.json")
        host = self.p["server_host"]
        try:
            if self.attach_dir:
                self.job = RemoteJob(host, job_dir=self.attach_dir)
                self.log_msg.emit(f"🔌 Reconectando con {host}:{self.attach_dir}")
            else:
                etiqueta = f"{self.p.get('naca') or 'custom'}_a{self.p.get('aoa', 0)}"
                self.job = RemoteJob(host, etiqueta=etiqueta)
                self.log_msg.emit("📝 Preparando el caso...")
                transient = configure_case(self.case_dir, self.p)
                nproc = int(self.p.get("server_nproc", 4))
                self.log_msg.emit(f"📤 Subiendo a {host} ({nproc} procesos)...")
                self.job.subir_y_lanzar(self.case_dir, self.msh_file, nproc, transient)
                with open(estado_local, "w") as f:
                    json.dump({"host": host, "job_dir": self.job.job_dir,
                               "aoa": self.p.get("aoa", 0.0)}, f)
            self.job_started.emit(host, self.job.job_dir)

            est = _follow_remote_job(self, self.job, self._evento,
                                     lambda: self._detached)
            if est is None:
                self.log_msg.emit(
                    f"🔌 El trabajo sigue en {host}:{self.job.job_dir}. "
                    "Al volver a iniciar en modo servidor podrás reconectarte.")
                self.finished.emit(0)
                return

            rc = int(est.get("rc") or 0)
            if est.get("error"):
                self.log_msg.emit(f"❌ Servidor: {est['error']}")
            self.log_msg.emit("📥 Descargando resultados...")
            self.job.descargar(self.case_dir)
            if os.path.exists(estado_local):
                os.remove(estado_local)
            self.log_msg.emit(f"✅ Resultados en {self.case_dir}")
            self.finished.emit(rc)
        except (RemoteError, subprocess.SubprocessError, OSError) as e:
            self.log_msg.emit(f"❌ Servidor: {e}")
            self.finished.emit(1)

    def stop(self):
        if self.job is not None:
            self.job.detener()
            self.log_msg.emit("🛑 Trabajo detenido en el servidor.")

    def detach(self):
        """Deja de seguir el trabajo sin detenerlo (al cerrar la app)."""
        self._detached = True

    def set_paused(self, pausado):
        if pausado:
            self.job.pausar()
        else:
            self.job.reanudar()


class RemoteSweepWorker(SweepWorker):
    """Barrido cuyos angulos se resuelven en el servidor, uno tras otro."""

    def __init__(self, params, case_dir):
        super().__init__(params, case_dir)
        self._job = None

    def request_stop(self):
        super().request_stop()
        job = self._job
        if job is not None:
            try:
                job.detener()
            except Exception as e:  # noqa: BLE001
                self.log_msg.emit(f"⚠️ No se pudo detener el trabajo: {e}")

    def _solve_angle(self, params, json_path, msh_file, angle):
        from core.forces import final_coefficients
        from core.remote_runner import RemoteError, RemoteJob
        from core.solve_script import configure_case

        transient = configure_case(self.case_dir, params)
        etiqueta = f"{params.get('naca') or 'custom'}_a{angle}"
        self._job = RemoteJob(params["server_host"], etiqueta=etiqueta)
        self._job.subir_y_lanzar(self.case_dir, msh_file,
                                 int(params.get("server_nproc", 4)), transient)
        est = _follow_remote_job(self, self._job, lambda ev: None,
                                 lambda: self._stop_requested)
        if est is None or est.get("rc"):
            raise RemoteError((est or {}).get("error", "trabajo detenido"))
        self._job.descargar(self.case_dir)
        return final_coefficients(self.case_dir)
