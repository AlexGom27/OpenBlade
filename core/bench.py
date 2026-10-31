"""Banco de validacion: NACA 0012 a Re = 6e6 frente a NASA TMR y Ladson.

Corre por el mismo camino que cualquier caso y compara fuerzas y distribuciones con
los datos publicados. Las tolerancias estan aqui, a la vista: un caso las cumple o
no, y el informe lo dice. Cumplirlas no certifica precision: el error real de un
coeficiente es el del estudio de malla, en el informe de la campana.

Referencias (validation/refs/):
  - NASA TMR, 2D NACA 0012 Airfoil Validation: CFL3D, FUN3D y NTS con SST y malla
    897 x 257; CFL3D y otros con Spalart-Allmaras.
  - Ladson, NASA TM 4074 (1988), Re = 6e6, transicion fijada con grano 80.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from core.defaults import case_params
from core.jobs import Dispatcher, Events, Job, Machine, new_job

REFS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "validation", "refs")
SST = "k-Omega SST (RAS)"
SA = "Spalart-Allmaras (RAS)"

# Publicados en la pagina de TMR, malla 897 x 257.
TMR = {
    SST: {0.0: {"CFL3D": (0.0, 0.00809), "FUN3D": (0.0, 0.00808), "NTS": (0.0, 0.00809)},
          10.0: {"CFL3D": (1.0778, 0.01236), "FUN3D": (1.0840, 0.01253), "NTS": (1.0765, 0.01251)},
          15.0: {"CFL3D": (1.5068, 0.02219), "FUN3D": (1.5109, 0.02275), "NTS": (1.5100, 0.02187)}},
    SA: {0.0: {"CFL3D": (0.0, 0.00819), "FUN3D": (0.0, 0.00812), "NTS": (0.0, 0.00813)},
         10.0: {"CFL3D": (1.0909, 0.01231), "FUN3D": (1.0983, 0.01242), "NTS": (1.0891, 0.01243)},
         15.0: {"CFL3D": (1.5461, 0.02124), "FUN3D": (1.5547, 0.02159), "NTS": (1.5461, 0.02105)}},
}
# Tolerancias frente a la media de TMR y frente a Ladson: |dCl| relativo o absoluto, |dCd| relativo.
TOL_TMR = {0.0: (0.01, 0.05), 10.0: (0.02, 0.05), 15.0: (0.03, 0.10)}
TOL_LADSON = {0.0: (0.02, 0.05), 10.0: (0.03, 0.10), 15.0: (0.05, 0.20)}
TOL_CP_RMS = 0.10
TOL_CF_RMS = 1.5e-3
TOL_DOMINIO = (0.01, 0.02)      # cambio de Cl y Cd entre los dos dominios de la prueba


@dataclass
class BenchCase:
    etiqueta: str
    aoa: float
    turbulencia: str = SST
    nivel: int = 2
    radio: float = 500.0
    ajustes: Dict[str, Any] = field(default_factory=dict)


def default_cases() -> List[BenchCase]:
    casos = [BenchCase(f"banco_sst_a{a:g}", a) for a in (0.0, 10.0, 15.0)]
    casos += [BenchCase(f"banco_sa_a{a:g}", a, SA) for a in (0.0, 10.0, 15.0)]
    casos += [BenchCase("banco_dominio_R40_a10", 10.0, radio=40.0),
              BenchCase("banco_dominio_R200_a10", 10.0, radio=200.0)]
    return casos


def case_parameters(c: BenchCase) -> Dict[str, Any]:
    return case_params(reynolds=6e6, aoa=c.aoa, turbulence=c.turbulencia, grid_level=c.nivel,
                       farfield=c.radio, max_iters=40000, **c.ajustes)


def _zona(ruta: str, nombre: str) -> np.ndarray:
    filas, dentro = [], False
    with open(ruta) as f:
        for linea in f:
            if linea.startswith("zone"):
                dentro = nombre in linea
            elif dentro and linea.strip() and not linea.startswith(("#", "variables")):
                filas.append([float(v) for v in linea.split()])
    return np.array(filas)


def ladson(aoa: float, zona: str = "80 grit") -> Tuple[float, float]:
    """Cl y Cd de Ladson interpolados al angulo, en el tramo sin perdida."""
    d = _zona(os.path.join(REFS, "ladson_clcd.dat"), zona)
    d = d[d[:, 0] < 17.5]
    return float(np.interp(aoa, d[:, 0], d[:, 1])), float(np.interp(aoa, d[:, 0], d[:, 2]))


def _tmr_media(turbulencia: str, aoa: float) -> Tuple[float, float]:
    valores = list(TMR[turbulencia][aoa].values())
    return float(np.mean([v[0] for v in valores])), float(np.mean([v[1] for v in valores]))


def _error_cl(valor: float, ref: float) -> float:
    """Relativo; con Cl de referencia casi nulo, absoluto."""
    return valor - ref if abs(ref) < 0.05 else (valor - ref) / ref


def surface_comparison(case_dir: str, turbulencia: str, aoa: float, u_inf: float = 15.0) -> Dict[str, float]:
    """RMS de Cp y Cf frente a CFL3D, sin el tramo final junto al borde de salida."""
    from core.surface import read_surface

    modelo = "sst" if turbulencia == SST else "sa"
    s = read_surface(case_dir, u_inf)
    cp = _zona(os.path.join(REFS, f"tmr_n0012cp_cfl3d_{modelo}.dat"), f"alpha={aoa:g}\"")
    cf = _zona(os.path.join(REFS, f"tmr_n0012cf_cfl3d_{modelo}.dat"), f"alpha={aoa:g},")
    k = int(np.argmin(cp[:, 0]))
    a, b = cp[:k + 1][::-1], cp[k:]
    if np.interp(0.1, a[:, 0], a[:, 1]) > np.interp(0.1, b[:, 0], b[:, 1]):
        a, b = b, a
    sup, inf = s.upper, ~s.upper
    dentro_sup = s.x[sup] < 0.98
    dentro_inf = s.x[inf] < 0.98
    d_sup = np.interp(s.x[sup], a[:, 0], a[:, 1])[dentro_sup] - s.cp[sup][dentro_sup]
    d_inf = np.interp(s.x[inf], b[:, 0], b[:, 1])[dentro_inf] - s.cp[inf][dentro_inf]
    orden = np.argsort(cf[:, 0])
    d_cf = np.interp(s.x[sup], cf[orden, 0], cf[orden, 1])[dentro_sup] - s.cf[sup][dentro_sup]
    return {"cp_rms": float(np.sqrt(np.mean(np.concatenate([d_sup, d_inf]) ** 2))),
            "cf_rms": float(np.sqrt(np.mean(d_cf ** 2))),
            "cp_min": float(s.cp.min()), "cp_min_tmr": float(cp[:, 1].min())}


def evaluate(c: BenchCase, job: Job) -> Dict[str, Any]:
    """Compara un caso terminado con sus referencias."""
    analisis = job.analysis or {}
    v = analisis.get("verdict") or {}
    fila: Dict[str, Any] = {"caso": asdict(c), "trabajo": job.id, "maquina": job.host, "estado": job.state,
                            "error": job.error, "veredicto": v.get("state"), "razon": v.get("reason"),
                            "cl": v.get("cl"), "cl_amp": v.get("cl_amp"), "cd": v.get("cd"),
                            "cd_amp": v.get("cd_amp"), "cm": v.get("cm"), "filas": v.get("n_rows"),
                            "yplus": (analisis.get("yplus") or {}).get("mean"), "comprobaciones": []}

    def comprueba(nombre: str, error: float, tope: float, texto: str) -> None:
        fila["comprobaciones"].append({"nombre": nombre, "error": error, "tope": tope,
                                       "cumple": abs(error) <= tope, "detalle": texto})

    if v.get("cl") is None or v.get("state") == "DIVERGIDO":
        return fila
    if c.aoa in TMR.get(c.turbulencia, {}) and c.radio == 500.0:
        ref_cl, ref_cd = _tmr_media(c.turbulencia, c.aoa)
        tol_cl, tol_cd = TOL_TMR[c.aoa]
        comprueba("Cl frente a TMR", _error_cl(v["cl"], ref_cl), tol_cl, f"{v['cl']:.4f} frente a {ref_cl:.4f}")
        comprueba("Cd frente a TMR", (v["cd"] - ref_cd) / ref_cd, tol_cd, f"{v['cd']:.5f} frente a {ref_cd:.5f}")
        lad_cl, lad_cd = ladson(c.aoa)
        tol_cl, tol_cd = TOL_LADSON[c.aoa]
        comprueba("Cl frente a Ladson", _error_cl(v["cl"], lad_cl), tol_cl, f"{v['cl']:.4f} frente a {lad_cl:.4f}")
        comprueba("Cd frente a Ladson", (v["cd"] - lad_cd) / lad_cd, tol_cd, f"{v['cd']:.5f} frente a {lad_cd:.5f}")
        try:
            d = surface_comparison(job.case_dir, c.turbulencia, c.aoa, float(job.params["u_inlet"]))
            comprueba("Cp frente a CFL3D (RMS)", d["cp_rms"], TOL_CP_RMS, f"pico {d['cp_min']:.3f} frente a {d['cp_min_tmr']:.3f}")
            comprueba("Cf frente a CFL3D (RMS)", d["cf_rms"], TOL_CF_RMS, "extradós, sin el 2 % final")
        except (ValueError, OSError) as e:
            fila["superficie"] = str(e)
    return fila


def run_bench(machines: List[Machine], casos: Optional[List[BenchCase]] = None,
              events: Optional[Events] = None) -> Dict[str, Any]:
    """Lanza el banco por el programa y devuelve la comparacion completa."""
    casos = casos if casos is not None else default_cases()
    d = Dispatcher(events, poll_s=8.0)
    d.set_machines(machines)
    trabajos = []
    for c in casos:
        j = new_job(case_parameters(c), label=c.etiqueta)
        trabajos.append(j)
        d.submit(j)
    d.wait()
    return summarize(casos, trabajos)


def summarize(casos: List[BenchCase], trabajos: List[Job]) -> Dict[str, Any]:
    filas = [evaluate(c, j) for c, j in zip(casos, trabajos)]
    dominio = _domain_test(filas)
    comprobaciones = [x for f in filas for x in f["comprobaciones"]] + dominio
    malos = [f for f in filas if f["veredicto"] != "CONVERGIDO"]
    return {"filas": filas, "dominio": dominio, "cumplidas": sum(1 for x in comprobaciones if x["cumple"]),
            "total": len(comprobaciones), "sin_converger": [f["caso"]["etiqueta"] for f in malos],
            "tolerancias": {"tmr": {str(k): v for k, v in TOL_TMR.items()},
                            "ladson": {str(k): v for k, v in TOL_LADSON.items()},
                            "cp_rms": TOL_CP_RMS, "cf_rms": TOL_CF_RMS, "dominio": TOL_DOMINIO}}


def _domain_test(filas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grupo = [f for f in filas if "dominio" in f["caso"]["etiqueta"] and f["cl"] is not None]
    if len(grupo) != 2:
        return []
    a, b = sorted(grupo, key=lambda f: f["caso"]["radio"])
    d_cl, d_cd = (a["cl"] - b["cl"]) / b["cl"], (a["cd"] - b["cd"]) / b["cd"]
    texto = f"{a['caso']['radio']:g}c frente a {b['caso']['radio']:g}c"
    return [{"nombre": "Efecto del dominio en Cl", "error": d_cl, "tope": TOL_DOMINIO[0],
             "cumple": abs(d_cl) <= TOL_DOMINIO[0], "detalle": f"{a['cl']:.4f} y {b['cl']:.4f}, {texto}"},
            {"nombre": "Efecto del dominio en Cd", "error": d_cd, "tope": TOL_DOMINIO[1],
             "cumple": abs(d_cd) <= TOL_DOMINIO[1], "detalle": f"{a['cd']:.5f} y {b['cd']:.5f}, {texto}"}]


def write_report(resultado: Dict[str, Any], carpeta: str) -> str:
    """Guarda banco.json y el informe PDF; devuelve la ruta del informe."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    os.makedirs(carpeta, exist_ok=True)
    with open(os.path.join(carpeta, "banco.json"), "w") as f:
        json.dump(resultado, f, indent=1, ensure_ascii=False)
    ruta = os.path.join(carpeta, "banco_validacion.pdf")
    estilos = getSampleStyleSheet()
    partes = [Paragraph("OpenBlade: banco de validación", estilos["Heading1"]),
              Paragraph("NACA 0012, Re = 6e6, con la malla y los valores por defecto del programa. "
                        f"Comprobaciones cumplidas: {resultado['cumplidas']} de {resultado['total']}. "
                        "Cumplir las tolerancias detecta errores gruesos; no certifica precisión.",
                        estilos["Normal"]), Spacer(1, 10)]
    if resultado["sin_converger"]:
        partes.append(Paragraph("Sin converger: " + ", ".join(resultado["sin_converger"]), estilos["Normal"]))
    filas = [["Caso", "Veredicto", "Cl", "Cd", "y+", "Máquina"]]
    for f in resultado["filas"]:
        filas.append([f["caso"]["etiqueta"], f["veredicto"] or f["estado"],
                      "" if f["cl"] is None else f"{f['cl']:.4f}", "" if f["cd"] is None else f"{f['cd']:.5f}",
                      "" if f["yplus"] is None else f"{f['yplus']:.2f}", f["maquina"].split("@")[-1]])
    t = Table(filas)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.grey), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                           ("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
    partes += [t, Spacer(1, 10), Paragraph("Comprobaciones", estilos["Heading2"])]
    filas = [["Caso", "Comprobación", "Error", "Tope", "¿Cumple?", "Detalle"]]
    estilo = [("BACKGROUND", (0, 0), (-1, 0), colors.grey), ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
              ("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 7)]
    pares = [(f["caso"]["etiqueta"], x) for f in resultado["filas"] for x in f["comprobaciones"]]
    pares += [("dominio", x) for x in resultado["dominio"]]
    for n, (etiqueta, x) in enumerate(pares, start=1):
        filas.append([etiqueta, x["nombre"], f"{x['error']:+.3f}", f"{x['tope']:.3f}", "sí" if x["cumple"] else "NO", x["detalle"]])
        if not x["cumple"]:
            estilo.append(("TEXTCOLOR", (0, n), (-1, n), colors.red))
    t = Table(filas)
    t.setStyle(TableStyle(estilo))
    partes.append(t)
    SimpleDocTemplate(ruta, pagesize=letter).build(partes)
    return ruta
