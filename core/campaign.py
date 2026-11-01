"""Campana en paquetes: polar con incertidumbre de malla y URANS donde RANS no converge.

Cada punto es un paquete normal, con su carpeta, ficha y veredicto. La incertidumbre
sale de un GCI con tres niveles anidados en los angulos que se indiquen; entre esos
angulos se interpola la banda relativa. Un punto que no converge no se presenta como
resultado: se indica, y si se pide se repite en transitorio.
"""

from __future__ import annotations

import csv
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np

from core.defaults import DEFAULT_PARAMS, case_params
from core.gci import study_from_levels
from core.jobs import (DESCARGANDO, DETENIDO, Dispatcher, Events, FALLIDO, FINALES, Job, Machine, load_jobs,
                       mesh_key, new_job)

NIVELES_GCI = (1, 2, 3)
NIVEL_BASE = 2
# El nivel mas grueso puede oscilar poco con media estable: lo que entra en el calculo es su
# media, y esa debe moverse mucho menos que lo que separa las mallas. Los niveles finos no:
# su resultado es el que se usa, y la banda no dice nada de una oscilacion.
OSCILACION_MAX = 0.03   # amplitud frente a la media
DERIVA_MAX = 0.1        # cambio de la media entre tramos frente al salto entre mallas
CL_MINIMO = 0.1         # con Cl casi nulo la amplitud relativa no sirve
CM_AMP_MAX = 0.005      # Cm es casi nulo: su amplitud se mide en absoluto
PARAM_TRANSITORIO = {"regime": "Transitorio (pimpleFoam)"}


def _oscilacion_pequena(v: Dict[str, Any]) -> bool:
    """Oscila, pero poco frente a su media: esa media dice algo."""
    return (bool(v.get("oscila")) and v.get("cl") is not None and v.get("cd") is not None
            and (v.get("cl_amp") or 0.0) <= OSCILACION_MAX * max(abs(v["cl"]), CL_MINIMO)
            and (v.get("cd_amp") or 0.0) <= OSCILACION_MAX * abs(v["cd"]))


def verdict_of(job: Job) -> Dict[str, Any]:
    return (job.analysis or {}).get("verdict") or {}


def usable(job: Job) -> bool:
    return verdict_of(job).get("state") == "CONVERGIDO" and verdict_of(job).get("cl") is not None


def grid_study_cases(params: Dict[str, Any], niveles: Sequence[int] = NIVELES_GCI) -> List[Dict[str, Any]]:
    """Los paquetes de un estudio de malla, del nivel mas grueso al mas fino.

    Cada nivel fino pide del orden del doble de iteraciones que el anterior: el tope se
    escala para que el mas fino no se quede a medias.
    """
    tope = int(params.get("max_iters", DEFAULT_PARAMS["max_iters"]))
    return [dict(params, mesher="cgrid", grid_level=int(n), max_iters=int(tope * 2.0 ** (int(n) - NIVEL_BASE)))
            for n in sorted(niveles)]


def _oscila_poco(filas: Sequence[Dict[str, Any]]) -> bool:
    """¿El nivel mas grueso oscila poco y su media se mueve mucho menos que el salto al siguiente?"""
    f, siguiente = filas[0], filas[1]
    if (f["cm_amp"] or 0.0) > CM_AMP_MAX:
        return False
    for nombre, deriva, escala in (("cl", f["cl_deriva"], max(abs(f["cl"] or 0.0), CL_MINIMO)),
                                   ("cd", f["cd_deriva"], abs(f["cd"] or 0.0))):
        if f[nombre] is None or siguiente[nombre] is None or deriva is None:
            return False
        if f[f"{nombre}_amp"] > OSCILACION_MAX * escala:
            return False
        if deriva > DERIVA_MAX * abs(f[nombre] - siguiente[nombre]):
            return False
    return True


