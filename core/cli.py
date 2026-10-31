"""OpenBlade sin ventana: las mismas funciones que usa la interfaz.

    python3 -m core.cli correr --host usuario@host --procesos 8 aoa=8 reynolds=6e6
    python3 -m core.cli control --hosts usuario@a,usuario@b --procesos 8

Cada simulacion sale de aqui o de la ventana; no hay otra forma de escribir un caso.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, List

from core.defaults import case_params
from core.jobs import Dispatcher, Events, Job, Machine, new_job


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


def cmd_control(args: argparse.Namespace) -> int:
    from core.control import run_control

    angulos = tuple(float(a) for a in args.angulos.split(","))
    r = run_control(args.hosts.split(","), args.procesos, angulos, _Consola())
    falla = False
    for angulo, filas in r["por_angulo"].items():
        print(f"\nα = {angulo:g}")
        for f in filas:
            falla |= not f["ok"]
            print(f"  {f['n']}  {'pasa ' if f['ok'] else 'FALLA'}  {f['compuerta']}: {f['detalle']}")
    if args.salida:
        with open(args.salida, "w") as f:
            json.dump(r, f, indent=1, ensure_ascii=False)
    return 1 if falla else 0


def main(argv: List[str] = None) -> int:
    p = argparse.ArgumentParser(prog="core.cli", description=__doc__)
    sub = p.add_subparsers(dest="orden", required=True)

    correr = sub.add_parser("correr", help="un paquete en una maquina")
    correr.add_argument("--host", required=True, help="usuario@host o local")
    correr.add_argument("--procesos", type=int, default=4)
    correr.add_argument("--etiqueta", default="")
    correr.add_argument("ajustes", nargs="*", help="clave=valor sobre los valores por defecto")
    correr.set_defaults(fn=cmd_correr)

    control = sub.add_parser("control", help="caso de control con sus compuertas")
    control.add_argument("--hosts", required=True, help="maquinas separadas por comas")
    control.add_argument("--procesos", type=int, default=8)
    control.add_argument("--angulos", default="0,8")
    control.add_argument("--salida", default="", help="JSON con el resultado")
    control.set_defaults(fn=cmd_control)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
