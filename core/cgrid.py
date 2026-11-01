"""Generador de mallas C para perfiles, con familias anidadas como las de NASA TMR.

Cada linea i sale de la pared en su normal y llega recta a un contorno exterior
ordenado, asi que las lineas no se cruzan y la malla no cambia con el angulo: el
angulo lo da el flujo. Las distribuciones son funciones de un indice normalizado
y no dependen del nivel: cada nivel contiene exactamente los puntos del anterior,
que es lo que exige un estudio de malla con factor de refinamiento 2.

    nivel 0: 113 x 33      nivel 1: 225 x 65      nivel 2: 449 x 129
    nivel 3: 897 x 257     nivel 4: 1793 x 513

La malla oficial de TMR con el mismo nombre tiene los mismos tamanos.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Tuple

import numpy as np

# Celdas del nivel 2 (449 x 129): por superficie, en la estela y en la normal.
CARAS_POR_LADO = 128
CELDAS_ESTELA = 96
CELDAS_NORMAL = 128
NIVEL_BASE = 2
NIVEL_MAX = 4
NIVELES = {0: "113 x 33", 1: "225 x 65", 2: "449 x 129", 3: "897 x 257", 4: "1793 x 513"}
# Separacion en el nivel 2, en cuerdas: como en la malla oficial 449 x 129.
PRIMERA_CELDA_MAX = 0.005
DS_MORRO = 2.0e-4
DS_SALIDA = 2.0e-3
ALTURA_NORMAL = 0.15    # hasta aqui la linea sale recta y normal a la pared
ALTURA_CURVA = 0.45     # punto de control de la curva con la que gira hacia el exterior
MEZCLA_EXTERIOR = 0.7   # cuanto se reparten las lineas por igual en el contorno exterior
ASPECTO_ESTELA = 3000.0 # celda mas alargada que se admite en la estela
# Abertura del borde de salida, en cuerdas: la malla C la cierra. Medido en un perfil de 30 %:
# 0.2 % de abertura adelgaza x/c=0.8 un 1.2 %, y 2 % un 11 %. Con 2 % faltaria ademas una
# resistencia de base del 27 % de Cd (Hoerner), mas que cualquier banda que da el programa.
ABERTURA_AVISO = 0.002
ABERTURA_MAX = 0.02


def naca4(codigo: str, n: int = 40001) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Contorno denso de un NACA de 4 digitos con borde de salida cerrado: xu, yu, xl, yl."""
    if len(codigo) != 4 or not codigo.isdigit():
        raise ValueError(f"Código NACA no válido: {codigo}")
    m, p, t = int(codigo[0]) / 100.0, int(codigo[1]) / 10.0, int(codigo[2:]) / 100.0
    if not 0.01 <= t <= 0.40:
        raise ValueError(f"Espesor del {100 * t:.0f} %: la serie admite de 1 a 40 %")
    if m > 0 and p == 0:
        raise ValueError(f"NACA {codigo}: con curvatura, la posición no puede ser 0")
    beta = np.linspace(0.0, math.pi, n)
    x = 0.5 * (1.0 - np.cos(beta))
    yt = 5 * t * (0.2969 * np.sqrt(x) - 0.1260 * x - 0.3516 * x ** 2 + 0.2843 * x ** 3 - 0.1036 * x ** 4)
    if m > 0 and p > 0:
        delante = x < p
        yc = np.where(delante, m / p ** 2 * (2 * p * x - x ** 2),
                      m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * x - x ** 2))
        dyc = np.where(delante, 2 * m / p ** 2 * (p - x), 2 * m / (1 - p) ** 2 * (p - x))
    else:
        yc, dyc = np.zeros_like(x), np.zeros_like(x)
    th = np.arctan(dyc)
    return x - yt * np.sin(th), yc + yt * np.cos(th), x + yt * np.sin(th), yc - yt * np.cos(th)


