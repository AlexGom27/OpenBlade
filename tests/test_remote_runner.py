"""Pruebas de la ejecucion en servidor que no necesitan red."""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.remote_runner import (LogParser, RemoteError, RemoteJob,
                                configurar_acceso, validar_host)


def test_host_rejects_ssh_options():
    assert validar_host(" user@10.0.0.1 ") == "user@10.0.0.1"
    for malo in ("", "-oProxyCommand=x", "a b", "a;rm"):
        with pytest.raises(RemoteError):
            validar_host(malo)


def test_job_dir_stays_under_home():
    with pytest.raises(RemoteError):
        RemoteJob("u@h", job_dir="../fuera")
    assert "0012_a4.5_x_" in RemoteJob("u@h", etiqueta="0012_a4.5/x").job_dir


def test_two_jobs_launched_in_the_same_second_get_different_folders():
    """Compartian carpeta: un lanzamiento se perdia y ambos terminaban con rc=0."""
    assert len({RemoteJob("u@h", etiqueta="x").job_dir for _ in range(50)}) == 50


def test_parser_handles_openfoam12_output_and_split_lines():
    p = LogParser()
    ev = p.feed("Time = 12s\n\nGAMG:  Solving for p, Initial residual = 0.01, Fin")
    assert ev == []
    ev = p.feed("al residual = 1e-3, No Iterations 2\n"
                "    Cm    = 0.05\n    Cd    = 0.0123\n    Cl    = 0.8\n"
                "    Cl(f) = 0.4\n")
    assert ev == [("residual", "p", 0.01, 12.0), ("fuerza", "Cm", "0.05"),
                  ("fuerza", "Cd", "0.0123"), ("fuerza", "Cl", "0.8")]