def grid_study_result(trabajos: Sequence[Job]) -> Dict[str, Any]:
    """GCI de Cl, Cd y Cm a partir de los tres trabajos, del mas grueso al mas fino."""
    orden = sorted(trabajos, key=lambda j: int(j.params.get("grid_level", 2)))
    filas = [{"nivel": int(j.params.get("grid_level", 2)), "veredicto": verdict_of(j).get("state"),
              "cl": verdict_of(j).get("cl"), "cl_amp": verdict_of(j).get("cl_amp"),
              "cd": verdict_of(j).get("cd"), "cd_amp": verdict_of(j).get("cd_amp"),
              "cm": verdict_of(j).get("cm"), "cm_amp": verdict_of(j).get("cm_amp"),
              "oscila": bool(verdict_of(j).get("oscila")), "cl_deriva": verdict_of(j).get("cl_drift"),
              "cd_deriva": 0.01 * (verdict_of(j).get("cd_drift_pct") or 0.0) * abs(verdict_of(j).get("cd") or 0.0)
              if verdict_of(j).get("cd_drift_pct") is not None else None,
              "yplus": ((j.analysis or {}).get("yplus") or {}).get("mean"),
              "trabajo": j.id} for j in orden]
    sin_converger = [f["nivel"] for f in filas if f["veredicto"] != "CONVERGIDO"]
    oscilan = [filas[0]["nivel"]] if filas[0]["oscila"] and _oscila_poco(filas) else []
    malos = [n for n in sin_converger if n not in oscilan]
    resultado: Dict[str, Any] = {"aoa": float(orden[0].params.get("aoa", 0.0)), "niveles": filas,
                                 "sin_converger": sin_converger, "oscilan": oscilan}
    if malos:
        resultado["motivo"] = f"Sin GCI: los niveles {malos} no convergieron"
        return resultado
    for nombre in ("cl", "cd", "cm"):
        resultado[nombre] = study_from_levels([f[nombre] for f in filas]).to_dict()
    return resultado


def grid_study_text(r: Dict[str, Any]) -> str:
    """Resumen de un estudio de malla para el usuario."""
    if "motivo" in r:
        return r["motivo"]
    partes = []
    for nombre in ("cl", "cd"):
        g = r[nombre]
        orden = f"orden {g['orden']:.2f}" if g["orden"] is not None else g["convergencia"]
        ext = f", extrapolado {g['extrapolado']:.5f}" if g["extrapolado"] is not None else ""
        partes.append(f"{nombre.capitalize()} = {g['fina']:.5f} ± {g['banda']:.5f} "
                      f"(GCI {100 * g['gci_fina']:.2f} %, {orden}{ext})")
    if r.get("oscilan"):
        partes.append(f"El nivel {r['oscilan'][0]} oscila poco con media estable: se usa su media.")
    return "   ".join(partes)


def _bandas(estudios: Sequence[Dict[str, Any]], nombre: str, aoa: float, clave: str) -> Optional[float]:
    """Banda relativa interpolada entre los angulos con GCI; fuera de ellos no se sabe."""
    puntos = sorted((e["aoa"], e[nombre][clave]) for e in estudios if nombre in e)
    if not puntos or not puntos[0][0] <= aoa <= puntos[-1][0]:
        return None
    return float(np.interp(aoa, [p[0] for p in puntos], [p[1] for p in puntos]))


def polar_table(puntos: Sequence[Job], estudios: Sequence[Dict[str, Any]] = (),
                nivel_gci: str = "gci_media") -> List[Dict[str, Any]]:
    """Una fila por angulo, con el veredicto y la banda de malla de cada coeficiente.

    La polar se calcula en la malla media, asi que por defecto lleva la banda de la media.
    Un punto que oscila poco con media estable da su media, marcada: sigue sin convergir,
    pero cerca de la perdida es lo que hay. Lo que no convergio de otro modo no da numeros.
    """
    filas = []
    for j in sorted(puntos, key=lambda x: float(x.params.get("aoa", 0.0))):
        v = verdict_of(j)
        a = float(j.params.get("aoa", 0.0))
        fila = {"aoa": a, "veredicto": v.get("state"), "razon": v.get("reason"), "transitorio": j.transient,
                "cl": None, "cl_amp": None, "cd": None, "cd_amp": None, "cm": None,
                "banda_cl": None, "banda_cd": None, "periodo": v.get("period"), "trabajo": j.id,
                "oscila": _oscilacion_pequena(v),
                "maquina": j.host, "yplus": ((j.analysis or {}).get("yplus") or {}).get("mean")}
        if usable(j) or fila["oscila"]:
            fila.update(cl=v["cl"], cl_amp=v["cl_amp"], cd=v["cd"], cd_amp=v["cd_amp"], cm=v["cm"])
        if usable(j):
            rel_cl, rel_cd = _bandas(estudios, "cl", a, nivel_gci), _bandas(estudios, "cd", a, nivel_gci)
            if rel_cl is not None:
                fila["banda_cl"] = rel_cl * abs(v["cl"])
            if rel_cd is not None:
                fila["banda_cd"] = rel_cd * abs(v["cd"])
        filas.append(fila)
    return filas