def _contour_sides(ruta: str, n: int) -> Tuple[np.ndarray, np.ndarray]:
    """Extrados e intrados de un archivo x y, del morro a la salida, con cuerda 1."""
    filas = []
    with open(ruta) as f:
        for linea in f:
            partes = linea.replace(",", " ").split()
            if len(partes) >= 2:
                try:
                    filas.append((float(partes[0]), float(partes[1])))
                except ValueError:
                    continue
    if len(filas) < 8:
        raise ValueError(f"{ruta}: muy pocas coordenadas")
    xy = np.array(filas)
    if abs(xy[0, 0]) > 2:                       # primera fila con cuentas (Lednicer)
        xy = xy[1:]
    if xy[0, 0] < 0.5:                          # Lednicer: dos tramos desde el morro
        corte = next(i for i in range(1, len(xy)) if xy[i, 0] < xy[i - 1, 0])
        xy = np.concatenate([xy[:corte][::-1], xy[corte + 1:]])
    # Una sola spline por todo el contorno: dos que se unan en el morro hacen un
    # quiebro, y ahi las normales se cruzan.
    from scipy.interpolate import CubicSpline
    s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])
    t = np.linspace(0.0, s[-1], 2 * n)
    x, y = CubicSpline(s, xy[:, 0])(t), CubicSpline(s, xy[:, 1])(t)
    k = int(np.argmin(x))
    a, b = np.column_stack([x[:k + 1][::-1], y[:k + 1][::-1]]), np.column_stack([x[k:], y[k:]])
    if np.interp(0.3, a[:, 0], a[:, 1]) < np.interp(0.3, b[:, 0], b[:, 1]):
        a, b = b, a
    x0, y0 = x[k], y[k]
    c = max(a[-1, 0], b[-1, 0]) - x0
    return (a - [x0, y0]) / c, (b - [x0, y0]) / c


def trailing_edge_gap(ruta: str, n: int = 2001) -> float:
    """Abertura del borde de salida del archivo, en cuerdas."""
    a, b = _contour_sides(ruta, n)
    return float(np.hypot(*(a[-1] - b[-1])))


def opening_notice(abertura: float, cd: float = 0.012) -> str:
    """Lo que cambia al cerrar el borde. El arrastre que falta es la formula de Hoerner."""
    falta = 0.135 * abertura ** (4.0 / 3.0) / cd ** (1.0 / 3.0)
    return (f"⚠️ Borde de salida abierto {100 * abertura:.2f} % de la cuerda: la malla C lo cierra, así que se "
            f"calcula un perfil algo más delgado atrás y sin resistencia de base (Hoerner: ΔCd≈{falta:.4f} "
            f"con Cd={cd:g}). Esa diferencia no entra en la banda de malla.")


def read_contour(ruta: str, n: int = 40001) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Perfil de un archivo x y, normalizado a cuerda 1 y densificado.

    Si el borde de salida esta abierto se cierra repartiendo la abertura de forma
    lineal con la cuerda: la malla C necesita un punto unico de salida. Con una abertura
    grande eso ya seria otro perfil, y se rechaza.
    """
    a, b = _contour_sides(ruta, n)
    abertura = float(np.hypot(*(a[-1] - b[-1])))
    if abertura > ABERTURA_MAX:
        raise ValueError(f"{ruta}: el borde de salida está abierto {100 * abertura:.1f} % de la cuerda. La malla C "
                         f"lo cierra y admite hasta {100 * ABERTURA_MAX:g} %: con más calcularía otro perfil.")
    medio = 0.5 * (a[-1, 1] + b[-1, 1])
    a[:, 1] -= a[:, 0] * (a[-1, 1] - medio)
    b[:, 1] -= b[:, 0] * (b[-1, 1] - medio)
    return a[:, 0], a[:, 1], b[:, 0], b[:, 1]


def vinokur(xi: np.ndarray, d0: float, d1: float, n_ref: int) -> np.ndarray:
    """Funcion de reparto en [0,1] con separacion d0 y d1 en los extremos para n_ref celdas."""
    s0, s1 = (1.0 / n_ref) / d0, (1.0 / n_ref) / d1
    a, b = math.sqrt(s0 / s1), math.sqrt(s0 * s1)
    if b <= 1.0:
        raise ValueError("Con esos extremos no hace falta agrupar puntos: revisa las separaciones")
    # sinh(d)/d = b
    d = 1.0
    for _ in range(100):
        d -= (math.sinh(d) / d - b) / ((d * math.cosh(d) - math.sinh(d)) / d ** 2)
    u = 0.5 * (1.0 + np.tanh(d * (xi - 0.5)) / math.tanh(d / 2.0))
    return u / (a + (1.0 - a) * u)


def _razon(total: float, primero: float, n: int) -> float:
    """r tal que primero * (r^n - 1) / (r - 1) = total."""
    lo, hi = 1.0 + 1e-9, 4.0
    for _ in range(200):
        r = 0.5 * (lo + hi)
        if primero * (r ** n - 1.0) / (r - 1.0) < total:
            lo = r
        else:
            hi = r
    return 0.5 * (lo + hi)


def _lado(x: np.ndarray, y: np.ndarray, n: int, d_le: float, d_te: float) -> Tuple[np.ndarray, np.ndarray]:
    """n+1 puntos de una superficie, del morro al borde de salida."""
    s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    longitud = s[-1]
    t = vinokur(np.linspace(0.0, 1.0, n + 1), d_le / longitud, d_te / longitud, CARAS_POR_LADO)
    return np.interp(t * longitud, s, x), np.interp(t * longitud, s, y)


def _normales(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Normal a la izquierda del avance en cada punto de la linea, por diferencias centradas."""
    dx, dy = np.gradient(x), np.gradient(y)
    largo = np.hypot(dx, dy)
    return np.column_stack([-dy / largo, dx / largo])


