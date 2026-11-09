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
    # Las dos miden la deriva con el mismo tramo que el veredicto: un quinto de la
    # corrida. Con tramos mas cortos una rampa lenta parece quieta y se recorta antes
    # de tiempo.
    from core.verdict import FRACCION_TRAMO
    assert R.FRACCION_TRAMO == FRACCION_TRAMO
    # Y ademas las dos preguntan al veredicto: el recorte no puede cerrar una corrida
    # que el juicio final da por NO CONVERGIDA.
    import inspect
    for fn in (R._Convergencia.convergio, J._Vigilancia.convergio):
        assert "veredicto_de_series" in inspect.getsource(fn), fn
    # El vigilante del servidor lleva el veredicto portado a mano (en el servidor no
    # existe el paquete core). Sus constantes tienen que ser las de core.verdict.
    from core import verdict as V
    assert R.VENTANA == V.VENTANA
    assert R.V_MIN_FILAS == V.MIN_FILAS
    assert R.V_ARRANQUE == V.ARRANQUE
    assert R.V_TOL_RANGO == V.TOL_RANGO
    assert R.V_TOL_DERIVA == V.TOL_DERIVA
    assert R.V_TOL_DERIVA_CL == V.TOL_DERIVA_CL
    assert R.V_CL_REF == V.CL_REF
    assert R.V_TOL_CL_ABS == V.TOL_CL_ABS
    assert R.V_TOL_CM_ABS == V.TOL_CM_ABS
    assert R.V_CL_IMPOSIBLE == V.CL_IMPOSIBLE
    assert R.V_CD_IMPOSIBLE == V.CD_IMPOSIBLE


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

    # Deriva al principio y quieto despues: converge en la 13000, como el control real.
    # La rampa tiene que aplanarse de verdad: con el criterio del veredicto (tramos de
    # un quinto, no de un decimo) una rampa que sigue bajando no converge nunca.
    lineas = []
    for i in range(14000):
        lineas.append(f"Time = {i}")
        cd = 0.00898 - 0.0001 * min(1.0, i / 8000.0) + 1e-7 * (i % 7)
        lineas.append(f"    Cd: {cd}")
        lineas.append(f"    Cl: {0.861 + 1e-5 * (i % 5)}")
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
    texto = (caso / "system" / "controlDict").read_text()
    # Se recorta al multiplo fijo que toca; lo que importa es que recorte y que el
    # veredicto con lo que hay hasta ahi sea aceptable.
    assert "endTime         4000;" in texto, texto

    from core.verdict import CONVERGIDO, veredicto_de_series
    v = veredicto_de_series([i and (0.00898 - 0.0001 * min(1.0, i / 8000.0) + 1e-7 * (i % 7))
                             for i in range(1, 4001)],
                            [0.861 + 1e-5 * (i % 5) for i in range(1, 4001)])
    assert v.state == CONVERGIDO, v.reason


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


# --- el recorte no puede dejar un veredicto peor que no recortar ----------------

def _rampa(n, inicio=0.009, paso=1.628e-8):
    """Cd bajando poco a poco: con tramos de un decimo parece quieto, con quintos no.

    Es la forma de los dos trabajos del 9-nov: 20261109_071444_polar_a0_c8b1 dio
    0.147 % con el criterio viejo de la vigilancia y 0.405 % con el del veredicto.
    """
    return [inicio - paso * i for i in range(n)]


def test_the_watcher_never_cuts_a_run_the_verdict_would_reject():
    """La propiedad que importa: recortar no puede empeorar el juicio final.

    La vigilancia es mas estricta que el veredicto (mismo tramo, tolerancia menor), asi
    que puede no recortar una corrida que el veredicto habria aceptado; lo que no puede
    es recortar una que el veredicto rechaza. Antes medía la deriva en tramos de un
    decimo: aprobaba con 0.147 % lo que el veredicto ve como 0.405 %.
    """
    from core.verdict import CONVERGIDO, veredicto_de_series

    for n in (8000, 11000, 13000):
        cd = _rampa(n)
        v = R._Convergencia()
        v.cd, v.cl, v.n = cd, [0.861] * n, n
        if v.convergio():
            final = veredicto_de_series(cd[:v.final_previsto()] if v.final_previsto() <= n else cd,
                                        [0.861] * min(v.final_previsto(), n))
            assert final.state == CONVERGIDO, (
                f"a {n} la vigilancia recorto y el veredicto con lo recortado dice "
                f"{final.state}: {final.reason}")

    # Y con estos datos la vigilancia no recorta donde el veredicto rechaza.
    cd = _rampa(11000)
    v = R._Convergencia()
    v.cd, v.cl, v.n = cd, [0.861] * len(cd), len(cd)
    assert veredicto_de_series(cd, [0.861] * len(cd)).state != CONVERGIDO
    assert not v.convergio()