def write_polar_csv(filas: Iterable[Dict[str, Any]], ruta: str) -> None:
    columnas = ["aoa", "veredicto", "oscila", "transitorio", "cl", "banda_cl", "cl_amp", "cd", "banda_cd", "cd_amp", "cm",
                "yplus", "maquina", "trabajo", "razon"]
    with open(ruta, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            w.writerow(fila)


def _neighbor(trabajos: Sequence[Job], j: Job) -> Optional[Job]:
    """El trabajo convergido de angulo mas cercano en la misma malla."""
    malla = mesh_key(j.params)
    candidatos = [k for k in trabajos if k is not j and usable(k) and mesh_key(k.params) == malla]
    return min(candidatos, key=lambda k: abs(float(k.params["aoa"]) - float(j.params["aoa"])), default=None)


def run_polar(machines: List[Machine], base: Dict[str, Any], angulos: Sequence[float],
              angulos_gci: Sequence[float], events: Optional[Events] = None,
              urans_si_no_converge: bool = False, urans: Optional[Dict[str, Any]] = None,
              continuar: bool = False) -> Dict[str, Any]:
    """Lanza la polar y los estudios de malla, y repite en transitorio lo que no converja.

    Con continuar, aprovecha los trabajos de una campana interrumpida que tengan la misma
    etiqueta y los mismos parametros: los terminados no se repiten y los que siguen en su
    maquina se retoman. La campana vive en la Mac: si esta se apaga, lo que corre sigue en
    los servidores, pero lo pendiente no se envia hasta que se relance.
    """
    d = Dispatcher(events, poll_s=8.0)
    d.set_machines(machines)
    params = case_params(**base)
    previos = load_jobs() if continuar else []

    def trabajo(q: Dict[str, Any], etiqueta: str) -> Job:
        for j in reversed(previos):
            if j.label != etiqueta or j.params != q:
                continue
            # El calculo termino bien y solo fallo traerlo: no hay que repetirlo.
            if j.state == FALLIDO and j.remote_dir and j.rc == 0 and not j.analysis:
                j.state, j.error, j.finished = DESCARGANDO, "", None
                return j
            # Reventado al arrancar: repetirlo igual reventaria otra vez; se rescata abajo.
            if j.state not in (FALLIDO, DETENIDO) or verdict_of(j).get("state") == "DIVERGIDO":
                return j
        return new_job(q, label=etiqueta)

    def enviar(trabajos: Iterable[Job]) -> None:
        # Lo que sigue en su maquina ocupa su sitio antes de repartir lo demas.
        for j in trabajos:
            if j.remote_dir and j.state not in FINALES:
                d.attach(j)
        # Primero lo rapido: la polar queda lista aunque las mallas finas tarden horas.
        for j in sorted(trabajos, key=lambda j: int(j.params.get("grid_level", 2))):
            if not j.remote_dir and j.state not in FINALES:
                d.submit(j)

    puntos = {}
    estudios_trabajos: Dict[float, List[Job]] = {}
    pendientes: List[Job] = []
    for a in angulos_gci:
        grupo = [trabajo(q, f"gci_a{a:g}_n{q['grid_level']}")
                 for q in grid_study_cases(dict(params, aoa=float(a)))]
        pendientes += grupo
        estudios_trabajos[float(a)] = grupo
    nivel_polar = int(params.get("grid_level", 2))
    for a in angulos:
        ya = next((j for j in estudios_trabajos.get(float(a), [])
                   if int(j.params["grid_level"]) == nivel_polar), None)
        if ya is not None:
            puntos[float(a)] = ya
            continue
        j = trabajo(dict(params, aoa=float(a)), f"polar_a{a:g}")
        puntos[float(a)] = j
        pendientes.append(j)
    enviar(pendientes)
    d.wait()

    # Un punto que revienta al arrancar suele salir desde el angulo vecino: la malla es la
    # misma. Medido a 15 grados en el nivel 2: el resultado no cambia (Cd 0.019875 y 0.019893)
    # y Cd llega a 0.5 % de su valor en 2100 iteraciones en lugar de 16 700.
    rescates: Dict[str, Job] = {}
    for j in pendientes:
        vecino = _neighbor(pendientes, j) if verdict_of(j).get("state") == "DIVERGIDO" else None
        if vecino is not None:
            rescates[j.id] = trabajo(dict(j.params, campo_inicial=vecino.case_dir), f"{j.label}_vecino")
    enviar(list(rescates.values()))
    d.wait()
    puntos = {a: rescates.get(j.id, j) for a, j in puntos.items()}
    estudios_trabajos = {a: [rescates.get(j.id, j) for j in g] for a, g in estudios_trabajos.items()}

    transitorios = {}
    if urans_si_no_converge:
        for a, j in puntos.items():
            if not usable(j):
                q = dict(params, aoa=a, **PARAM_TRANSITORIO, **(urans or {}))
                t = new_job(q, label=f"urans_a{a:g}")
                transitorios[a] = t
                d.submit(t)
        d.wait()
    finales = [transitorios.get(a, j) for a, j in puntos.items()]
    estudios = [grid_study_result(g) for g in estudios_trabajos.values()]
    return {"base": base, "filas": polar_table(finales, estudios), "estudios": estudios,
            "rans_sin_converger": sorted(transitorios)}


def write_polar_report(resultado: Dict[str, Any], carpeta: str) -> str:
    """polar.json, polar.csv y una figura de Cl y Cd con su banda de malla."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from core.bench import ladson

    os.makedirs(carpeta, exist_ok=True)
    with open(os.path.join(carpeta, "polar.json"), "w") as f:
        json.dump(resultado, f, indent=1, ensure_ascii=False)
    write_polar_csv(resultado["filas"], os.path.join(carpeta, "polar.csv"))

    filas = [f for f in resultado["filas"] if f["cl"] is not None]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.5), constrained_layout=True)
    if filas:
        alfa = [f["aoa"] for f in filas]
        a1.errorbar(alfa, [f["cl"] for f in filas], yerr=[f["banda_cl"] or 0 for f in filas], fmt="o-", capsize=3,
                    label="OpenBlade (SST)")
        a2.errorbar([f["cd"] for f in filas], [f["cl"] for f in filas], xerr=[f["banda_cd"] or 0 for f in filas],
                    yerr=[f["banda_cl"] or 0 for f in filas], fmt="o-", capsize=3, label="OpenBlade (SST)")
        # Hueco: oscila con media estable, no ha convergido.
        huecos = [f for f in filas if f.get("oscila")]
        a1.plot([f["aoa"] for f in huecos], [f["cl"] for f in huecos], "o", mfc="white", mec="tab:blue", zorder=5)
        a2.plot([f["cd"] for f in huecos], [f["cl"] for f in huecos], "o", mfc="white", mec="tab:blue", zorder=5)
    base = resultado.get("base", {})
    if str(base.get("naca", "0012")) == "0012" and abs(float(base.get("reynolds", 0)) - 6e6) < 1:
        ref = np.array([ladson(a) for a in np.arange(0.0, 17.1, 1.0)])
        a1.plot(np.arange(0.0, 17.1, 1.0), ref[:, 0], "k--", label="Ladson 80 grit")
        a2.plot(ref[:, 1], ref[:, 0], "k--", label="Ladson 80 grit")
    a1.set_xlabel("α [°]"), a1.set_ylabel("Cl"), a1.grid(alpha=0.3), a1.legend()
    a2.set_xlabel("Cd"), a2.set_ylabel("Cl"), a2.grid(alpha=0.3), a2.legend()
    ruta = os.path.join(carpeta, "polar.png")
    fig.savefig(ruta, dpi=140)
    plt.close(fig)
    return ruta