def _exterior(p: np.ndarray, n: np.ndarray, radio: float, x_out: float, centro: float) -> np.ndarray:
    """Donde llega al contorno una linea que sale de p en la direccion n.

    El contorno es un semicirculo por delante de x=centro y dos rectas y=+-radio
    hasta la salida.
    """
    fin = np.empty_like(p)
    for k in range(len(p)):
        d = n[k]
        if abs(d[1]) > 1e-12:
            t = (math.copysign(radio, d[1]) - p[k, 1]) / d[1]
            xh = p[k, 0] + t * d[0]
            if centro <= xh:
                fin[k] = (min(xh, x_out), math.copysign(radio, d[1]))
                continue
        # Corte con el circulo
        oc = p[k] - (centro, 0.0)
        b = oc @ d
        t = -b + math.sqrt(max(b * b - (oc @ oc - radio ** 2), 0.0))
        fin[k] = p[k] + t * d
    return fin


def generate_cgrid(contorno: Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray], primera_celda: float,
                   nivel: int = NIVEL_BASE, radio: float = 500.0,
                   estela: float = 0.0) -> Tuple[np.ndarray, np.ndarray]:
    """Rejilla x(i,j), y(i,j) de cuerda 1. `primera_celda` es la del nivel 2.

    i va de la salida inferior a la superior pasando por el perfil; j de la pared
    al contorno exterior.
    """
    if nivel not in NIVELES:
        raise ValueError(f"Nivel {nivel}: los hay de 0 a 4")
    if radio < 5.0:
        raise ValueError(f"Radio del dominio de {radio:g} cuerdas: el mínimo es 5")
    if not 1e-8 <= primera_celda <= 0.01:
        raise ValueError(f"Primera celda de {primera_celda:g} cuerdas fuera de rango")
    # Se construye siempre el nivel mas fino y se toma uno de cada 2^k puntos: las
    # normales y el contorno exterior son exactamente los mismos en todos los niveles.
    factor = 2.0 ** (NIVEL_MAX - NIVEL_BASE)
    n_lado = int(CARAS_POR_LADO * factor)
    n_estela = int(CELDAS_ESTELA * factor)
    n_normal = int(CELDAS_NORMAL * factor)
    xu, yu, xl, yl = contorno
    x_out = 1.0 + (estela if estela > 0 else radio)

    # j=0 sobre el perfil
    sup = _lado(xu, yu, n_lado, DS_MORRO, DS_SALIDA)
    inf = _lado(xl, yl, n_lado, DS_MORRO, DS_SALIDA)
    te_x, te_y = 0.5 * (xu[-1] + xl[-1]), 0.5 * (yu[-1] + yl[-1])

    # j=0 sobre la estela: progresion geometrica con continuidad de separacion
    largo = x_out - te_x
    r = _razon(largo, DS_SALIDA, CELDAS_ESTELA)
    xi = np.linspace(0.0, 1.0, n_estela + 1)
    w = (r ** (xi * CELDAS_ESTELA) - 1.0) / (r ** CELDAS_ESTELA - 1.0)
    wx, wy = te_x + largo * w, te_y + 0.0 * w

    x0 = np.concatenate([wx[::-1], inf[0][::-1][1:], sup[0][1:], wx[1:]])
    y0 = np.concatenate([wy[::-1], inf[1][::-1][1:], sup[1][1:], wy[1:]])
    ni = x0.size
    p = np.column_stack([x0, y0])

    # Direccion de cada linea. Las del perfil son normales; las de la estela heredan
    # la inclinacion de la ultima del perfil y la pierden hasta la salida: asi no se
    # cruzan con ella por muy lejos que vayan.
    n = _normales(x0, y0)
    i_te_inf, i_te_sup = n_estela, ni - 1 - n_estela
    sup_n = _normales(sup[0], sup[1])[-1]
    inf_n = _normales(inf[0][::-1], inf[1][::-1])[0]
    n[i_te_sup] = sup_n
    n[i_te_inf] = inf_n
    for k in range(n_estela):
        # Se pierde con la distancia, no con el indice: con el indice las lineas
        # junto al borde de salida adelantaban a la anterior.
        peso = 1.0 - w[k + 1]
        tanu = sup_n[0] / sup_n[1] * peso
        tanl = inf_n[0] / abs(inf_n[1]) * peso
        n[i_te_sup + 1 + k] = np.array([tanu, 1.0]) / math.hypot(tanu, 1.0)
        n[i_te_inf - 1 - k] = np.array([tanl, -1.0]) / math.hypot(tanl, 1.0)

    # Puntos del contorno exterior. Prolongar las normales agolparia alli las lineas
    # que salen juntas del borde de salida: columnas de ancho 0.003 y alto 60, que dan
    # no ortogonalidad de casi 90 grados. Se reparten mezclando la proyeccion con un
    # reparto uniforme; las lineas siguen saliendo normales de la pared.
    centro = 0.5
    fin = _reparte_exterior(_exterior(p, n, radio, x_out, centro), radio, x_out, centro)

    # Distancia desde la pared: razon constante, la misma funcion en todos los niveles.
    eta = np.linspace(0.0, 1.0, n_normal + 1)
    rn = _razon(radio, primera_celda, CELDAS_NORMAL)
    d = primera_celda * (rn ** (eta * CELDAS_NORMAL) - 1.0) / (rn - 1.0)

    x = np.empty((ni, n_normal + 1))
    y = np.empty_like(x)
    # Cada linea: recta y normal hasta ALTURA_NORMAL, una curva de Bezier y una recta
    # hasta su punto del contorno. Con los puntos en orden no se cruzan.
    h0, h1 = ALTURA_NORMAL, ALTURA_CURVA
    tramo_curvo = 2.0 * (h1 - h0)
    control = p + h1 * n
    hacia = fin - control
    hacia /= np.linalg.norm(hacia, axis=1)[:, None]
    q0, q2 = p + h0 * n, control + (h1 - h0) * hacia
    rectos = np.linalg.norm(fin - q2, axis=1)
    longitudes = h0 + tramo_curvo + rectos
    # En la estela la primera celda crece con la distancia al borde de salida. Con la
    # de la pared, lejos del perfil salian celdas de aspecto 1e7 sin ningun provecho.
    distancia_estela = np.zeros(ni)
    distancia_estela[:n_estela] = x0[:n_estela] - te_x
    distancia_estela[ni - n_estela:] = x0[ni - n_estela:] - te_x
    for i in range(ni):
        relleno = 0.4 * distancia_estela[i] / ASPECTO_ESTELA * CELDAS_NORMAL
        base = (d + relleno * eta) * radio / (radio + relleno)
        s = base * (1.0 + (longitudes[i] / radio - 1.0) * (base / radio))
        en_curva = (s > h0) & (s <= h0 + tramo_curvo)
        en_recta = s > h0 + tramo_curvo
        punto = p[i] + s[:, None] * n[i]
        u = (s[en_curva] - h0)[:, None] / tramo_curvo
        punto[en_curva] = (1 - u) ** 2 * q0[i] + 2 * u * (1 - u) * control[i] + u ** 2 * q2[i]
        v = (s[en_recta] - h0 - tramo_curvo)[:, None] / rectos[i]
        punto[en_recta] = q2[i] + v * (fin[i] - q2[i])
        x[i], y[i] = punto[:, 0], punto[:, 1]
    # La salida es una recta vertical
    x[0, :] = x_out
    x[-1, :] = x_out
    salto = 2 ** (NIVEL_MAX - nivel)
    return x[::salto, ::salto], y[::salto, ::salto]


