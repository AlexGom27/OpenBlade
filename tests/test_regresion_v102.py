"""Regresión con las cifras de referencia de v1.0.2 (bb27cca).

Los fixtures son las últimas filas de historiales de fuerzas reales de la campaña de
bb27cca, no historias sintéticas: si el lector, el veredicto, la ventana o el GCI
cambian, estas pruebas lo delatan.

Origen (OpenBlade_proyecto/trabajos_v1.0.2_bb27cca), polar limpia `_tiempo2`
del 23-nov, sola en los dos servidores:

  naca0012_re6e6_a0_n2.dat    20261123_113010_gci_a0_n2_afcd
  naca0012_re6e6_a10_n1.dat   20261123_113010_gci_a10_n1_e68e
  naca0012_re6e6_a10_n2.dat   20261123_113010_gci_a10_n2_c25e
  naca0012_re6e6_a10_n3.dat   20261123_113010_gci_a10_n3_94ec

Las cifras de referencia están en docs/VALIDACION.md, §4 y §6.
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

# Nivel 2, NACA 0012 Re=6e6, de docs/VALIDACION.md §4.
REF_A10_CL = 1.0656
REF_A10_CD = 0.01142
REF_A0_CD = 0.00784
# Estudio de malla a 10°, §6: nivel 1, 2 y 3.
REF_A10_CD_N1 = 0.01008
REF_A10_CD_N2 = 0.01142
REF_A10_CD_N3 = 0.01197
REF_A10_CL_N1 = 1.0671
REF_A10_CL_N2 = 1.0656
REF_A10_CL_N3 = 1.0628


def _historial(nombre):
    with open(os.path.join(FIXTURES, nombre)) as f:
        columnas = parse_force_lines(f, ("Time", "Cl", "Cd", "Cm"))
    return ForceHistory(columnas, [])


def _media_final(historial, filas=500):
    """Media de Cl y Cd en las últimas `filas`, como hace el veredicto."""
    cl, cd = historial.column("Cl")[-filas:], historial.column("Cd")[-filas:]
    return sum(cl) / len(cl), sum(cd) / len(cd)


def test_a10_nivel2_veredicto_y_coeficientes():
    """10°, nivel 2: CONVERGIDO con el Cl y el Cd del artículo."""
    v = evaluate(_historial("naca0012_re6e6_a10_n2.dat"))
    assert v.state == CONVERGIDO, v.reason
    assert not v.oscila
    # Tolerancia de reproducción: la media de la ventana no depende del recorte.
    assert v.cl == pytest.approx(REF_A10_CL, abs=1e-3)
    assert v.cd == pytest.approx(REF_A10_CD, abs=1e-4)


def test_a0_nivel2_cd_del_articulo():
    """0°: Cl nulo y Cd 0.00784."""
    v = evaluate(_historial("naca0012_re6e6_a0_n2.dat"))
    assert v.state == CONVERGIDO, v.reason
    assert v.cd == pytest.approx(REF_A0_CD, abs=1e-4)
    assert abs(v.cl) < 1e-3


def test_estudio_de_malla_a10_reproduce_los_tres_niveles():
    """Los tres niveles del estudio a 10° dan las cifras de la tabla de §6."""
    medias = {}
    for nivel in (1, 2, 3):
        cl, cd = _media_final(_historial(f"naca0012_re6e6_a10_n{nivel}.dat"))
        medias[nivel] = (cl, cd)
    assert medias[1][1] == pytest.approx(REF_A10_CD_N1, abs=1e-4)
    assert medias[2][1] == pytest.approx(REF_A10_CD_N2, abs=1e-4)
    assert medias[3][1] == pytest.approx(REF_A10_CD_N3, abs=1e-4)
    assert medias[1][0] == pytest.approx(REF_A10_CL_N1, abs=1e-3)
    assert medias[2][0] == pytest.approx(REF_A10_CL_N2, abs=1e-3)
    assert medias[3][0] == pytest.approx(REF_A10_CL_N3, abs=1e-3)

def test_gci_a10_cd_da_orden_extrapolado_y_dos_bandas():
    """El GCI del Cd a 10°: orden 1.30, extrapolado 0.01234 y las dos bandas.

    Importa la distinción: `banda` es la del nivel 3 (±3.86 %) y `banda_media` la de la
    malla media (10.01 %), que es la que lleva la fila de la polar. Confundirlas fue un
    hallazgo de la revisión del 23-nov.
    """
    # Las cifras medidas, no las redondeadas del documento: el orden y el extrapolado
    # dependen de la tercera cifra significativa de la diferencia entre niveles.
    _, cd1 = _media_final(_historial("naca0012_re6e6_a10_n1.dat"))
    _, cd2 = _media_final(_historial("naca0012_re6e6_a10_n2.dat"))
    _, cd3 = _media_final(_historial("naca0012_re6e6_a10_n3.dat"))
    s = study_from_levels([cd1, cd2, cd3])
    assert s.convergencia == "monotona"
    assert s.orden == pytest.approx(1.30, abs=0.02)
    assert s.extrapolado == pytest.approx(0.01234, abs=1e-5)
    assert s.banda == pytest.approx(0.000462, abs=5e-6)
    assert s.banda_media == pytest.approx(0.001144, abs=1e-5)
    assert s.gci_fina == pytest.approx(0.0386, abs=0.0005)
    assert s.gci_media == pytest.approx(0.1001, abs=0.001)


def test_gci_a10_cl_no_es_asintotica():
    """El Cl a 10° no da orden creíble: banda de 3× el mayor salto, sin extrapolar."""
    s = study_from_levels([REF_A10_CL_N1, REF_A10_CL_N2, REF_A10_CL_N3])
    assert s.convergencia == "no asintotica"
    assert s.orden is None and s.extrapolado is None
    # 3 × max(|1.0656-1.0671|, |1.0628-1.0656|) = 3 × 0.0028
    assert s.banda == pytest.approx(0.0084, abs=1e-6)


def test_estudio_a14_banda_menor_que_la_interpolada():
    """El estudio a 14° (M4a del revisor): la banda medida es menor que la interpolada.

    Antes de tener el estudio se interpolaba entre 10° y 15°, lo que daba ±0.053 en Cl y
    ±0.0031 en Cd. El estudio propio da la mitad en Cl, así que la interpolación era
    conservadora y la fila de 14° deja de ser interpolada.
    """
    medias = {}
    for nivel in (1, 2, 3):
        cl, cd = _media_final(_historial(f"naca0012_re6e6_a14_n{nivel}.dat"))
        medias[nivel] = (cl, cd)
    assert medias[2][0] == pytest.approx(1.4301, abs=1e-3)
    assert medias[2][1] == pytest.approx(0.017320, abs=1e-4)

    cl_study = study_from_levels([medias[n][0] for n in (1, 2, 3)])
    cd_study = study_from_levels([medias[n][1] for n in (1, 2, 3)])

    # Cl sale oscilatorio: la banda es 3x el mayor salto, sin extrapolar.
    assert cl_study.convergencia == "oscilatoria"
    assert cl_study.banda_media == pytest.approx(0.026, abs=1e-3)
    assert cl_study.banda_media < 0.053        # menos que la interpolada

    # Cd es monotono con orden cercano a 1 y extrapolado 0.01914.
    assert cd_study.convergencia == "monotona"
    assert cd_study.orden == pytest.approx(0.93, abs=0.02)
    assert cd_study.extrapolado == pytest.approx(0.01914, abs=1e-4)
    assert cd_study.banda_media == pytest.approx(0.00228, abs=5e-5)
    assert cd_study.banda_media < 0.0031       # menos que la interpolada
