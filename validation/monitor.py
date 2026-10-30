#!/usr/bin/env python3
"""Monitor remoto: estado de la simulación y del servidor en una pantalla.

Pensado para consultarse por SSH desde otra máquina, con o sin la GUI.

    python3 validation/monitor.py --case /tmp/sim2
    python3 validation/monitor.py --case /tmp/sim2 --watch 30
    python3 validation/monitor.py --case /tmp/sim2 --json     # para la GUI

El modo --json devuelve una sola línea con todo lo necesario para que la GUI
dibuje el panel sin tener que parsear texto.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time


PUNTOS_SERIE = 400   # puntos de la historia de Cl/Cd que se envian a la GUI
LOG_ACTIVO_S = 120   # sin escribir en run.log este tiempo, el caso no corre


def _read(path, limit=None):
    try:
        with open(path, errors="replace") as f:
            if limit:
                f.seek(max(0, os.path.getsize(path) - limit))
            return f.read()
    except OSError:
        return ""


# ---------------------------------------------------------------- simulación
def log_stats(case):
    log = os.path.join(case, "run.log")
    if not os.path.exists(log):
        return {}
    cola = _read(log, limit=500_000)

    tiempos = re.findall(r"^Time = ([-+0-9.eE]+)s?", cola, re.M)
    t_now = float(tiempos[-1]) if tiempos else None

    res = {}
    for m in re.finditer(
            r"Solving for (Ux|Uy|Uz|p|k|omega|epsilon|nuTilda),\s*"
            r"Initial residual = ([-+0-9.eE]+)", cola):
        res[m.group(1)] = float(m.group(2))

    cont = re.findall(r"continuity errors : sum local = ([-+0-9.eE]+)", cola)
    dt = re.findall(r"^deltaT = ([-+0-9.eE]+)", cola, re.M)
    n_iter = cola.count("Time = ")

    div = any(abs(v) > 1e3 for v in res.values()) or (
        cont and abs(float(cont[-1])) > 1e3)

    return {
        "t": t_now,
        "res": res,
        "continuidad": float(cont[-1]) if cont else None,
        "dt": float(dt[-1]) if dt else None,
        "pasos": n_iter,
        "divergido": bool(div),
    }


def case_stats(case):
    """Tiempos escritos, contando también los directorios de processor*."""
    tiempos = set()
    for base in [case] + glob.glob(os.path.join(case, "processor*")):
        try:
            for n in os.listdir(base):
                try:
                    float(n)
                except ValueError:
                    continue
                if os.path.exists(os.path.join(base, n, "U")):
                    tiempos.add(float(n))
        except OSError:
            pass

    end = None
    cd = os.path.join(case, "system", "controlDict")
    if os.path.exists(cd):
        m = re.search(r"^endTime\s+([0-9.eE+-]+);", _read(cd), re.M)
        if m:
            end = float(m.group(1))

    return {"tiempos": sorted(tiempos), "endTime": end}


def coeffs(case):
    files = glob.glob(os.path.join(case, "postProcessing", "forceCoeffs", "*",
                                   "*.dat"))
    if not files:
        return None
    mejor = max(files, key=os.path.getmtime)
    texto = _read(mejor).splitlines()
    # El orden de columnas cambia entre versiones de OpenFOAM (en la 12:
    # Time Cm Cd Cl Cl(f) Cl(r)), asi que se toma de la cabecera del archivo.
    nombres = []
    for l in texto:
        if l.startswith("#") and l[1:].split()[:1] == ["Time"]:
            nombres = l[1:].split()
    if "Cd" not in nombres or "Cl" not in nombres:
        return None
    i_cd, i_cl = nombres.index("Cd"), nombres.index("Cl")

    filas = []
    for l in texto:
        if l.strip() and not l.lstrip().startswith("#"):
            v = l.split()
            try:
                filas.append((float(v[0]), float(v[i_cd]), float(v[i_cl])))
            except (IndexError, ValueError):
                pass
    if not filas:
        return None
    paso = max(1, len(filas) // PUNTOS_SERIE)
    serie = filas[-1::-paso][::-1]
    t, cd, cl = filas[-1]
    return {"t": t, "Cd": cd, "Cl": cl, "n": len(filas), "serie": serie}


def log_reciente(case):
    """solver_vivo cuenta cualquier solver del servidor; esto mira ESTE caso."""
    try:
        return time.time() - os.path.getmtime(
            os.path.join(case, "run.log")) < LOG_ACTIVO_S
    except OSError:
        return False


def solver_vivo():
    try:
        out = subprocess.run(["pgrep", "-c", "-f", "foamRun|simpleFoam|pimpleFoam"],
                             capture_output=True, text=True, timeout=5).stdout
        return int(out.strip() or 0)
    except Exception:
        return 0


# ------------------------------------------------------------------ servidor
def server_stats():
    """CPU, RAM y carga del servidor."""
    d = {}
    try:
        # /proc/stat da los contadores acumulados; dos lecturas separadas
        # dan el uso real del intervalo.
        def leer_cpu():
            with open("/proc/stat") as f:
                v = [int(x) for x in f.readline().split()[1:]]
            idle = v[3] + (v[4] if len(v) > 4 else 0)
            return sum(v), idle

        t0, i0 = leer_cpu()
        time.sleep(0.35)
        t1, i1 = leer_cpu()
        dt, di = t1 - t0, i1 - i0
        d["cpu_pct"] = round(100.0 * (1 - di / dt), 1) if dt else None
    except Exception:
        d["cpu_pct"] = None

    try:
        with open("/proc/meminfo") as f:
            m = {l.split(":")[0]: int(l.split()[1]) for l in f if ":" in l}
        total = m["MemTotal"] / 1024 / 1024
        disp = m["MemAvailable"] / 1024 / 1024
        d["ram_total_gb"] = round(total, 1)
        d["ram_usada_gb"] = round(total - disp, 1)
        d["ram_pct"] = round(100 * (total - disp) / total, 1)
    except Exception:
        d["ram_pct"] = None

    try:
        d["carga"] = [round(x, 2) for x in os.getloadavg()]
        d["cores"] = os.cpu_count()
    except Exception:
        pass

    try:
        st = os.statvfs("/")
        libre = st.f_bavail * st.f_frsize / 2**30
        total = st.f_blocks * st.f_frsize / 2**30
        d["disco_libre_gb"] = round(libre, 0)
        d["disco_pct"] = round(100 * (total - libre) / total, 1)
    except Exception:
        pass

    return d


# ------------------------------------------------------------------ salida
def recoger(case):
    ls = log_stats(case)
    cs = case_stats(case)
    cf = coeffs(case)
    sv = server_stats()

    t = ls.get("t")
    if t is None and cs["tiempos"]:
        t = cs["tiempos"][-1]

    end = cs["endTime"]
    pct = (100.0 * t / end) if (t is not None and end) else None

    n_proc = solver_vivo()
    if ls.get("divergido"):
        estado = "DIVERGIDO"
    elif n_proc > 0 and log_reciente(case):
        estado = "EN_CURSO"
    elif end and t is not None and t >= end - 1e-9:
        estado = "COMPLETADA"
    else:
        estado = "PARADA"

    return {
        "estado": estado,
        "caso": os.path.basename(os.path.abspath(case)),
        "t": t,
        "endTime": end,
        "pct": pct,
        "residuales": ls.get("res", {}),
        "continuidad": ls.get("continuidad"),
        "dt": ls.get("dt"),
        "pasos": cf["n"] if cf else ls.get("pasos", 0),
        "tiempos_escritos": len(cs["tiempos"]),
        "coeffs": cf,
        "procesos": n_proc,
        "servidor": sv,
    }


def render_texto(d):
    L = []
    estado = {"COMPLETADA": "✔ COMPLETADA", "EN_CURSO": "⏳ EN CURSO",
              "DIVERGIDO": "💥 DIVERGIDO"}.get(d["estado"], "⏸ PARADA")
    L.append(f"{estado}   {d['caso']}   ({d['procesos']} procesos)")

    if d["t"] is not None and d["endTime"]:
        pct = d["pct"] or 0
        n = 28
        barra = "█" * int(n * min(pct, 100) / 100) + "░" * (n - int(n * min(pct, 100) / 100))
        L.append(f"  t = {d['t']:9.5f} / {d['endTime']:g} s  [{barra}] {pct:5.1f}%")
    elif d["t"] is not None:
        L.append(f"  t = {d['t']:.5f} s")

    L.append(f"  pasos: {d['pasos']:,}   tiempos escritos: {d['tiempos_escritos']}")

    if d["residuales"]:
        partes = [f"{k}={v:.1e}" for k, v in d["residuales"].items()]
        L.append("  residuales: " + "  ".join(partes))
    if d["continuidad"] is not None:
        L.append(f"  continuidad: {d['continuidad']:.2e}"
                 + (f"   dt = {d['dt']:.2e}" if d["dt"] else ""))

    if d["coeffs"]:
        c = d["coeffs"]
        L.append(f"  Cl = {c['Cl']:+.5f}   Cd = {c['Cd']:.5f}   (t={c['t']:g})")

    s = d["servidor"]
    L.append("")
    L.append("  ── SERVIDOR ──")
    if s.get("cpu_pct") is not None:
        L.append(f"  CPU: {s['cpu_pct']:5.1f}%   carga: {s.get('carga', ['?'])[0]}"
                 f"   cores: {s.get('cores', '?')}")
    if s.get("ram_pct") is not None:
        L.append(f"  RAM: {s['ram_pct']:5.1f}%   "
                 f"({s['ram_usada_gb']}/{s['ram_total_gb']} GB)")
    if s.get("disco_pct") is not None:
        L.append(f"  Disco: {s['disco_pct']:.0f}% usado, {s['disco_libre_gb']:.0f} GB libre")

    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="openfoam_case")
    ap.add_argument("--watch", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    case = os.path.expanduser(args.case)
    if not os.path.isdir(case):
        print(f"No existe el caso: {case}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(recoger(case)))
        return 0

    if not args.watch:
        print(render_texto(recoger(case)))
        return 0

    try:
        while True:
            os.system("clear")
            print(time.strftime("%Y-%m-%d %H:%M:%S"))
            print(render_texto(recoger(case)))
            print(f"\n(refrescando cada {args.watch}s · Ctrl+C para salir)")
            time.sleep(args.watch)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
