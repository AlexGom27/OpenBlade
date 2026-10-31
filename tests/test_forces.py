"""El lector de fuerzas lee por nombre de columna y nunca adivina."""

import glob
import os
import re
import sys

import pytest

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, RAIZ)

from core.forces import (ForceDataError, final_coefficients, parse_force_lines,
                         read_forces, tail_statistics)

OF12 = ("# Force coefficients\n# magUInf     : 1.5e+01\n"
        "# Time\tCm\tCd\tCl\tCl(f)\tCl(r)\n")
ESI = "# Time\tCd\tCd(f)\tCd(r)\tCl\tCl(f)\tCl(r)\tCmPitch\tCmRoll\tCmYaw\n"


def _caso(tmp_path, tiempo="0", nombre="forceCoeffs.dat", texto=""):
    d = tmp_path / "postProcessing" / "forceCoeffs" / tiempo
    d.mkdir(parents=True, exist_ok=True)
    (d / nombre).write_text(texto)
    return str(tmp_path)


def test_openfoam12_columns_are_read_by_name(tmp_path):
    caso = _caso(tmp_path, texto=OF12 + "1 0.1 0.2 0.3 0.4 0.5\n2 0.05 0.012 0.8 0.5 0.3\n")
    assert final_coefficients(caso) == (0.8, 0.012, 0.05)


def test_esi_columns_are_read_by_name(tmp_path):
    caso = _caso(tmp_path, nombre="coefficient.dat",
                 texto=ESI + "7 0.012 0.1 0.2 0.8 0.5 0.3 0.05 0.6 0.7\n")
    assert final_coefficients(caso) == (0.8, 0.012, 0.05)


def test_lift_fractions_are_never_taken_for_lift(tmp_path):
    caso = _caso(tmp_path, texto=OF12 + "1 0.0 0.012 0.8 0.11 0.69\n")
    assert read_forces(caso).cl == [0.8]


@pytest.mark.parametrize("cabecera", [
    "# Time Cm Cd Cl(f) Cl(r)\n",
    "# Time Cd Cl\n",
    "",
])
def test_missing_column_or_header_fails(tmp_path, cabecera):
    ancho = len(cabecera.split()) - 1 or 6
    caso = _caso(tmp_path, texto=cabecera + " ".join(["1"] * ancho) + "\n")
    with pytest.raises(ForceDataError):
        read_forces(caso)


def test_no_results_fails(tmp_path):
    with pytest.raises(ForceDataError):
        final_coefficients(str(tmp_path))


def test_row_with_other_width_fails_but_last_incomplete_row_is_ignored():
    filas = OF12.splitlines() + ["1 0.1 0.2 0.3 0.4 0.5\n"]
    assert parse_force_lines(filas + ["2 0.1 0.2\n"])["Time"] == [1.0]
    with pytest.raises(ForceDataError):
        parse_force_lines(filas + ["2 0.1 0.2\n", "3 0.1 0.2 0.3 0.4 0.5\n"])


def test_nan_is_kept_so_that_divergence_can_be_seen():
    columnas = parse_force_lines(OF12.splitlines() + ["1 nan nan -nan 0 0\n"])
    assert columnas["Cl"][0] != columnas["Cl"][0]


def test_restarts_are_joined_in_time_order_and_the_latest_wins(tmp_path):
    caso = _caso(tmp_path, "0", texto=OF12 + "".join(
        f"{t} 0 {t}.5 1 0 0\n" for t in (1, 2, 3)))
    _caso(tmp_path, "10", texto=OF12 + "11 0 9 1 0 0\n")
    _caso(tmp_path, "2.5", texto=OF12 + "3 0 7 1 0 0\n4 0 8 1 0 0\n")
    h = read_forces(caso)
    assert h.time == [1, 2, 3, 4, 11]
    assert h.cd == [1.5, 2.5, 7, 8, 9]


def test_tail_statistics(tmp_path):
    assert tail_statistics(str(tmp_path)) is None
    caso = _caso(tmp_path, texto=OF12 + "".join(
        f"{t} 0 {0.1 if t > 8 else 9} 1 0 0\n" for t in range(10)))
    assert tail_statistics(caso, 0.5, minimo=20) is None
    s = tail_statistics(caso, 0.9, minimo=5)
    assert (s["n"], s["cd"], s["cl"], s["cd_std"]) == (1, 0.1, 1.0, 0.0)


def test_nobody_else_reads_the_force_file():
    """Otro lector por posicion volveria a confundir Cl(f) con Cl."""
    patron = re.compile(r"postProcessing.{0,10}forceCoeffs|coefficient\.dat|forceCoeffs\.dat")
    ajenos = []
    for carpeta in ("core", "gui", "validation", "tools"):
        for ruta in glob.glob(os.path.join(RAIZ, carpeta, "*.py")):
            if os.path.basename(ruta) == "forces.py":
                continue
            with open(ruta, encoding="utf-8") as f:
                if patron.search(f.read()):
                    ajenos.append(os.path.relpath(ruta, RAIZ))
    assert ajenos == []
