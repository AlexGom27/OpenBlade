"""Caso de control de cada entrega: el mismo paquete en dos maquinas y ocho compuertas.

NACA 0012, cuerda 1, Re=6e6, valores por defecto de la ventana.
Las tolerancias detectan errores gruesos; no certifican precision.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Tuple

from core.defaults import case_params
from core.forces import read_forces
from core.jobs import Dispatcher, Events, Job, Machine, ensure_mesh, new_job
from core.package import read_ficha, sha256_file

LADSON = {0.0: (0.0, 0.00806), 8.0: (0.8593, 0.00979)}
TOL_CD_A0 = 0.05
TOL_A8 = 0.10
TOL_RANGO = 1.0         # %
TOL_YPLUS = 0.01


def _md5(ruta: str) -> str:
    h = hashlib.md5()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def run_control(hosts: List[str], nproc: int = 8, angulos: Tuple[float, ...] = (0.0, 8.0),
                events: Events = None) -> Dict[str, Any]:
    """Lanza cada angulo en cada maquina y evalua las compuertas."""
    d = Dispatcher(events, poll_s=5.0)
    d.set_machines([Machine(h, nproc, 2) for h in hosts])
    trabajos: Dict[Tuple[float, str], Job] = {}
    for angulo in angulos:
        for host in hosts:
            j = new_job(case_params(aoa=angulo, reynolds=6e6), host, nproc,
                        label=f"control_a{angulo:g}_{host.split('@')[-1]}")
            trabajos[(angulo, host)] = j
            d.submit(j)
    d.wait()
    return {"por_angulo": {a: evaluate_gates(a, [trabajos[(a, h)] for h in hosts]) for a in angulos},
            "trabajos": {f"{a:g}@{h}": j.id for (a, h), j in trabajos.items()}}


def evaluate_gates(angulo: float, trabajos: List[Job]) -> List[Dict[str, Any]]:
    """Las compuertas de un angulo, a partir de lo que dejaron sus trabajos."""
    filas: List[Dict[str, Any]] = []

    def compuerta(n: int, nombre: str, ok: bool, detalle: str) -> None:
        filas.append({"n": n, "compuerta": nombre, "ok": bool(ok), "detalle": detalle})

    # 1. misma malla en todas las maquinas
    huellas = {(read_ficha(j.case_dir) or {}).get("archivos", {}).get("mesh.msh") for j in trabajos}
    compuerta(1, "misma malla", len(huellas) == 1 and None not in huellas,
              f"sha256 {sorted(str(h)[:12] for h in huellas)}")

    # 2. mismas fuerzas fila por fila
    historias, fuentes = [], []
    for j in trabajos:
        try:
            h = read_forces(j.case_dir)
            historias.append(h)
            fuentes.append(_md5(h.sources[-1]))
        except ValueError as e:
            compuerta(3, f"Cl y Cd por nombre en {j.host}", False, str(e))
    compuerta(2, "mismas fuerzas entre máquinas", len(set(fuentes)) == 1 and len(fuentes) == len(trabajos),
              f"md5 {sorted(f[:12] for f in set(fuentes))}")

    # 3. columnas por nombre
    if len(historias) == len(trabajos):
        compuerta(3, "Cl y Cd leídos por nombre", all(len(h) > 0 for h in historias),
                  f"{[len(h) for h in historias]} filas")
    if not historias:
        return filas

    for j, h in zip(trabajos, historias):
        v = (j.analysis or {}).get("verdict") or {}
        destino = j.host.split("@")[-1]
        # 4. rango de Cd en las ultimas 500 iteraciones
        cola = h.cd[-500:]
        media = sum(cola) / len(cola)
        rango = 100.0 * (max(cola) - min(cola)) / abs(media) if media else float("inf")
        compuerta(4, f"rango de Cd ({destino})", rango < TOL_RANGO, f"{rango:.2f} %")
        # 5. sin divergencia
        pico = max(abs(x) for x in h.cl)
        negativos = sum(1 for x in cola if x < 0)
        compuerta(5, f"sin divergencia ({destino})", pico <= 2.0 and not negativos,
                  f"|Cl| máx {pico:.3f}, Cd<0 en {negativos} filas")
        ref_cl, ref_cd = LADSON[angulo]
        m_cl, m_cd = v.get("cl"), v.get("cd")
        if m_cd is None:
            compuerta(6, f"fuerzas frente a Ladson ({destino})", False, f"veredicto {v.get('state')}")
            continue
        # 6. frente a Ladson
        if angulo == 0.0:
            err = (m_cd - ref_cd) / ref_cd
            compuerta(6, f"Cd frente a Ladson ({destino})", abs(err) <= TOL_CD_A0,
                      f"{m_cd:.5f} ({100 * err:+.1f} %)")
            # 7. simetria
            compuerta(7, f"|Cl| a α=0 ({destino})", abs(m_cl) < 0.01, f"{m_cl:+.5f}")
        else:
            err_cl = (m_cl - ref_cl) / ref_cl
            err_cd = (m_cd - ref_cd) / ref_cd
            compuerta(6, f"Cl y Cd frente a Ladson ({destino})",
                      abs(err_cl) <= TOL_A8 and abs(err_cd) <= TOL_A8,
                      f"Cl {m_cl:.4f} ({100 * err_cl:+.1f} %), Cd {m_cd:.5f} ({100 * err_cd:+.1f} %)")

    # 8. y+ del programa igual entre maquinas
    medios = [((j.analysis or {}).get("yplus") or {}).get("mean") for j in trabajos]
    if all(m is not None for m in medios):
        dif = (max(medios) - min(medios)) / max(abs(m) for m in medios)
        compuerta(8, "y+ igual entre máquinas", dif <= TOL_YPLUS, f"{[round(m, 3) for m in medios]}")
    else:
        compuerta(8, "y+ igual entre máquinas", False, f"sin y+ en {medios}")
    return sorted(filas, key=lambda f: f["n"])
