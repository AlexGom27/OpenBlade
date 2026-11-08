"""La ficha identifica el paquete y un paquete alterado no se calcula."""

import hashlib
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import remote_job
from core.package import (build_ficha, complete_ficha, mesh_notice, package_files,
                          parse_checkmesh, read_ficha, sha256_file)
from core.remote_runner import RemoteError, RemoteJob, interpret_status

CHECKMESH_REAL = """Build  : 12-86e126a7bc4d
Mesh stats
    points:           118348
    cells:            58608
Checking geometry...
    Overall domain bounding box (-24.8176 -25 0) (50.9927 25 0.1)
 ***High aspect ratio cells found, Max aspect ratio: 72435.3, number of cells 5508
    Minimum face area = 9.32245e-09. Maximum face area = 4.03222.  Face area magnitudes OK.
    Min volume = 9.32245e-10. Max volume = 0.403222.  Total volume = 352.94.  Cell volumes OK.
    Mesh non-orthogonality Max: 76.7971 average: 5.78891
   *Number of severely non-orthogonal (> 70 degrees) faces: 11.
    Non-orthogonality check OK.
    Max skewness = 0.359438 OK.

Failed 1 mesh checks.

End
"""


@pytest.fixture
def caso(tmp_path, monkeypatch):
    for ruta, texto in (("0/U", "u"), ("system/controlDict", "c"), ("constant/transportProperties", "t"),
                        ("constant/polyMesh/boundary", "b"), ("mesh.msh", "m"), ("job.json", "{}")):
        destino = tmp_path / ruta
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_ficha_lists_every_file_of_the_package_except_the_converted_mesh(caso):
    ficha = build_ficha(str(caso), {"aoa": 8.0, "server_host": "u@h", "fsi_E": 1.0})
    assert sorted(ficha["archivos"]) == sorted(
        ["0/U", "system/controlDict", "constant/transportProperties", "mesh.msh", "job.json"])
    assert ficha["archivos"]["0/U"] == sha256_file("0/U")
    assert ficha["parametros"] == {"aoa": 8.0}
    assert "gmsh" in ficha["versiones"]
    assert read_ficha(str(caso)) == ficha


def test_package_files_are_listed_in_stable_order(caso):
    assert package_files(str(caso)) == ["0/U", "constant/transportProperties", "system/controlDict"]


def test_mesh_method_goes_into_the_ficha(caso):
    (caso / "mesh.msh.info.json").write_text('{"mallador": "no estructurada"}')
    assert build_ficha(str(caso), {}, str(caso / "mesh.msh"))["malla"]["mallador"] == "no estructurada"


def test_intact_package_is_accepted_and_ficha_hash_returned(caso):
    build_ficha(str(caso), {})
    assert remote_job.verificar_paquete() == sha256_file("ficha.json")


@pytest.mark.parametrize("alterar,mensaje", [
    (lambda c: (c / "system/controlDict").write_text("otro"), "system/controlDict"),
    (lambda c: (c / "mesh.msh").write_text("otra malla"), "mesh.msh"),
    (lambda c: (c / "0/U").unlink(), "0/U"),
    (lambda c: (c / "0/k").write_text("sobra"), "0/k"),
])
def test_altered_package_is_rejected(caso, alterar, mensaje):
    build_ficha(str(caso), {})
    alterar(caso)
    with pytest.raises(RuntimeError, match=mensaje):
        remote_job.verificar_paquete()


def test_package_without_ficha_is_rejected(caso):
    with pytest.raises(RuntimeError, match="ficha"):
        remote_job.verificar_paquete()


def test_real_checkmesh_output_is_parsed():
    d = parse_checkmesh(CHECKMESH_REAL)
    assert d["celdas"] == 58608 and d["fallos"] == 1 and not d["ok"]
    assert d["aspecto_max"] == 72435.3
    assert d["no_ortogonalidad_max"] == 76.7971 and d["no_ortogonalidad_media"] == 5.78891
    assert d["caras_no_ortogonales"] == 11 and d["sesgo_max"] == 0.359438
    assert d["solo_aspecto"]


