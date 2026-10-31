"""Arrancar un caso desde el resultado de otro con la misma malla."""

import json
import os

import pytest

from core.initial_field import latest_fields, start_from
from core.package import sha256_file

CAMPO = """FoamFile {{ class vol{tipo}Field; object {nombre}; }}
dimensions [0 1 -1 0 0 0 0];
internalField   {interior};
boundaryField
{{
    inlet {{ type fixedValue; value {valor}; }}
}}
"""


def _campo(ruta, nombre, interior, valor="uniform 1"):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w") as f:
        f.write(CAMPO.format(tipo="Scalar", nombre=nombre, interior=interior, valor=valor))


@pytest.fixture
def casos(tmp_path):
    malla = tmp_path / "m.msh"
    malla.write_text("malla")
    origen, destino = tmp_path / "origen", tmp_path / "destino"
    for nombre in ("U", "p"):
        _campo(str(origen / "0" / nombre), nombre, "uniform 0", "uniform 99")
        _campo(str(origen / "500" / nombre), nombre, "nonuniform List<scalar> 2(1.5\n2.5)", "uniform 99")
        _campo(str(destino / "0" / nombre), nombre, "uniform 0", "uniform 1")
    with open(origen / "ficha.json", "w") as f:
        json.dump({"archivos": {"mesh.msh": sha256_file(str(malla))}}, f)
    return str(origen), str(destino), str(malla)


def test_only_the_inside_of_the_fields_is_copied(casos):
    origen, destino, malla = casos
    assert start_from(origen, destino, malla) == "500"
    texto = open(os.path.join(destino, "0", "U")).read()
    assert "nonuniform List<scalar> 2(1.5\n2.5)" in texto
    # La condicion de contorno es la de este caso, no la del de origen
    assert "uniform 1" in texto and "uniform 99" not in texto


def test_another_mesh_is_refused(casos, tmp_path):
    origen, destino, _ = casos
    otra = tmp_path / "otra.msh"
    otra.write_text("otra malla")
    with pytest.raises(ValueError, match="otra malla"):
        start_from(origen, destino, str(otra))


def test_another_turbulence_model_is_refused(casos):
    origen, destino, malla = casos
    _campo(os.path.join(destino, "0", "omega"), "omega", "uniform 0")
    with pytest.raises(ValueError, match="omega"):
        start_from(origen, destino, malla)


def test_a_run_without_results_is_refused(casos, tmp_path):
    origen, destino, malla = casos
    vacio = tmp_path / "vacio"
    _campo(str(vacio / "0" / "U"), "U", "uniform 0")
    assert latest_fields(str(vacio)) is None
    with open(vacio / "ficha.json", "w") as f:
        f.write(open(os.path.join(origen, "ficha.json")).read())
    with pytest.raises(ValueError, match="no tiene campos"):
        start_from(str(vacio), destino, malla)


def test_the_package_records_that_it_skips_the_potential_flow(tmp_path):
    from core.defaults import case_params
    p = case_params(campo_inicial="/algo")
    assert p["campo_inicial"] == "/algo"
    fuente = open(os.path.join(os.path.dirname(__file__), "..", "core", "remote_job.py")).read()
    assert 'job.get("sin_potencial")' in fuente