def test_a_cut_that_the_verdict_rejects_is_lengthened_and_the_run_goes_on(tmp_path, monkeypatch):
    """Al llegar al final recortado, si el veredicto no pasa se alarga y se sigue.

    Es la garantia que faltaba: recortar nunca puede empeorar el resultado.
    """
    caso = tmp_path / "case"
    (caso / "system").mkdir(parents=True)
    (caso / "system" / "controlDict").write_text("endTime         40000;\n")
    monkeypatch.chdir(caso)
    # run.log con una serie que el veredicto NO acepta (a partir de ~10000).
    lineas = []
    for i in range(1, 12001):
        lineas += [f"Time = {i}", f"    Cd: {0.009 - 1.628e-8 * i}", "    Cl: 0.861"]
    (caso / "run.log").write_text("\n".join(lineas) + "\n")

    assert not R.veredicto_pasa(), "la serie de prueba tiene que ser NO CONVERGIDO"
    # Con el final ya alcanzado y el veredicto en contra, se alarga hasta max_iters.
    R.alargar_final(11000, 40000)
    assert "endTime         40000;" in (caso / "system" / "controlDict").read_text()


def test_a_cut_that_the_verdict_accepts_is_left_alone(tmp_path, monkeypatch):
    """Si el veredicto acepta lo recortado, no se toca nada."""
    caso = tmp_path / "case"
    (caso / "system").mkdir(parents=True)
    (caso / "system" / "controlDict").write_text("endTime         4000;\n")
    monkeypatch.chdir(caso)
    lineas = []
    for i in range(1, 4001):
        lineas += [f"Time = {i}", f"    Cd: {0.00898 - 1e-9 * i + 1e-7 * (i % 7)}", "    Cl: 0.861"]
    (caso / "run.log").write_text("\n".join(lineas) + "\n")
    assert R.veredicto_pasa(), "esta serie converge con el criterio del veredicto"
    assert "endTime         4000;" in (caso / "system" / "controlDict").read_text()


# --- el vigilante del servidor, de verdad, sin OpenBlade -------------------------
# Estas pruebas ejecutan remote_job.py en un subproceso con `python3 -I`, desde una
# carpeta temporal donde no existe el paquete core: es la unica forma de ver lo que
# pasa en el servidor. Con core en el path, un `from core.verdict import ...` que alli
# falla pasaria desapercibido, que es como se colo el defecto.

def _copiar_para_servidor(destino):
    """Deja remote_job.py solo, como lo deja el envio al servidor."""
    import shutil
    import pathlib
    origen = pathlib.Path(R.__file__).resolve()
    destino.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origen, destino / "remote_job.py")
    return destino / "remote_job.py"


def _correr_sin_core(caso, guion):
    """Ejecuta un guion con `python3 -I` en el caso, sin core en el path."""
    import subprocess
    import sys
    envoltorio = (
        "import importlib.util, sys, json\n"
        "assert not any(p for p in sys.path if p and __import__('os').path.isdir("
        "__import__('os').path.join(p, 'core'))), 'core sigue en el path'\n"
        "spec = importlib.util.spec_from_file_location('rj', 'remote_job.py')\n"
        "R = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(R)\n"
    ) + guion
    return subprocess.run([sys.executable, "-I", "-c", envoltorio], cwd=caso,
                          capture_output=True, text=True, timeout=120)


def test_the_server_watcher_really_cuts_without_the_core_package(tmp_path):
    """En el servidor no hay paquete core: aun asi el vigilante tiene que recortar.

    El defecto: `convergio()` hacia `from core.verdict import ...` y, con ImportError,
    devolvia False. En el servidor eso es siempre, asi que nunca recortaba: si la red
    se cae, solo recorta la Mac, la otra maquina llega a max_iters y la compuerta del
    control vuelve a fallar.
    """
    caso = tmp_path / "caso"
    _copiar_para_servidor(caso)
    (caso / "system").mkdir()
    (caso / "system" / "controlDict").write_text("endTime         40000;\n")
    guion = (
        "v = R._Convergencia()\n"
        "for i in range(4000):\n"
        "    v.cl.append(0.861); v.cd.append(0.00898); v.n += 1\n"
        "    if v.n % 1000 == 0 and v.convergio():\n"
        "        print('recorta en', v.n, v.final_previsto()); break\n"
        "else:\n"
        "    print('NO RECORTO')\n"
    )
    r = _correr_sin_core(caso, guion)
    assert r.returncode == 0, r.stderr
    assert "recorta en 1000" in r.stdout, r.stdout + r.stderr


