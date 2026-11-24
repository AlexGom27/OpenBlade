"""Regresión con las cifras de referencia de v1.0.2 (bb27cca).

Los fixtures son las últimas 1200 filas de historiales de fuerzas reales de la campaña
de bb27cca, no historias sintéticas. Sobre un historial fijo el cálculo es
determinista, así que aquí se fija el valor exacto que da el código (rel=1e-9) y, en
otra aserción aparte, que ese valor redondeado es el que publica el artículo.

Origen (OpenBlade_proyecto/trabajos_v1.0.2_bb27cca), polar limpia `_tiempo2`
del 23-nov, sola en los dos servidores:

  naca0012_re6e6_a0_n2.dat    20261123_113010_gci_a0_n2_afcd
  naca0012_re6e6_a10_n1.dat   20261123_113010_gci_a10_n1_e68e
  naca0012_re6e6_a10_n2.dat   20261123_113010_gci_a10_n2_c25e
  naca0012_re6e6_a10_n3.dat   20261123_113010_gci_a10_n3_94ec
  naca0012_re6e6_a14_n1.dat   20261123_113010_gci_a14_n1_a3ec
  naca0012_re6e6_a14_n2.dat   20261123_113010_gci_a14_n2_eeae
  naca0012_re6e6_a14_n3.dat   20261123_113010_gci_a14_n3_7cc5

Las cifras del artículo están en docs/VALIDACION.md, §4 y §6, y en el manuscrito.
"""

import os
import sys

import pytest

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, RAIZ)

from core.forces import ForceHistory, parse_force_lines
from core.gci import study_from_levels
from core.verdict import CONVERGIDO, evaluate

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

REL = 1e-9  # el cálculo sobre un historial fijo es determinista

# Lo que da el código hoy con estos fixtures: (estado, Cl, Cd, Cm, filas).
# Cualquier cambio en el lector de columnas, la ventana o el promedio lo delata.
REPR_EXACTA = {
    "a0_n2": ("CONVERGIDO", -5.59567907181334e-07, 0.007839027217246356,
              1.0719407814503286e-07, 1200),
    "a10_n2": ("CONVERGIDO", 1.065628579746473, 0.011424218536646075,
               0.008499893062016959, 1200),
    "a14_n2": ("CONVERGIDO", 1.4301320857425872, 0.017320150047244343,
               0.015707697839471384, 1200),
}

# Medias exactas de la ventana (500 filas) de los tres niveles de cada estudio.
# Se guardan aparte porque los niveles 1 de ambos estudios NO son convergentes
# (oscilan), y aun así su media es la que entra en el GCI.
MEDIAS_EXACTAS = {
    "a10_n1": (1.067121267239296, 0.010075770812888081),
    "a10_n2": (1.065628579746473, 0.011424218536646075),
    "a10_n3": (1.0628320183444353, 0.011968574325957094),
    "a14_n1": (1.4215037186227921, 0.015669691164972462),
    "a14_n2": (1.4301320857425872, 0.017320150047244343),
    "a14_n3": (1.4264161543073417, 0.018186392043605726),
}

# Cifras publicadas: docs/VALIDACION.md §4 (polar) y §6 (estudios de malla).
ART_A10_CL, ART_A10_CD = 1.0656, 0.01142
ART_A0_CD = 0.00784
ART_A10_LVL = {1: (1.0671, 0.01008), 2: (1.0656, 0.01142), 3: (1.0628, 0.01197)}
ART_A14_LVL = {1: (1.4215, 0.01567), 2: (1.4301, 0.01732), 3: (1.4264, 0.01819)}


def _historial(nombre):
    with open(os.path.join(FIXTURES, nombre)) as f:
        columnas = parse_force_lines(f, ("Time", "Cl", "Cd", "Cm"))
    return ForceHistory(columnas, [])


def _media_final(nombre, filas=500):
    """Media de Cl y Cd en las últimas `filas`, como hace el veredicto."""
    h = _historial(nombre)
    cl, cd = h.column("Cl")[-filas:], h.column("Cd")[-filas:]
    return sum(cl) / len(cl), sum(cd) / len(cd)


# --- Reproducción exacta: lo que el código da hoy, al detalle del último bit ---


@pytest.mark.parametrize("caso", sorted(REPR_EXACTA))
def test_reproduce_exacto_el_veredicto_y_los_coeficientes(caso):
    """El veredicto y Cl, Cd, Cm de la ventana, sin margen: valor exacto."""
    estado, cl, cd, cm, filas = REPR_EXACTA[caso]
    v = evaluate(_historial(f"naca0012_re6e6_{caso}.dat"))
    assert v.state == estado, v.reason
    assert v.n_rows == filas
    assert v.window == 500
    assert not v.oscila
    assert v.cl == pytest.approx(cl, rel=REL)
    assert v.cd == pytest.approx(cd, rel=REL)
    assert v.cm == pytest.approx(cm, rel=REL)