def _reparte_exterior(fin: np.ndarray, radio: float, x_out: float, centro: float) -> np.ndarray:
    """Puntos del contorno exterior en orden, sin agolparse."""
    # Abscisa de recorrido: 0 en la salida inferior, creciente hasta la superior.
    tramo_recta = x_out - centro
    def abscisa(q):
        if q[0] >= centro:
            base = x_out - q[0]
            return base if q[1] < 0 else 2 * tramo_recta + math.pi * radio - base
        angulo = math.atan2(q[1], centro - q[0])    # -pi/2 abajo ... pi/2 arriba
        return tramo_recta + (angulo + math.pi / 2) * radio

    def punto(s):
        if s <= tramo_recta:
            return x_out - s, -radio
        if s >= tramo_recta + math.pi * radio:
            return x_out - (2 * tramo_recta + math.pi * radio - s), radio
        angulo = (s - tramo_recta) / radio - math.pi / 2
        return centro - radio * math.cos(angulo), radio * math.sin(angulo)

    s = np.array([abscisa(q) for q in fin])
    # Un perfil concavo puede hacer que una normal adelante a la anterior.
    s = np.maximum.accumulate(s)
    uniforme = np.linspace(s[0], s[-1], len(s))
    return np.array([punto(v) for v in (1.0 - MEZCLA_EXTERIOR) * s + MEZCLA_EXTERIOR * uniforme])