def test_boundary_layer_aspect_ratio_alone_is_not_a_mesh_failure():
    aviso = mesh_notice(parse_checkmesh(CHECKMESH_REAL))
    assert aviso["level"] == "aviso" and "11 caras" in aviso["text"]
    limpio = CHECKMESH_REAL.replace("   *Number of severely non-orthogonal (> 70 degrees) faces: 11.\n", "")
    assert mesh_notice(parse_checkmesh(limpio))["level"] == "ok"


def test_other_failures_are_a_mesh_problem():
    roto = CHECKMESH_REAL.replace("Failed 1", "Failed 2") + " ***Error in face pyramids: 3 faces\n"
    assert mesh_notice(parse_checkmesh(roto))["level"] == "mal"
    assert mesh_notice(None) is None


def test_ficha_is_completed_with_execution_and_result(caso):
    build_ficha(str(caso), {})
    (caso / "run.log").write_text('Build  : 12-86e126a7bc4d\nHost   : "openblade2"\nnProcs : 8\n')
    (caso / "log.checkMesh").write_text(CHECKMESH_REAL)
    f = caso / "postProcessing" / "forceCoeffs" / "0"
    f.mkdir(parents=True)
    (f / "forceCoeffs.dat").write_text("# Time Cm Cd Cl Cl(f) Cl(r)\n1 0 0 0 0 0\n")
    ficha = complete_ficha(str(caso), {"verdict": {"state": "CONVERGIDO"}}, 0, "u@h", "jobs/x")
    assert ficha["ejecucion"]["openfoam_build"] == "12-86e126a7bc4d"
    assert ficha["ejecucion"]["procesos"] == "8"
    assert ficha["checkmesh"]["celdas"] == 58608
    assert ficha["resultado"]["verdict"]["state"] == "CONVERGIDO"
    assert list(ficha["fuerzas_sha256"]) == [os.path.join("postProcessing", "forceCoeffs", "0", "forceCoeffs.dat")]


def test_job_that_never_started_is_a_failure_not_running():
    est = interpret_status("", "", "python3: command not found")
    assert est["state"] == "failed" and "command not found" in est["error"]


def test_job_without_status_yet_is_running():
    assert interpret_status("", "", "")["state"] == "running"
    assert interpret_status('{"state": "done"}', "", "")["state"] == "done"


def test_job_whose_process_died_is_a_failure_not_running_forever():
    """Hallado por OpenClaw: un reinicio del servidor dejaba el seguimiento en un bucle."""
    vivo = interpret_status('{"state": "running", "step": "solver", "pid": 7}', "vivo", "")
    assert vivo["state"] == "running"
    muerto = interpret_status('{"state": "running", "step": "solver", "pid": 7}', "muerto", "")
    assert muerto["state"] == "failed" and "solver" in muerto["error"]
    # Si ya termino, que el proceso no exista es lo normal.
    assert interpret_status('{"state": "done", "pid": 7}', "muerto", "")["state"] == "done"


def test_unreadable_status_is_a_failure():
    assert interpret_status("{corrupto", "", "")["state"] == "failed"


def test_other_ficha_on_the_server_stops_the_run():
    job = RemoteJob("u@h", job_dir="jobs/x")
    job.ficha_sha256 = "a"
    job.comprobar_ficha({"ficha_sha256": "a"})
    job.comprobar_ficha({})
    with pytest.raises(RemoteError):
        job.comprobar_ficha({"ficha_sha256": "b"})