def _ssh_falso(tmp_path, monkeypatch):
    """ssh que pide la contrasena por askpass y guarda la clave que recibe."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "ssh"
    script.write_text(
        '#!/bin/sh\n'
        'echo "$*" >> "$HOME/argv"\n'
        'case "$*" in *BatchMode=yes*) [ -s "$HOME/recibida" ]; exit $? ;; esac\n'
        '[ "$("$SSH_ASKPASS")" = "secreta 1" ] || { echo "Permission denied" >&2; exit 255; }\n'
        'cat > "$HOME/recibida"\n')
    script.chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_configurar_acceso_creates_key_and_hides_password(tmp_path, monkeypatch):
    _ssh_falso(tmp_path, monkeypatch)
    configurar_acceso("u@h", "secreta 1")
    pub = (tmp_path / ".ssh" / "id_ed25519.pub").read_text().strip()
    assert (tmp_path / "recibida").read_text().strip() == pub
    assert "secreta" not in (tmp_path / "argv").read_text()


def test_configurar_acceso_reports_wrong_password(tmp_path, monkeypatch):
    _ssh_falso(tmp_path, monkeypatch)
    with pytest.raises(RemoteError, match="incorrectos"):
        configurar_acceso("u@h", "otra")


def test_rsync_is_retried_before_giving_up(monkeypatch):
    """Un corte al descargar marcaba como fallido un calculo terminado."""
    from core import remote_runner as rr

    class R:
        def __init__(self, rc):
            self.returncode, self.stderr = rc, "unexpected end of file"

    llamadas = []

    def falso(cmd, **_k):
        llamadas.append(cmd)
        return R(0 if len(llamadas) == 3 else 12)

    monkeypatch.setattr(rr.subprocess, "run", falso)
    monkeypatch.setattr(rr, "ESPERA_RSYNC", 0.0)
    RemoteJob("u@h", job_dir="jobs/x").descargar("/tmp/x")
    assert len(llamadas) == 3
    llamadas.clear()
    monkeypatch.setattr(rr.subprocess, "run", lambda cmd, **_k: R(12))
    with pytest.raises(RemoteError, match="rsync"):
        RemoteJob("u@h", job_dir="jobs/x").descargar("/tmp/x")


def test_tailscale_check_is_reported_with_its_link():
    """ssh se quedaba esperando sin decir nada: la ventana solo veia 'no responde'."""
    from core.remote_runner import _aviso_tailscale
    salida = "# Tailscale SSH requires an additional check.\n# To authenticate, visit: https://login.tailscale.com/a/abc\n"
    assert _aviso_tailscale(salida) == "Tailscale pide autenticarse: abre https://login.tailscale.com/a/abc"
    assert _aviso_tailscale(salida.encode()) .endswith("/a/abc")
    assert _aviso_tailscale("otra cosa") == "" and _aviso_tailscale(None) == ""


def test_a_dead_connection_cannot_hang_a_transfer_and_a_download_insists(monkeypatch):
    """Con la Mac dormida o en otra red, rsync se quedaba colgado para siempre."""
    from core import remote_runner as R
    assert "ServerAliveInterval=15" in R.SSH_OPTS
    llamadas = []

    class Resultado:
        returncode = 1
        stderr = "sin red"

    def falso(cmd, **k):
        llamadas.append(cmd)
        return Resultado()

    monkeypatch.setattr(R.subprocess, "run", falso)
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    with pytest.raises(R.RemoteError):
        R.RemoteJob("u@h", job_dir="jobs/x").descargar("/tmp/x")
    assert len(llamadas) == R.INTENTOS_DESCARGA
    assert any(a.startswith("--timeout=") for a in llamadas[0])


def test_launching_twice_after_a_cut_starts_one_calculation_only(tmp_path):
    """El mismo comando que se envia al servidor, ejecutado aqui con otro programa."""
    import subprocess
    (tmp_path / "remote_job.py").write_text("print('calculo')\n")
    llamadas = []

    class Probe(RemoteJob):
        def _run(self, comando, timeout=30):
            llamadas.append(comando)
            subprocess.run(["sh", "-c", comando.replace("setsid nohup python3 remote_job.py", "echo lanzado")],
                           cwd=tmp_path, check=True)

    t = Probe("u@h", job_dir="jobs/x")
    t.lanzar()
    t.lanzar()
    import time
    time.sleep(0.3)
    assert (tmp_path / "job.log").read_text().count("lanzado") == 1


def test_a_slow_link_reads_the_log_in_smaller_pieces(monkeypatch):
    """Con 2 MB fijos y una red lenta, la lectura se agotaba siempre en el mismo sitio."""
    from core import remote_runner as rr
    import subprocess
    pedidos = []

    class Salida:
        returncode = 0
        stderr = b""
        stdout = b"x" * 10

    def falso(cmd, **_k):
        pedidos.append(int(cmd[-1].rsplit(" ", 1)[1]))
        if len(pedidos) <= 2:
            raise subprocess.TimeoutExpired(cmd, 60)
        return Salida()

    monkeypatch.setattr(rr.subprocess, "run", falso)
    t = RemoteJob("u@h", job_dir="jobs/x")
    for _ in range(2):
        with pytest.raises(subprocess.TimeoutExpired):
            t.leer_log()
    assert t.leer_log() == "x" * 10 and t.offset == 10
    t.leer_log()
    assert pedidos == [2_000_000, 1_000_000, 500_000, 1_000_000]


def test_the_server_check_tells_physical_cores_from_threads(monkeypatch):
    from types import SimpleNamespace
    from core import remote_runner as rr
    salida = "20\n3.0\nrsync\npython3\n/opt/openfoam12/etc/bashrc\nfin\n14\n"
    monkeypatch.setattr(rr, "_ssh", lambda *a, **k: SimpleNamespace(returncode=0, stdout=salida, stderr=""))
    d = rr.probar_servidor("u@h")
    assert (d["nucleos"], d["fisicos"], d["libres"]) == (20, 14, 11)
    # Sin lscpu se usa lo que dijo nproc
    salida = "8\n1.0\nrsync\npython3\nfin\n0\n"
    d = rr.probar_servidor("u@h")
    assert (d["fisicos"], d["openfoam"]) == (8, "")


def test_more_processes_than_cores_are_not_refused():
    fuente = open(os.path.join(os.path.dirname(__file__), "..", "core", "remote_job.py")).read()
    assert '"--oversubscribe"' in fuente


def _cola_falsa(tmp_path, ocupadas):
    """Carpeta de trabajo con flock y python3 falsos: flock sale con 75 si la ranura esta ocupada."""
    import os, stat
    from core.remote_runner import JOBS_DIR, script_cola
    binarios = tmp_path / "bin"; binarios.mkdir()
    (binarios / "flock").write_text(
        "#!/bin/bash\n# flock -n -E 75 RANURA orden...\nr=$4; shift 4\n"
        f"case \"$r\" in *ranura_[{''.join(map(str, ocupadas)) or '0'}]) exit 75;; esac\n"
        "echo \"$r\" > ranura_usada; exec \"$@\"\n")
    (binarios / "python3").write_text("#!/bin/bash\necho corrio > corrio\nexit 0\n")
    for b in binarios.iterdir():
        b.chmod(b.stat().st_mode | stat.S_IEXEC)
    caso = tmp_path / "caso"; caso.mkdir()
    (caso / "cola.sh").write_text(script_cola(2))
    entorno = dict(os.environ, PATH=f"{binarios}:{os.environ['PATH']}", HOME=str(tmp_path))
    (tmp_path / JOBS_DIR).mkdir()
    return caso, entorno


def test_server_queue_runs_the_package_in_a_free_slot(tmp_path):
    import subprocess
    caso, entorno = _cola_falsa(tmp_path, ocupadas=[1])
    r = subprocess.run(["bash", "cola.sh"], cwd=caso, env=entorno, timeout=20)
    assert r.returncode == 0 and (caso / "corrio").exists()
    assert (caso / "ranura_usada").read_text().strip().endswith(".ranura_2")


def test_a_job_waiting_in_the_server_queue_says_so_and_can_be_stopped(tmp_path):
    import json, signal, subprocess, time
    caso, entorno = _cola_falsa(tmp_path, ocupadas=[1, 2])
    p = subprocess.Popen(["bash", "cola.sh"], cwd=caso, env=entorno, start_new_session=True)
    time.sleep(1.5)
    estado = json.loads((caso / "status.json").read_text())
    assert estado["state"] == "running" and estado["step"] == "en cola" and estado["pgid"] == p.pid
    import os
    os.killpg(p.pid, signal.SIGTERM)
    p.wait(25)
    assert json.loads((caso / "status.json").read_text())["state"] == "stopped"
    assert not (caso / "corrio").exists()