def contour_from_params(params: Dict) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if "Custom" in params.get("profile_type", ""):
        return read_contour(params["file_path"])
    return naca4(str(params.get("naca", "0012")))


def cells_of_level(nivel: int) -> Tuple[int, int]:
    """Celdas de la rejilla de un nivel, a lo largo del contorno y normales a la pared."""
    factor = 2.0 ** (nivel - NIVEL_BASE)
    return int(2 * (CARAS_POR_LADO + CELDAS_ESTELA) * factor), int(CELDAS_NORMAL * factor)


def first_cell_of(params: Dict) -> float:
    """Primera celda del nivel 2, en cuerdas, para el y+ pedido a este Reynolds.

    A Reynolds bajos la formula, que es turbulenta, pide una celda tan alta como la capa
    limite: a Re = 1000 da 0.014 cuerdas. Se acota, y el y+ medido dira lo que salio.
    """
    from core.yplus import first_cell_for_yplus
    altura = first_cell_for_yplus(float(params.get("yplus_target", 0.5)), float(params.get("reynolds", 1e6)))
    return min(altura, PRIMERA_CELDA_MAX)


def first_cell_at_level(params: Dict) -> float:
    """Altura real de la primera celda con el nivel de malla elegido."""
    nivel = int(params.get("grid_level", NIVEL_BASE))
    return first_cell_of(params) * 2.0 ** (NIVEL_BASE - nivel)


def transient_notice(params: Dict) -> str:
    """Cuanto va a costar un transitorio: con y+ < 1 el paso lo fija la primera celda.

    Medido en el nivel 1 a 18 grados, el paso real es unas 2.5 veces Co * h / U.
    """
    h = first_cell_at_level(params) * float(params.get("chord", 1.0))
    max_co = float(params.get("max_co", 10.0))
    paso = max_co * h / float(params.get("u_inlet", 15.0))
    pasos = float(params.get("end_time", 0.5)) / paso
    texto = (f"⏱️ Transitorio: con Courant {max_co:g} el paso será del orden de {paso:.0e} s, "
             f"unos {pasos:,.0f} pasos hasta t = {params.get('end_time', 0.5)} s.")
    if pasos > 200_000:
        texto += " Es muy largo: acorta el tiempo final o sube el Courant máximo (10 es estable en esta malla, 30 diverge)."
    return texto


def build_mesh(params: Dict, salida: str) -> Dict:
    """Genera la malla de estos parametros y la escribe como .msh."""
    import json
    from core.structured_mesh import write_cgrid_msh, write_preview_vtk

    nivel = int(params.get("grid_level", NIVEL_BASE))
    cuerda = float(params.get("chord", 1.0))
    x, y = generate_cgrid(contour_from_params(params), first_cell_of(params), nivel,
                          float(params.get("farfield", 500.0)), float(params.get("wake_length", 0.0)))
    info = write_cgrid_msh(salida, x * cuerda, y * cuerda, float(params.get("depth", 0.1)) * cuerda)
    info["mallador"] = f"C propia, nivel {nivel} ({NIVELES[nivel]})"
    if "Custom" in params.get("profile_type", ""):
        abertura = trailing_edge_gap(params["file_path"])
        info["abertura_borde_salida"] = round(abertura, 5)
        if abertura > ABERTURA_AVISO:
            info["aviso"] = opening_notice(abertura)
    with open(salida + ".info.json", "w") as f:
        json.dump(info, f, ensure_ascii=False)
    write_preview_vtk(salida.replace(".msh", ".vtk"), x * cuerda, y * cuerda)
    return info