def test_report_shows_verdict_sheet_and_warns_when_not_valid(tmp_path):
    """El informe dice el veredicto antes que los numeros, y la ficha del calculo."""
    from core.report_generator import generate_pdf_report
    ficha = {"programa": {"commit": "abc123def456", "modificados": []}, "versiones": {"gmsh": "4.15.2"},
             "archivos": {"mesh.msh": "f" * 64}, "ejecucion": {"openfoam_build": "12-86e126a7bc4d", "maquina": "u@h",
                                                               "procesos": "8"},
             "checkmesh": {"celdas": 57344, "no_ortogonalidad_max": 28.0, "sesgo_max": 1.2}}
    analisis = {"verdict": {"state": "NO CONVERGIDO", "reason": "Cd varía 3 %", "cl": 1.07, "cl_amp": 0.01, "cd": 0.012,
                            "cd_amp": 0.001, "cm": 0.0, "cm_amp": 0.0, "window": 500, "n_rows": 6000, "transient": False},
                "yplus_notice": {"level": "ok", "text": "y+ medio 0.70"}}
    ruta = tmp_path / "informe.pdf"
    generate_pdf_report(str(ruta), {"naca": "0012", "aoa": 10.0}, analisis, {}, ficha)
    assert ruta.stat().st_size > 1000
    divergido = dict(analisis, verdict=dict(analisis["verdict"], state="DIVERGIDO", cl=None))
    generate_pdf_report(str(tmp_path / "d.pdf"), {"naca": "0012"}, divergido, {}, None)
    assert (tmp_path / "d.pdf").stat().st_size > 1000


def test_the_sheet_states_the_opening_of_the_trailing_edge():
    from core.report_generator import _tabla_ficha

    filas = dict(map(tuple, _tabla_ficha({"malla": {"abertura_borde_salida": 0.01}})))
    assert filas["Abertura del borde de salida"].startswith("1.00 %")
    assert "Abertura del borde de salida" not in dict(map(tuple, _tabla_ficha({"malla": {}})))


# --- que codigo hizo el paquete: lo del arranque, no lo del disco -----------------

def _simular_arranque(monkeypatch, commit, script, modificados=()):
    """Deja fijada la instantanea de arranque del modulo, como al importarlo."""
    from core import package as P

    monkeypatch.setattr(P, "_ARRANQUE", {
        "commit": commit, "modificados": list(modificados), "script": script,
        "script_sha256": hashlib.sha256(script).hexdigest(),
        "tomado": "2026-11-08T06:00:00Z"})


def _git_que_dice(monkeypatch, commit):
    """El disco responde con ese HEAD; el estado queda limpio."""
    from core import package as P

    monkeypatch.setattr(P, "_git", lambda *a: commit if a[:2] == ("rev-parse", "HEAD") else "")


def test_ficha_records_the_code_that_loaded_not_the_head_on_disk(caso, monkeypatch):
    """Un proceso vivo con codigo viejo no puede anotar el commit nuevo.

    Se cambio el HEAD despues de arrancar: la ficha sigue diciendo cual ejecuta, y
    ademas avisa de que el disco ya no coincide.
    """
    _simular_arranque(monkeypatch, "1817b2d" + "0" * 33, b"#!/usr/bin/env python3\nVIEJO\n")
    _git_que_dice(monkeypatch, "05a6ad3" + "0" * 33)
    ficha = build_ficha(str(caso), {})
    assert ficha["programa"]["commit"].startswith("1817b2d")
    assert ficha["programa"]["commit_disco"].startswith("05a6ad3")


def test_a_matching_disk_adds_no_noise(caso, monkeypatch):
    """Si el disco coincide, la ficha no lleva commit_disco ni ruido."""
    sha = hashlib.sha256(b"x").hexdigest()
    _simular_arranque(monkeypatch, "a" * 40, b"x")
    _git_que_dice(monkeypatch, "a" * 40)
    prog = build_ficha(str(caso), {})["programa"]
    assert prog["commit"] == "a" * 40
    assert "commit_disco" not in prog
    assert prog["remote_job_sha256"] == sha


