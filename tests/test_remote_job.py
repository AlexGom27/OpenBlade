"""El servidor decide solo cuando terminar, sin depender de la Mac.

Antes lo decidia la Mac leyendo run.log. Con la maquina inalcanzable (Tailscale
caido 8021 s seguidos en el caso de control) nadie veia la convergencia: una
maquina paro en 16000 y la otra en 40000, y la compuerta "mismas fuerzas entre
maquinas" fallaba aunque las fuerzas eran identicas hasta donde coincidian.
"""

import os

import pytest

from core import jobs as J
from core import remote_job as R


def test_the_server_and_the_mac_agree_on_when_to_stop():
    """Las dos copias del vigilante tienen que dar el mismo final.

    `remote_job.py` se sube al servidor y solo puede usar la biblioteca estandar,
    asi que no puede importar `core.jobs`: las constantes estan repetidas. Si una
    cambia y la otra no, el mismo paquete terminaria en un sitio u otro segun
    quien lo pare.
    """
    v = J._Vigilancia
    assert R.CADA_CONVERGENCIA == v.CADA_CONVERGENCIA
    assert R.MARGEN == v.MARGEN
    assert R.MINIMO == v.MINIMO
    assert R.VENTANA == v.VENTANA
    assert R.TOL_RANGO_CD == v.TOL_RANGO_CD
    assert R.TOL_RANGO_CL == v.TOL_RANGO_CL
    assert R.TOL_DERIVA_CD == v.TOL_DERIVA_CD
    assert R.TOL_DERIVA_CL == v.TOL_DERIVA_CL


def _serie(n, cd=0.0088, cl=0.861, ruido_cd=0.0, ruido_cl=0.0):
    """Una corrida sintetica que se queda quieta, con el mismo ruido que una real."""
    import math
    return ([cd + ruido_cd * math.sin(i / 7.0) for i in range(n)],
            [cl + ruido_cl * math.sin(i / 5.0) for i in range(n)])


def _primera_convergencia(vigia, cd, cl):
    for i in range(len(cd)):
        vigia.cl.append(cl[i])
        vigia.cd.append(cd[i])
        vigia.n += 1
        if vigia.n % 100 == 0 and vigia.convergio():
            return vigia.n, vigia.final_previsto()
    return None


def test_both_watchers_stop_at_the_same_iteration():
    cd, cl = _serie(20000, ruido_cd=0.00002, ruido_cl=0.0002)
    mac = _primera_convergencia(J._Vigilancia(), cd, cl)
    servidor = _primera_convergencia(R._Convergencia(), cd, cl)
    assert mac is not None
    assert mac == servidor


def test_a_run_that_still_drifts_is_not_stopped():
    """Cd todavia subiendo despacio: pararlo daria un numero que no es el de la corrida.

    Es el caso de una malla fina: dentro de una ventana de 500 vueltas el Cd parece
    quieto, pero la media de un tramo no coincide con la del anterior.
    """
    cd = [0.0088 * (1.0 + 1e-5 * i) for i in range(20000)]
    cl = [0.861] * 20000
    assert _primera_convergencia(R._Convergencia(), cd, cl) is None


def test_the_server_shortens_end_time_instead_of_killing_the_solver(tmp_path, monkeypatch):
    """Se reescribe endTime: OpenFOAM termina solo y escribe campos y fuerzas."""
    caso = tmp_path / "case"
    (caso / "system").mkdir(parents=True)
    control = caso / "system" / "controlDict"
    control.write_text("FoamFile {}\n\nendTime         40000;\nwriteInterval   100;\n")
    monkeypatch.chdir(caso)

    R.recortar_final(16000)
    texto = control.read_text()
    assert "endTime         16000;" in texto
    assert "writeInterval   100;" in texto          # lo demas no se toca
    assert texto.count("endTime") == 1


def test_the_watcher_cuts_the_run_when_the_forces_settle(tmp_path, monkeypatch):
    """Con el log de una corrida que ya se quedo quieta, el final se adelanta."""
    caso = tmp_path / "case"
    (caso / "system").mkdir(parents=True)
    (caso / "system" / "controlDict").write_text("endTime         40000;\n")
    monkeypatch.chdir(caso)

    lineas = []
    for i in range(14000):
        lineas.append(f"Time = {i}")
        # Deriva al principio y quieto despues: converge en la 13000, como el control real.
        cd = 0.0088 + 0.001 * max(0, 11000 - i) / 11000 + 1e-5 * (i % 7)
        lineas.append(f"    Cd: {cd}")
        lineas.append(f"    Cl: {0.861 + 1e-4 * (i % 5)}")
    (caso / "run.log").write_text("\n".join(lineas) + "\n")

    class Proceso:
        """Finge seguir vivo hasta que se le recorta el final."""

        def __init__(self):
            self.vivo = True

        def poll(self):
            texto = (caso / "system" / "controlDict").read_text()
            return None if "40000" in texto else 0

    monkeypatch.setattr(R.time, "sleep", lambda _s: None)
    R.vigilar_y_parar(Proceso(), 40000)
    assert "endTime         16000;" in (caso / "system" / "controlDict").read_text()


