"""Veredicto de una corrida: lo que el programa afirma de sus propios numeros.

Que el solver termine con codigo 0 no dice nada del resultado: un NACA 0012 a
8 grados con Cl entre -897 y +728 termina con codigo 0. El veredicto se decide
con las fuerzas de la ventana final, no con la ultima fila.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from core.forces import ForceDataError, ForceHistory, read_forces

CONVERGIDO = "CONVERGIDO"
NO_CONVERGIDO = "NO CONVERGIDO"
DIVERGIDO = "DIVERGIDO"
SIN_DATOS = "SIN DATOS"

VENTANA = 500           # iteraciones finales que se evaluan
FRACCION_TRAMO = 5      # la deriva se mide entre los dos ultimos quintos de la corrida
MIN_FILAS = 100         # con menos no se puede juzgar nada
TOL_RANGO = 0.01        # (max-min)/|media| dentro de la ventana
TOL_DERIVA = 0.003      # cambio de la media de Cd entre esos dos tramos
TOL_DERIVA_TRANS = 0.01
TOL_DERIVA_CL = 0.0015  # cambio de la media de Cl entre esos dos tramos, sobre max(|Cl|, CL_REF)
CL_REF = 0.1            # con Cl casi nulo la tolerancia relativa no sirve
TOL_CL_ABS = 0.002      # amplitud minima de Cl que se tolera en la ventana
TOL_CM_ABS = 0.002
ARRANQUE = 0.2          # fraccion inicial donde un pico de fuerzas es normal
# Ningun perfil aislado sin soplado se acerca a estos valores.
CL_IMPOSIBLE = 5.0
CD_IMPOSIBLE = 5.0
RC_DETENIDA = 143       # SIGTERM: la detuvo el usuario


@dataclass
class Verdict:
    state: str
    reason: str
    transient: bool = False
    n_rows: int = 0
    window: int = 0
    cl: Optional[float] = None
    cl_amp: Optional[float] = None
    cd: Optional[float] = None
    cd_amp: Optional[float] = None
    cm: Optional[float] = None
    cm_amp: Optional[float] = None
    cd_range_pct: Optional[float] = None
    cd_drift_pct: Optional[float] = None
    cl_drift: Optional[float] = None    # cambio absoluto de la media de Cl entre tramos
    max_abs_cl: Optional[float] = None
    period: Optional[float] = None
    oscila: bool = False    # NO CONVERGIDO solo por la amplitud: la media ya es estable

    @property
    def usable(self) -> bool:
        """Los coeficientes se pueden presentar como resultado."""
        return self.state == CONVERGIDO

    def coefficients_text(self) -> str:
        if self.cl is None or self.state == DIVERGIDO:
            return "sin coeficientes validos"
        return (f"Cl = {self.cl:.4f} ± {self.cl_amp:.4f}   "
                f"Cd = {self.cd:.5f} ± {self.cd_amp:.5f}   "
                f"Cm = {self.cm:.4f} ± {self.cm_amp:.4f}")

    def summary(self) -> str:
        return f"{self.state}: {self.reason}\n{self.coefficients_text()}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _media_amplitud(valores: List[float]) -> Tuple[float, float]:
    return sum(valores) / len(valores), (max(valores) - min(valores)) / 2.0


def _media_temporal(t: List[float], v: List[float]) -> float:
    """Media ponderada por el paso de tiempo, que en transitorio no es constante."""
    total = t[-1] - t[0]
    if total <= 0:
        return sum(v) / len(v)
    return sum((t[i + 1] - t[i]) * (v[i] + v[i + 1]) / 2.0
               for i in range(len(t) - 1)) / total


def _periodos_enteros(t: List[float], v: List[float]) -> Tuple[int, int, Optional[float]]:
    """Tramo con un numero entero de periodos, si la senal oscila.

    Promediar un desprendimiento de vortices sobre periodos incompletos sesga la
    media. Un cruce solo cuenta si la senal bajo antes de la franja central: asi
    el ruido alrededor de la media no crea periodos falsos.
    """
    media, amplitud = _media_amplitud(v)
    cruces, abajo = [], False
    for i, x in enumerate(v):
        if x < media - 0.25 * amplitud:
            abajo = True
        elif abajo and x >= media:
            cruces.append(i)
            abajo = False
    if len(cruces) < 3:
        return 0, len(v), None
    periodo = (t[cruces[-1]] - t[cruces[0]]) / (len(cruces) - 1)
    return cruces[0], cruces[-1] + 1, periodo


def tramo_final(x: List[float]) -> Tuple[float, float]:
    """Media del ultimo quinto de la corrida y del anterior, nunca menos que la ventana.

    En una malla fina la convergencia es mas lenta: entre dos ventanas fijas de 500
    iteraciones Cd cambia muy poco y aun le falta mas de un 1 %. Con tramos que crecen con
    la corrida el cambio medido no depende de la malla. Medido en el NACA 0012: la primera
    iteracion con CONVERGIDO queda a 0.39 % de Cd del valor final como mucho, y con un
    decimo de la corrida quedaba a 1.9 %.
    """
    n = len(x)
    w = min(max(VENTANA, n // FRACCION_TRAMO), n // 2)
    return sum(x[n - w:]) / w, sum(x[n - 2 * w:n - w]) / w


def veredicto_de_series(cd: List[float], cl: List[float], transient: bool = False) -> Verdict:
    """El veredicto de una corrida a partir de sus series, sin ficha ni case.

    Es el mismo `evaluate`, construido con lo minimo que necesita. Existe para que el
    vigilante que recorta la corrida juzgue con el criterio del veredicto y no con uno
    propio: antes aprobaba la deriva con tramos de un decimo de la corrida y el
    veredicto la medía entre quintos, asi que el recorte cerraba corridas que despues
    salian NO CONVERGIDO.
    """
    if not cd or len(cd) != len(cl):
        return Verdict(SIN_DATOS, "Sin fuerzas suficientes para juzgar", transient)
    h = ForceHistory(columns={"Time": [float(i) for i in range(len(cd))],
                              "Cl": list(cl), "Cd": list(cd), "Cm": [0.0] * len(cd)},
                     sources=[])
    return evaluate(h, transient=transient)


def _inicio_ventana(h: ForceHistory, transient: bool) -> Tuple[int, int]:
    """Indices donde empiezan la ventana anterior y la evaluada."""
    n = len(h)
    if not transient:
        w = min(VENTANA, n // 2)
        return n - 2 * w, n - w
    t = h.time
    t_fin = t[-1]
    duracion = t_fin - t[0]
    corte = next(i for i, x in enumerate(t) if x >= t_fin - 0.25 * duracion)
    previo = next(i for i, x in enumerate(t) if x >= t_fin - 0.50 * duracion)
    return previo, corte


def _tol_cl(media: float) -> float:
    return max(TOL_RANGO * abs(media), TOL_CL_ABS)


def evaluate(h: ForceHistory, transient: bool = False, rc: int = 0,
             log_tail: str = "") -> Verdict:
    """Decide el estado de la corrida a partir de su historia de fuerzas."""
    n = len(h)
    if n == 0:
        return Verdict(SIN_DATOS, f"El solver no escribio fuerzas (codigo {rc})",
                       transient)
    base = {"transient": transient, "n_rows": n}

    todas = h.cl + h.cd + h.cm
    if not all(math.isfinite(x) for x in todas):
        return Verdict(DIVERGIDO, "Aparecen valores NaN o infinitos en las fuerzas",
                       **base)
    if "sigFpe" in log_tail or "Floating point exception" in log_tail:
        return Verdict(DIVERGIDO, "El solver abortó por una excepción de punto "
                                  "flotante", **base)
    if n < MIN_FILAS:
        razon = f"Solo hay {n} filas de fuerzas; no alcanza para juzgar"
        if rc:
            razon += f" (el solver terminó con código {rc})"
        return Verdict(NO_CONVERGIDO, razon, **base)

    previo, corte = _inicio_ventana(h, transient)
    cl, cd, cm = h.cl[corte:], h.cd[corte:], h.cm[corte:]
    base.update(window=len(cl), max_abs_cl=max(abs(x) for x in h.cl))

    if transient:
        t = h.time[corte:]
        i0, i1, periodo = _periodos_enteros(t, cl)
        m_cl, m_cd, m_cm = (_media_temporal(t[i0:i1], x[i0:i1]) for x in (cl, cd, cm))
        a_cl, a_cd, a_cm = (_media_amplitud(x)[1] for x in (cl, cd, cm))
        base["period"] = periodo
    else:
        (m_cl, a_cl), (m_cd, a_cd), (m_cm, a_cm) = (
            _media_amplitud(x) for x in (cl, cd, cm))
    base.update(cl=m_cl, cl_amp=a_cl, cd=m_cd, cd_amp=a_cd, cm=m_cm, cm_amp=a_cm)

    pico = max(abs(x) for x in cl)
    if pico > CL_IMPOSIBLE or max(abs(x) for x in cd) > CD_IMPOSIBLE:
        return Verdict(DIVERGIDO, f"|Cl| llega a {pico:.1f} en la ventana final; "
                                  "no es un valor físico", **base)
    negativos = sum(1 for x in cd if x < 0)
    if negativos:
        return Verdict(DIVERGIDO, f"Cd es negativo en {negativos} de {len(cd)} "
                                  "filas de la ventana final", **base)

    # Una corrida que se dispara a mitad de camino y luego se serena no es de fiar,
    # aunque termine estable. En el arranque los picos son normales.
    desde = int(ARRANQUE * n)
    for i in range(desde, n):
        if abs(h.cl[i]) > CL_IMPOSIBLE or abs(h.cd[i]) > CD_IMPOSIBLE:
            return Verdict(NO_CONVERGIDO, f"Las fuerzas se dispararon en t = {h.time[i]:g} "
                                          f"(Cl = {h.cl[i]:.1f}) antes de estabilizarse", **base)

    rango_cd = 100.0 * 2 * a_cd / abs(m_cd) if m_cd else math.inf
    if transient:
        t_previo = h.time[previo:corte]
        cd_previo = h.cd[previo:corte]
        j0, j1, _ = _periodos_enteros(t_previo, h.cl[previo:corte])
        media_previa, cd_reciente = _media_temporal(t_previo[j0:j1], cd_previo[j0:j1]), m_cd
    else:
        cd_reciente, media_previa = tramo_final(h.cd)
    deriva_cd = 100.0 * abs(cd_reciente - media_previa) / abs(cd_reciente) if cd_reciente else math.inf
    # Una deriva lenta no se ve en el rango de una ventana y puede sumar varios por ciento.
    if transient:
        cl_previo = h.cl[previo:corte]
        cl_reciente, media_cl_previa = m_cl, _media_temporal(t_previo[j0:j1], cl_previo[j0:j1])
    else:
        cl_reciente, media_cl_previa = tramo_final(h.cl)
    base.update(cd_range_pct=rango_cd, cd_drift_pct=deriva_cd, cl_drift=abs(cl_reciente - media_cl_previa))

    if rc == RC_DETENIDA:
        return Verdict(NO_CONVERGIDO, "Se detuvo antes de terminar", **base)
    if rc:
        return Verdict(NO_CONVERGIDO, f"El solver terminó con código {rc}", **base)

    ventana = (f"el último 25 % del tiempo simulado" if transient
               else f"las últimas {len(cl)} iteraciones")
    tol_deriva = 100.0 * (TOL_DERIVA_TRANS if transient else TOL_DERIVA)
    if deriva_cd > tol_deriva:
        return Verdict(NO_CONVERGIDO, f"La media de Cd aún cambia {deriva_cd:.2f} % "
                                      f"entre tramos (máximo {tol_deriva:g} %)", **base)
    if abs(cl_reciente - media_cl_previa) > TOL_DERIVA_CL * max(abs(cl_reciente), CL_REF):
        return Verdict(NO_CONVERGIDO, f"La media de Cl aún cambia de {media_cl_previa:.4f} a "
                                      f"{cl_reciente:.4f} entre tramos", **base)
    if not transient:
        if rango_cd > 100.0 * TOL_RANGO:
            return Verdict(NO_CONVERGIDO, f"Cd varía {rango_cd:.2f} % en {ventana} "
                                          f"(máximo {100 * TOL_RANGO:.0f} %)", oscila=True, **base)
        if 2 * a_cl > _tol_cl(m_cl):
            return Verdict(NO_CONVERGIDO, f"Cl varía {2 * a_cl:.4f} en {ventana} "
                                          f"(máximo {_tol_cl(m_cl):.4f})", oscila=True, **base)
        if 2 * a_cm > max(TOL_RANGO * abs(m_cm), TOL_CM_ABS):
            return Verdict(NO_CONVERGIDO, f"Cm varía {2 * a_cm:.4f} en {ventana}", oscila=True, **base)
        return Verdict(CONVERGIDO, f"Cd varía {rango_cd:.2f} % en {ventana}", **base)
    return Verdict(CONVERGIDO, f"La media de Cd cambia {deriva_cd:.2f} % entre "
                               f"ventanas; {ventana} promedia el régimen", **base)


def _cola_log(case_dir: str, limite: int = 200_000) -> str:
    try:
        with open(os.path.join(case_dir, "run.log"), errors="replace") as f:
            f.seek(max(0, os.path.getsize(f.name) - limite))
            return f.read()
    except OSError:
        return ""


def evaluate_case(case_dir: str, transient: bool = False, rc: int = 0) -> Verdict:
    """Veredicto del caso; SIN DATOS si no hay fuerzas que se puedan leer."""
    try:
        h = read_forces(case_dir)
    except ForceDataError as e:
        return Verdict(SIN_DATOS, str(e), transient)
    return evaluate(h, transient, rc, _cola_log(case_dir) if rc else "")


def analyze_case(case_dir: str, transient: bool = False, rc: int = 0,
                 host: str = "", job_dir: str = "", error: str = "") -> Dict[str, Any]:
    """Veredicto, y+ y malla del caso; se guardan en resultado.json y en su ficha."""
    from core.package import complete_ficha, mesh_notice, parse_checkmesh
    from core.yplus import YPlusError, compute_yplus, regime_notice

    verdict = evaluate_case(case_dir, transient, rc)
    if error and verdict.state == SIN_DATOS:
        verdict.reason = error
    resultado: Dict[str, Any] = {"verdict": verdict.to_dict(), "yplus": None,
                                 "yplus_notice": None}
    try:
        yp = compute_yplus(case_dir)
        nivel, aviso = regime_notice(yp)
        resultado.update(yplus=yp.to_dict(),
                         yplus_notice={"level": nivel, "text": aviso})
    except YPlusError as e:
        resultado["yplus_notice"] = {"level": "sin datos", "text": f"y+ no disponible: {e}"}
    try:
        from core.surface import surface_summary
        resultado["superficie"] = surface_summary(case_dir)
    except (YPlusError, OSError, ValueError, IndexError, KeyError):
        resultado["superficie"] = None
    try:
        with open(os.path.join(case_dir, "log.checkMesh"), errors="replace") as f:
            resultado["mesh_notice"] = mesh_notice(parse_checkmesh(f.read()))
    except OSError:
        resultado["mesh_notice"] = None
    try:
        with open(os.path.join(case_dir, "resultado.json"), "w") as f:
            json.dump(resultado, f, indent=2, ensure_ascii=False, allow_nan=False)
    except (OSError, ValueError):
        pass
    complete_ficha(case_dir, resultado, rc, host, job_dir)
    return resultado