def test_the_script_sent_is_the_one_in_memory(caso, monkeypatch, tmp_path):
    """El remote_job.py del disco cambio: se envia el del arranque, no el de ahora."""
    viejo = b"#!/usr/bin/env python3\n# el que se cargo al arrancar\n"
    _simular_arranque(monkeypatch, "a" * 40, viejo)
    _git_que_dice(monkeypatch, "a" * 40)
    malla = tmp_path / "m.msh"
    malla.write_bytes(b"malla")

    job = RemoteJob("u@h", "openblade_jobs/x")
    enviado = {}

    def falso_rsync(self, origen, destino, excluir, intentos=0, opts=None):
        enviado["script"] = open(os.path.join(origen, "remote_job.py"), "rb").read()
        enviado["ficha"] = json.load(open(os.path.join(origen, "ficha.json")))

    monkeypatch.setattr(RemoteJob, "_rsync", falso_rsync)
    monkeypatch.setattr("core.remote_runner._ssh", lambda *a, **k: type(
        "R", (), {"returncode": 0, "stdout": "", "stderr": ""})())

    job.subir(str(caso), str(malla), 8, False, {"max_iters": 100})
    assert enviado["script"] == viejo
    # Y la ficha declara ese mismo sha, no el del archivo del disco.
    assert enviado["ficha"]["archivos"]["remote_job.py"] == sha256_file_bytes(viejo)
    assert enviado["ficha"]["programa"]["remote_job_sha256"] == sha256_file_bytes(viejo)


def sha256_file_bytes(datos):
    return hashlib.sha256(datos).hexdigest()


# --- la misma prueba, con un repositorio de verdad -------------------------------

def _repo_temporal(tmp_path):
    """Un repo minimo con core/remote_job.py, para cambiarle el HEAD de verdad."""
    repo = tmp_path / "repo"
    (repo / "core").mkdir(parents=True)
    (repo / "core" / "__init__.py").write_text("")
    (repo / "core" / "remote_job.py").write_text("print('v1')\n")
    (repo / "gui").mkdir()
    for orden in (["init", "-q", "-b", "main"], ["add", "-A"]):
        subprocess.run(["git", "-C", str(repo)] + orden, check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-qm", "v1"], check=True, capture_output=True)
    return repo


def _commitear(repo, texto):
    (repo / "core" / "remote_job.py").write_text(texto)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-qm", "v2"], check=True, capture_output=True)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def test_the_snapshot_survives_a_commit_made_while_the_process_lives(tmp_path, monkeypatch):
    """Lo que de verdad pasaba: un commit despues de arrancar cambia la ficha.

    Con el codigo de antes, la ficha anotaba el commit nuevo aunque el proceso
    siguiera ejecutando el viejo. Aqui se comprueba el comportamiento, no el nombre
    de una variable interna.
    """
    from core import package as P

    repo = _repo_temporal(tmp_path)
    monkeypatch.setattr(P, "RAIZ", str(repo))
    monkeypatch.setattr(P, "_ARRANQUE", None)      # el modulo "arranca" aqui
    al_arrancar = P.program_version()
    script_al_arrancar = P.script_servidor()

    nuevo = _commitear(repo, "print('v2')\n")     # otro commit, el proceso sigue vivo

    despues = P.program_version()
    assert despues["commit"] == al_arrancar["commit"], "la ficha anota el commit del disco"
    assert despues["commit_disco"] == nuevo, "no se avisa de que el disco ya no coincide"
    assert P.script_servidor() == script_al_arrancar, "se enviaria el script del disco"
    # Y lo que se envia al servidor es ese texto, con su sha en la ficha.
    (tmp_path / "caso" / "system").mkdir(parents=True)
    (tmp_path / "caso" / "mesh.msh").write_bytes(b"malla")
    ficha = P.build_ficha(str(tmp_path / "caso"), {})
    assert ficha["programa"]["commit"] == al_arrancar["commit"]
    assert ficha["programa"]["remote_job_sha256"] == \
        hashlib.sha256(script_al_arrancar).hexdigest()