def test_a_transient_run_is_never_cut(monkeypatch):
    """En transitorio manda el tiempo fisico: recortarlo cambiaria el resultado."""
    import subprocess

    llamado = {}

    class Proceso:
        def wait(self):
            return 0

    def falso_popen(*a, **k):
        llamado["popen"] = True
        return Proceso()

    monkeypatch.setattr(R.subprocess, "Popen", falso_popen)
    monkeypatch.setattr(R, "vigilar_y_parar", lambda *a: llamado.setdefault("vigilo", True))
    with open(os.devnull, "w") as _:
        pass
    R.correr_vigilado(["true"], {}, os.devnull, 40000, True)
    assert llamado.get("popen") and "vigilo" not in llamado


def test_the_mac_never_lengthens_a_final_the_server_already_shortened(monkeypatch):
    """Las dos pueden decidir; la que llega tarde no puede deshacer lo hecho.

    Si el servidor recorto a 13000 porque no habia red, y luego la Mac (que ve el log
    con retraso) calcula 16000, escribir 16000 alargaria una corrida ya recortada.
    """
    from core import remote_runner as RR

    ordenes = []

    # _run devuelve texto, no el proceso: el doble tiene que imitar eso o la prueba
    # pasa con un codigo que en el servidor revienta.
    class Falso:
        def _run(self, comando, timeout=0):
            ordenes.append(comando)
            return "endTime         13000;\n" if comando.startswith("grep") else ""

    RR.RemoteJob.terminar_en(Falso(), 16000)
    assert not any("sed -i" in c for c in ordenes)

    ordenes.clear()
    class Falso2(Falso):
        def _run(self, comando, timeout=0):
            ordenes.append(comando)
            return "endTime         40000;\n" if comando.startswith("grep") else ""

    RR.RemoteJob.terminar_en(Falso2(), 16000)
    assert any("endTime         16000;" in c for c in ordenes)


def test_the_package_tells_the_server_the_iteration_limit(tmp_path, monkeypatch):
    """Sin max_iters en el paquete, el vigilante del servidor no haria nada.

    Lo tenia solo la Mac, en job.params; el job.json que se sube es otro y no lo
    llevaba, asi que el arreglo habria quedado desactivado sin que nada fallara.
    """
    import json

    from core import remote_runner as RR

    caso = tmp_path / "case"
    caso.mkdir()
    malla = tmp_path / "m.msh"
    malla.write_bytes(b"malla")

    # El paquete se borra del caso tras subirlo: se lee en el momento de subir.
    visto = {}

    def falso_rsync(self, origen, destino, excluir, intentos=0, opts=None):
        visto.update(json.load(open(os.path.join(origen, "job.json"))))

    monkeypatch.setattr(RR.RemoteJob, "_rsync", falso_rsync)
    monkeypatch.setattr(RR, "_ssh", lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    # La ficha y sus sha256 no son lo que se prueba: se dejan pasar.
    import core.package as PK

    monkeypatch.setattr(PK, "build_ficha", lambda *a, **k: {})
    monkeypatch.setattr(PK, "sha256_file", lambda *a, **k: "x")

    job = RR.RemoteJob("u@h", "openblade_jobs/x")
    job.subir(str(caso), str(malla), 8, False, {"max_iters": 40000})
    assert visto["max_iters"] == 40000
    assert visto["transient"] is False
    assert not os.path.exists(caso / "job.json")      # no se queda en el caso


def test_shortening_the_run_works_through_the_real_run(monkeypatch):
    """El caso tal cual fallo: terminar_en por el _run de verdad, con _ssh simulado.

    _run devuelve el texto de stdout, no un CompletedProcess. El doble anterior
    devolvia un objeto con .stdout y ocultaba que en la maquina real esto reventaba
    con "'str' object has no attribute 'stdout'": el trabajo se marcaba fallido
    despues de haber convergido, y no se descargaba.
    """
    from core import remote_runner as RR

    ordenes = []

    def falso_ssh(host, comando, timeout=0):
        ordenes.append(comando)
        salida = "endTime         40000;\n" if "grep" in comando else ""
        return type("R", (), {"stdout": salida, "stderr": "", "returncode": 0})()

    monkeypatch.setattr(RR, "_ssh", falso_ssh)
    RR.RemoteJob.terminar_en(RR.RemoteJob("u@h", "openblade_jobs/x"), 16000)

    assert any("grep" in c for c in ordenes)
    assert any("endTime         16000;" in c for c in ordenes), "no se recorto"


def test_shortening_never_lengthens_through_the_real_run(monkeypatch):
    """Y si el servidor ya recorto mas, no se alarga: tampoco por el _run real."""
    from core import remote_runner as RR

    ordenes = []
    monkeypatch.setattr(RR, "_ssh", lambda h, c, timeout=0: type(
        "R", (), {"stdout": "endTime         13000;\n" if "grep" in c else "",
                  "stderr": "", "returncode": 0})())
    ordenes.clear()
    RR.RemoteJob.terminar_en(RR.RemoteJob("u@h", "openblade_jobs/x"), 16000)
    assert not any("sed -i" in c for c in ordenes)