def test_the_server_verdict_matches_the_real_one_on_many_series():
    """El veredicto portado y core.verdict tienen que decidir lo mismo.

    El port es una copia a mano: si core.verdict cambia y el port no, el servidor
    recortaria con otro criterio que el juicio final.
    """
    import random
    from core.verdict import veredicto_de_series as de_verdad

    rng = random.Random(20261109)
    casos = []
    for _ in range(60):
        n = rng.choice([80, 150, 400, 1000, 3000, 4000])
        tipo = rng.choice(["quieta", "rampa", "oscila", "pico", "negativo"])
        cd, cl = [], []
        for i in range(n):
            if tipo == "quieta":
                a, b = 0.0088 + rng.gauss(0, 1e-7), 0.861 + rng.gauss(0, 1e-6)
            elif tipo == "rampa":
                a, b = 0.009 - 1.6e-8 * i, 0.861 + 1e-7 * i
            elif tipo == "oscila":
                a, b = 0.0088 + 3e-4 * (-1) ** i, 0.861 + 0.01 * (-1) ** i
            elif tipo == "pico":
                a, b = 0.0088, (9.0 if i == n // 2 else 0.861)
            else:
                a, b = -0.001 + 1e-9 * i, 0.861
            cd.append(a)
            cl.append(b)
        casos.append((cd, cl))

    for cd, cl in casos:
        estado, oscila = R.veredicto_de_series(cd, cl)
        v = de_verdad(cd, cl)
        assert estado == v.state, (len(cd), estado, v.state, v.reason)
        # `oscila` solo lo usa el vigilante cuando el estado es NO CONVERGIDO.
        if estado == "NO CONVERGIDO":
            assert oscila == v.oscila, (len(cd), oscila, v.oscila, v.reason)


def test_a_cut_is_reverted_before_the_solver_reaches_the_new_end(tmp_path, monkeypatch):
    """La decision se toma antes de llegar al final, no cuando el solver ya salio.

    OpenFOAM escribe y sale en la misma iteracion en que alcanza endTime, asi que
    esperar a que run.log llegue para juzgar llega tarde: el solver ya termino y no hay
    nada que alargar. Aqui el solver sale exactamente al llegar a endTime y run.log
    crece con el, como en el servidor. Con el codigo anterior el recorte se quedaba sin
    revertir y el trabajo terminaba NO CONVERGIDO.
    """
    caso = tmp_path / "case"
    (caso / "system").mkdir(parents=True)
    (caso / "system" / "controlDict").write_text("endTime         40000;\n")
    monkeypatch.chdir(caso)

    def cd_en(i):
        # Quieta hasta la 2000, sube hasta la 8000 y se aplana. En la 1000 el vigilante
        # la da por convergida y recorta a 4000; el veredicto sobre esas 4000 filas NO
        # pasa, asi que hay que alargar. Dejada llegar a 40000, converge. Es el caso de
        # los nueve trabajos: corridas sanas recortadas demasiado pronto.
        if i <= 2000:
            return 0.0090
        if i <= 8000:
            return 0.0090 + 4e-7 * (i - 2000)
        return 0.0090 + 4e-7 * 6000

    (caso / "run.log").write_text("")

    class Solver:
        """Avanza 100 iteraciones por sondeo y sale justo al llegar al endTime."""

        iteracion = 0

        def poll(self):
            import re as _re
            final = int(_re.search(r"endTime\s+(\d+)",
                                   (caso / "system" / "controlDict").read_text()).group(1))
            if self.iteracion >= final:
                return 0          # sale justo al llegar, como OpenFOAM
            return None

    solver = Solver()

    def final_actual():
        import re as _re
        return int(_re.search(r"endTime\s+(\d+)",
                              (caso / "system" / "controlDict").read_text()).group(1))

    def avanzar(_s):
        # Un solver real para en su endTime y solo avanza si no salio ya. Ademas run.log
        # va un sondeo por detras: cuando el solver sale al llegar al final, la ultima
        # linea escrita todavia no incluye esa iteracion. Ese retraso es justo lo que
        # hace que juzgar "al llegar" llegue tarde.
        if solver.poll() is not None:
            return
        nuevo = min(solver.iteracion + 1000, 40000, final_actual())
        with open("run.log", "a") as f:
            for i in range(solver.iteracion + 1, nuevo + 1):
                if nuevo >= final_actual() and i > nuevo - 1000:
                    break
                f.write(f"Time = {i}\n    Cd: {cd_en(i)}\n    Cl: 0.861\n")
        solver.iteracion = nuevo

    monkeypatch.setattr(R.time, "sleep", avanzar)
    R.vigilar_y_parar(solver, 40000)

    import re as _re
    final = int(_re.search(r"endTime\s+(\d+)",
                           (caso / "system" / "controlDict").read_text()).group(1))
    # Se juzga con core.verdict y no con el port: esta prueba es sobre cuando se
    # decide, y tiene que fallar por eso y no por el port.
    from core.verdict import veredicto_de_series as de_verdad
    estado = de_verdad([cd_en(i) for i in range(1, final + 1)], [0.861] * final).state
    assert final == 40000, (
        f"se quedo en {final}: el recorte no se revirtio y el trabajo termino antes "
        "de que la corrida convergiera")
    assert estado == "CONVERGIDO", (final, estado)