@pytest.mark.parametrize("nivel", [1, 2, 3])
def test_medias_exactas_de_los_estudios(nivel):
    """Las seis medias de los dos estudios, exactas: es la entrada del GCI."""
    for prefijo, angulo in (("a10", 10), ("a14", 14)):
        clave = f"{prefijo}_n{nivel}"
        cl, cd = _media_final(f"naca0012_re6e6_{clave}.dat")
        ref_cl, ref_cd = MEDIAS_EXACTAS[clave]
        assert cl == pytest.approx(ref_cl, rel=REL), (clave, angulo)
        assert cd == pytest.approx(ref_cd, rel=REL), (clave, angulo)


def test_gci_a10_exacto():
    """GCI del Cd a 10°: orden, extrapolado y las dos bandas, exactos.

    La distinción importa: `banda` es la del nivel 3 (±3.85 %) y `banda_media` la de la
    malla media (9.99 %), que es la que lleva la fila de la polar. Confundirlas fue un
    defecto real encontrado en la revisión del 23-nov.
    """
    s = study_from_levels([MEDIAS_EXACTAS[f"a10_n{n}"][1] for n in (1, 2, 3)])
    assert s.convergencia == "monotona"
    assert s.orden == pytest.approx(1.3086777866366501, rel=REL)
    assert s.extrapolado == pytest.approx(0.012337093412720752, rel=REL)
    assert s.banda == pytest.approx(0.00046064885845457324, rel=REL)
    assert s.banda_media == pytest.approx(0.0011410935950933471, rel=REL)
    assert s.gci_fina == pytest.approx(0.038488198001622585, rel=REL)
    assert s.gci_media == pytest.approx(0.09988373309150209, rel=REL)


def test_gci_a10_cl_no_asintotica_exacta():
    """El Cl a 10° no da orden creíble: banda de 3× el mayor salto, sin extrapolar."""
    s = study_from_levels([MEDIAS_EXACTAS[f"a10_n{n}"][0] for n in (1, 2, 3)])
    assert s.convergencia == "no asintotica"
    assert s.orden is None and s.extrapolado is None
    assert s.banda == pytest.approx(0.008389684206113301, rel=REL)


def test_gci_a14_exacto():
    """GCI a 14°: el Cl sale oscilatorio y el Cd monótono con orden 0.93."""
    cl = study_from_levels([MEDIAS_EXACTAS[f"a14_n{n}"][0] for n in (1, 2, 3)])
    assert cl.convergencia == "oscilatoria"
    assert cl.orden is None and cl.extrapolado is None
    assert cl.banda_media == pytest.approx(0.025885101359385265, rel=REL)

    cd = study_from_levels([MEDIAS_EXACTAS[f"a14_n{n}"][1] for n in (1, 2, 3)])
    assert cd.convergencia == "monotona"
    assert cd.orden == pytest.approx(0.9300251746308082, rel=REL)
    assert cd.extrapolado == pytest.approx(0.019143238561121025, rel=REL)
    assert cd.banda_media == pytest.approx(0.002278860642345853, rel=REL)


# --- Y aparte: esos valores redondeados son los que publica el artículo ---


def test_a10_redondeado_coincide_con_el_articulo():
    """10°, nivel 2: Cl 1.0656 y Cd 0.01142, las cifras del manuscrito."""
    cl, cd = _media_final("naca0012_re6e6_a10_n2.dat")
    assert round(cl, 4) == ART_A10_CL
    assert round(cd, 5) == ART_A10_CD


def test_a0_redondeado_coincide_con_el_articulo():
    """0°: Cl 0.0000 (casi nulo) y Cd 0.00784."""
    cl, cd = _media_final("naca0012_re6e6_a0_n2.dat")
    assert abs(cl) < 1e-5
    assert round(cd, 5) == ART_A0_CD


def test_niveles_de_los_estudios_redondeados_coinciden_con_el_articulo():
    """Los tres niveles de los estudios a 10° y a 14°, como se publican."""
    for nivel in (1, 2, 3):
        cl, cd = _media_final(f"naca0012_re6e6_a10_n{nivel}.dat")
        assert (round(cl, 4), round(cd, 5)) == ART_A10_LVL[nivel]
        cl, cd = _media_final(f"naca0012_re6e6_a14_n{nivel}.dat")
        assert (round(cl, 4), round(cd, 5)) == ART_A14_LVL[nivel]


def test_bandas_redondeadas_coinciden_con_el_articulo():
    """Las bandas del manuscrito: ±0.026 y ±0.0023 a 14°, y ±0.0011 en Cd a 10°."""
    cl14 = study_from_levels([MEDIAS_EXACTAS[f"a14_n{n}"][0] for n in (1, 2, 3)])
    cd14 = study_from_levels([MEDIAS_EXACTAS[f"a14_n{n}"][1] for n in (1, 2, 3)])
    assert round(cl14.banda_media, 3) == 0.026
    assert round(cd14.banda_media, 4) == 0.0023
    # Y son menores que la interpolación que sustituyen (M4a del revisor).
    assert cl14.banda_media < 0.053
    assert cd14.banda_media < 0.0031
