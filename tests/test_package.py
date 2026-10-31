"""La ficha identifica el paquete y un paquete alterado no se calcula."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import remote_job
from core.package import (build_ficha, complete_ficha, mesh_notice, package_files,
                          parse_checkmesh, read_ficha, sha256_file)
from core.remote_runner import RemoteJob, RemoteError

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


def _trabajo_con_salida(monkeypatch, salida):
    job = RemoteJob("u@h", job_dir="jobs/x")
    monkeypatch.setattr(job, "_run", lambda *a, **k: salida)
    return job


def test_job_that_never_started_is_a_failure_not_running(monkeypatch):
    job = _trabajo_con_salida(monkeypatch, "\n--\npython3: command not found\n")
    est = job.estado()
    assert est["state"] == "failed" and "command not found" in est["error"]


def test_job_without_status_yet_is_running(monkeypatch):
    assert _trabajo_con_salida(monkeypatch, "\n--\n").estado()["state"] == "running"
    assert _trabajo_con_salida(monkeypatch, '{"state": "done"}').estado()["state"] == "done"


def test_other_ficha_on_the_server_stops_the_run():
    job = RemoteJob("u@h", job_dir="jobs/x")
    job.ficha_sha256 = "a"
    job.comprobar_ficha({"ficha_sha256": "a"})
    job.comprobar_ficha({})
    with pytest.raises(RemoteError):
        job.comprobar_ficha({"ficha_sha256": "b"})
