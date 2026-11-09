"""OpenBlade sin ventana: las mismas funciones que usa la interfaz.

    python3 -m core.cli correr --host usuario@host --procesos 8 aoa=8 reynolds=6e6
    python3 -m core.cli control --hosts usuario@a,usuario@b --procesos 8
    python3 -m core.cli banco --maquinas usuario@a:10:1,usuario@b:8:1 --salida carpeta
    python3 -m core.cli polar --maquinas usuario@a:10:1 --angulos 0,4,8 --gci 0,8 reynolds=6e6
    python3 -m core.cli doctor --hosts usuario@a,usuario@b

Cada simulacion sale de aqui o de la ventana; no hay otra forma de escribir un caso.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List

from core.defaults import case_params
from core.jobs import Dispatcher, Events, Job, Machine, new_job

ESPACIO_MINIMO_GB = 5.0


class _Consola(Events):
    def __init__(self) -> None:
        self.t0 = time.time()

    def _linea(self, job: Job, texto: str) -> None:
        print(f"[{time.time() - self.t0:6.0f}s] {job.label}: {texto}", flush=True)

    def state(self, job: Job) -> None:
        self._linea(job, job.state + (f" ({job.step})" if job.step else ""))

    def log(self, job: Job, texto: str) -> None:
        self._linea(job, texto)


def _valor(texto: str) -> Any:
    """Numero, booleano o texto, sin comillas en la linea de comandos."""
    try:
        return json.loads(texto)
    except ValueError:
        pass
    try:
        return float(texto)
    except ValueError:
        return texto


def _ajustes(pares: List[str]) -> Dict[str, Any]:
    ajustes = {}
    for par in pares:
        clave, igual, valor = par.partition("=")
        if not igual:
            raise SystemExit(f"Se esperaba clave=valor y llegó: {par}")
        ajustes[clave] = _valor(valor)
    return ajustes


def _resumen(job: Job) -> Dict[str, Any]:
    analisis = job.analysis or {}
    return {"id": job.id, "maquina": job.host, "estado": job.state, "error": job.error,
            "carpeta": job.case_dir, "veredicto": analisis.get("verdict"),
            "yplus": analisis.get("yplus"), "avisos": [
                (analisis.get(k) or {}).get("text") for k in ("yplus_notice", "mesh_notice")]}


def cmd_correr(args: argparse.Namespace) -> int:
    d = Dispatcher(_Consola())
    d.set_machines([Machine(args.host, args.procesos, 1)])
    job = new_job(case_params(**_ajustes(args.ajustes)), args.host, args.procesos, label=args.etiqueta or "")
    d.submit(job)
    d.wait()
    print(json.dumps(_resumen(job), indent=1, ensure_ascii=False))
    return 0 if (job.analysis or {}).get("verdict", {}).get("state") == "CONVERGIDO" else 1


def _resumen_control(r: Dict[str, Any]) -> bool:
    """Imprime las compuertas y dice si alguna falla."""
    falla = False
    for angulo, filas in r["por_angulo"].items():
        print(f"\nα = {angulo:g}")
        for f in filas:
            falla |= not f["ok"]
            print(f"  {f['n']}  {'pasa ' if f['ok'] else 'FALLA'}  {f['compuerta']}: {f['detalle']}")
    return falla


def cmd_control(args: argparse.Namespace) -> int:
    if args.evaluar:
        # Solo mirar: no se lanza ni se envia nada.
        from core.control import ControlIncompleto, evaluar_guardados

        try:
            r = evaluar_guardados(args.evaluar)
        except ControlIncompleto as e:
            print(str(e))
            return 2
        falla = _resumen_control(r)
        if args.salida:
            with open(args.salida, "w") as f:
                json.dump(r, f, indent=1, ensure_ascii=False)
        return 1 if falla else 0

    from core.control import run_control

    hosts = [h for h in args.hosts.split(",") if h]
    if not hosts:
        print("Falta --hosts, o usa --evaluar PREFIJO para no lanzar nada")
        return 2
    angulos = tuple(float(a) for a in args.angulos.split(","))
    r = run_control(hosts, args.procesos, angulos, _Consola())
    falla = _resumen_control(r)
    if args.salida:
        with open(args.salida, "w") as f:
            json.dump(r, f, indent=1, ensure_ascii=False)
    return 1 if falla else 0


def _maquinas(texto: str) -> List[Machine]:
    """usuario@host:procesos:simultaneos, separadas por comas."""
    maquinas = []
    for m in texto.split(","):
        host, _, resto = m.partition(":")
        procesos, _, simultaneos = resto.partition(":")
        maquinas.append(Machine(host, int(procesos or 8), int(simultaneos or 1)))
    return maquinas


def cmd_banco(args: argparse.Namespace) -> int:
    from core.bench import run_bench, write_report

    r = run_bench(_maquinas(args.maquinas), events=_Consola())
    ruta = write_report(r, args.salida)
    print(f"\nComprobaciones cumplidas: {r['cumplidas']} de {r['total']}. Informe: {ruta}")
    for f in r["filas"]:
        for x in f["comprobaciones"]:
            print(f"  {'cumple' if x['cumple'] else 'NO    '} {f['caso']['etiqueta']:22s} {x['nombre']:26s} "
                  f"{x['error']:+.3f} (tope {x['tope']:.3f}) {x['detalle']}")
    for x in r["dominio"]:
        print(f"  {'cumple' if x['cumple'] else 'NO    '} {'dominio':22s} {x['nombre']:26s} "
              f"{x['error']:+.3f} (tope {x['tope']:.3f}) {x['detalle']}")
    return 0 if r["cumplidas"] == r["total"] and not r["sin_converger"] else 1


def cmd_polar(args: argparse.Namespace) -> int:
    from core.campaign import run_polar, write_polar_report

    angulos = [float(a) for a in args.angulos.split(",")]
    gci = [float(a) for a in args.gci.split(",")] if args.gci else []
    r = run_polar(_maquinas(args.maquinas), _ajustes(args.ajustes), angulos, gci, _Consola(), args.urans,
                  continuar=args.continuar)
    print("\nFigura:", write_polar_report(r, args.salida))
    for f in r["filas"]:
        cl = "" if f["cl"] is None else f"Cl {f['cl']:.4f} ± {f['banda_cl'] or 0:.4f}  Cd {f['cd']:.5f} ± {f['banda_cd'] or 0:.5f}"
        cl += "  (oscila con media estable)" if f.get("oscila") else ""
        print(f"  α={f['aoa']:6.2f}  {str(f['veredicto']):14s} {cl}")
    return 0


def _versiones_distintas() -> List[str]:
    """Paquetes cuya version no es la de requirements.txt, con la que se verifico el programa."""
    from importlib import metadata

    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    distintos = []
    with open(os.path.join(raiz, "requirements.txt")) as f:
        for linea in f:
            nombre, _, pedida = linea.strip().partition("==")
            if not pedida or nombre.startswith("#"):
                continue
            try:
                instalada = metadata.version(nombre)
            except metadata.PackageNotFoundError:
                instalada = "no instalado"
            if instalada != pedida:
                distintos.append(f"{nombre} {instalada} (se verificó con {pedida})")
    return distintos


def stop_jobs(patrones: List[str]) -> List[Job]:
    """Detiene los trabajos cuyo id empieza por alguno de los patrones, corran o esperen en cola.

    Es lo que hace el boton de detener de la ventana: en el servidor se manda TERM al grupo
    de procesos de ese trabajo, y uno que espera ranura sale de la cola sin correr.
    """
    from core.jobs import DETENIDO, FINALES, LOCAL, load_jobs, make_runner
    elegidos = [j for j in load_jobs() if any(j.id.startswith(p) for p in patrones)]
    for j in elegidos:
        if j.state in FINALES:
            continue
        if j.remote_dir and j.host != LOCAL:
            make_runner(j).detener()
        j.state = DETENIDO
        j.save()
    return elegidos


def cmd_detener(args: argparse.Namespace) -> int:
    elegidos = stop_jobs(args.trabajos)
    if not elegidos:
        print("Ningún trabajo empieza así")
        return 1
    for j in elegidos:
        print(f"  {j.id}: {j.state}")
    return 0


# Lo que remote_job.py escribe en status.json cuando ya no va a seguir.
ESTADOS_FINALES_MAQUINA = ("done", "failed", "stopped")


def cmd_retomar(args: argparse.Namespace) -> int:
    """Termina y descarga trabajos que se quedaron a medias, sin volver a calcular.

    Sirve para lo que la ventana hace al abrirse, desde la linea de ordenes. Un trabajo
    fallido con el calculo ya hecho en su maquina (rc 0 en su status.json) se vuelve a
    seguir y se descarga; no se envia otra vez. Con --si-terminado solo se miran los que
    su maquina da por terminados, para no esperar a los que siguen calculando.
    """
    from core import owner
    from core.jobs import FINALES, LOCAL, load_jobs, make_runner, run_job

    elegidos = [j for j in load_jobs() if j.id.startswith(tuple(args.trabajos))]
    if not elegidos:
        print("Ningún trabajo empieza así")
        return 1
    pendientes = []
    for j in elegidos:
        if not j.remote_dir:
            print(f"  {j.id}: no llegó a enviarse; se relanza con su campaña")
            continue
        if j.state not in FINALES:
            print(f"  {j.id}: {j.state}, se sigue como está")
            pendientes.append(j)
            continue
        if j.host == LOCAL:
            print(f"  {j.id}: local; no hay nada que recuperar de una máquina")
            continue
        dueno = owner.de_otro(j)
        if dueno is not None:
            print(f"  {j.id}: {owner.describir(dueno)}. No se toca.")
            continue
        # Lo que decide es lo que diga su maquina, no lo que creyera la Mac al fallar.
        try:
            est = make_runner(j).estado()
        except Exception as e:  # noqa: BLE001
            print(f"  {j.id}: no se pudo preguntar a {j.host}: {str(e)[:100]}")
            continue
        # Solo se descarga lo que la maquina da por terminado. "running" no lo es: ni
        # calculando ni esperando ranura en cola.sh, que escribe "en cola" con state
        # running. Mirar el rc no basta: ausente o 0 no significan terminado.
        estado = est.get("state")
        if estado == "done":
            pass
        elif estado == "running":
            print(f"  {j.id}: sigue en {j.host} ({est.get('step') or 'sin paso'}"
                  f"{', en cola' if est.get('step') == 'en cola' else ''}); se deja")
            continue
        elif estado in ESTADOS_FINALES_MAQUINA:
            print(f"  {j.id}: en {j.host} falló (rc {est.get('rc')}): {str(est.get('error'))[:80]}")
            continue
        else:
            # Un estado que no conocemos no se toca: no vaya a ser una cola.
            print(f"  {j.id}: {j.host} informa «{estado}», que no es final; se deja")
            continue
        print(f"  {j.id}: terminado en {j.host}; se descarga")
        j.state, j.error, j.finished = "descargando", "", None
        j.save()
        pendientes.append(j)

    if not pendientes:
        print("Nada que retomar.")
        return 0
    for j in pendientes:
        print(f"  {j.id}: siguiendo")
        run_job(j, _Consola(), poll_s=5.0)
        print(f"  {j.id}: {j.state}" + (f" ({j.error})" if j.error else ""))
    return 0 if all(j.state not in ("fallido",) for j in pendientes) else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    """Comprueba que todo esta listo para calcular, sin lanzar nada."""
    from core import paths
    from core.jobs import FINALES, load_jobs
    from core.local_runner import probar_docker
    from core.remote_runner import RemoteError, _ssh, probar_servidor

    problemas = 0

    def linea(bien: bool, texto: str) -> None:
        nonlocal problemas
        problemas += not bien
        print(f"  {'bien' if bien else 'MAL '}  {texto}")

    print("Esta computadora")
    distintos = _versiones_distintas()
    linea(not distintos, "; ".join(distintos) or "Versiones de requirements.txt")
    libre = shutil.disk_usage(paths.data_root()).free / 1e9
    linea(libre >= ESPACIO_MINIMO_GB, f"{libre:.0f} GB libres en {paths.data_root()}")
    linea(bool(shutil.which("rsync") and shutil.which("ssh")), "rsync y ssh, para los servidores")
    # Sin Docker aun se puede calcular en un servidor: no es un problema.
    print(f"  ----  Local: {probar_docker()['mensaje']}")
    for host in [h for h in args.hosts.split(",") if h]:
        print(host)
        try:
            s = probar_servidor(host)
            df = _ssh(host, "df -k ~ | tail -1", timeout=25)
            libre = int(df.stdout.split()[3]) / 1e6
        except (RemoteError, OSError, subprocess.TimeoutExpired, IndexError, ValueError) as e:
            linea(False, f"No responde: {str(e)[:160]}. Prueba «Configurar acceso…» o revisa la red.")
            continue
        linea(s["rsync"] and s["python3"], "rsync y python3")
        linea(bool(s["openfoam"]), f"OpenFOAM: {s['openfoam'] or 'no se encontró'}")
        linea(libre >= ESPACIO_MINIMO_GB, f"{libre:.0f} GB libres")
        print(f"  ----  {s.get('fisicos', s['nucleos'])} núcleos ({s['nucleos']} hilos), carga {s['carga']:.1f}")
    a_medias = [j.label for j in load_jobs() if j.state not in FINALES]
    if a_medias:
        print(f"Trabajos a medias: {len(a_medias)}. Se retoman al abrir la ventana, "
              f"o con «python3 -m core.cli retomar <id> --si-terminado».")
    print("Todo listo." if not problemas else f"{problemas} problema(s).")
    return 1 if problemas else 0


def main(argv: List[str] = None) -> int:
    p = argparse.ArgumentParser(prog="core.cli", description=__doc__)
    sub = p.add_subparsers(dest="orden", required=True)

    doctor = sub.add_parser("doctor", help="comprueba que todo esta listo, sin lanzar nada")
    doctor.add_argument("--hosts", default="", help="servidores separados por comas")
    doctor.set_defaults(fn=cmd_doctor)

    correr = sub.add_parser("correr", help="un paquete en una maquina")
    correr.add_argument("--host", required=True, help="usuario@host o local")
    correr.add_argument("--procesos", type=int, default=4)
    correr.add_argument("--etiqueta", default="")
    correr.add_argument("ajustes", nargs="*", help="clave=valor sobre los valores por defecto")
    correr.set_defaults(fn=cmd_correr)

    control = sub.add_parser("control", help="caso de control con sus compuertas")
    control.add_argument("--hosts", default="", help="maquinas separadas por comas (no hace falta con --evaluar)")
    control.add_argument("--procesos", type=int, default=8)
    control.add_argument("--angulos", default="0,8")
    control.add_argument("--evaluar", default="", metavar="PREFIJO",
                         help="solo evaluar una campana ya calculada (p. ej. 20261108_174028), sin lanzar nada")
    control.add_argument("--salida", default="", help="JSON con el resultado")
    control.set_defaults(fn=cmd_control)

    banco = sub.add_parser("banco", help="banco de validacion frente a NASA TMR y Ladson")
    banco.add_argument("--maquinas", required=True, help="usuario@host:procesos:simultaneos,...")
    banco.add_argument("--salida", default="banco_validacion", help="carpeta del informe")
    banco.set_defaults(fn=cmd_banco)

    polar = sub.add_parser("polar", help="polar con incertidumbre de malla")
    polar.add_argument("--maquinas", required=True, help="usuario@host:procesos:simultaneos,...")
    polar.add_argument("--angulos", required=True, help="angulos separados por comas")
    polar.add_argument("--gci", default="", help="angulos con estudio de malla")
    polar.add_argument("--urans", action="store_true", help="repite en transitorio lo que no converja")
    polar.add_argument("--continuar", action="store_true",
                       help="aprovecha lo terminado de una campana interrumpida y retoma lo que sigue corriendo")
    polar.add_argument("--salida", default="polar", help="carpeta de resultados")
    polar.add_argument("ajustes", nargs="*", help="clave=valor sobre los valores por defecto")
    polar.set_defaults(fn=cmd_polar)

    retomar = sub.add_parser("retomar", help="termina y descarga trabajos a medias, sin recalcular")
    retomar.add_argument("trabajos", nargs="+",
                         help="id del trabajo o su comienzo (p. ej. 20261108_174028)")
    retomar.add_argument("--si-terminado", action="store_true",
                         help="solo los que su maquina ya da por terminados")
    retomar.set_defaults(fn=cmd_retomar)

    detener = sub.add_parser("detener", help="detiene trabajos en su maquina, corran o esperen en cola")
    detener.add_argument("trabajos", nargs="+", help="id del trabajo o su comienzo (p. ej. la fecha de la campana)")
    detener.set_defaults(fn=cmd_detener)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
