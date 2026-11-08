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


def test_a_coarser_field_is_expanded_cell_by_cell_on_the_nested_mesh():
    import numpy as np
    from core.cgrid import cells_of_level, generate_cgrid, naca4
    from core.initial_field import _expand

    assert cells_of_level(2) == (448, 128) and cells_of_level(1) == (224, 64)

    def rejilla(nivel):
        x, y = generate_cgrid(naca4("0012"), 5e-6, nivel, 50.0)
        def centro(v):
            return 0.25 * (v[:-1, :-1] + v[1:, :-1] + v[:-1, 1:] + v[1:, 1:])
        diagonal = np.hypot(x[1:, 1:] - x[:-1, :-1], y[1:, 1:] - y[:-1, :-1])
        return centro(x).flatten(order="F"), centro(y).flatten(order="F"), diagonal.flatten(order="F")

    def expandida(valores):
        interior = ("internalField   nonuniform List<scalar> \n%d\n(\n" % valores.size
                    + "\n".join(repr(float(v)) for v in valores) + "\n)\n;")
        salida = _expand(interior, 2).split("\n")
        assert salida[1] == str(4 * valores.size) and salida[2] == "(" and salida[-2:] == [")", ";"]
        return np.array([float(v) for v in salida[3:-2]])

    xg, yg, dg = rejilla(1)
    xf, yf, _ = rejilla(2)
    # El centro de cada celda fina cae dentro de la gruesa de la que toma el valor
    distancia = np.hypot(expandida(xg) - xf, expandida(yg) - yf)
    assert (distancia <= expandida(dg)).all()


def test_expand_refuses_a_field_of_another_size():
    from core.initial_field import _expand
    with pytest.raises(ValueError, match="celdas"):
        _expand("internalField   nonuniform List<scalar> \n2\n(\n1\n2\n)\n;", 2)
    assert _expand("internalField   uniform 0;", 2) == "internalField   uniform 0;"


def test_a_coarser_field_with_chord_refinement_is_expanded_too():
    """Estudio de malla con la cuerda refinada: el nivel 1 x4 tiene 4 veces mas celdas a lo largo."""
    from core.cgrid import cells_of_level, generate_cgrid, naca4
    from core.initial_field import _expand
    assert cells_of_level(1, 2) == (896, 64) and cells_of_level(2, 2) == (1792, 128)
    x, _ = generate_cgrid(naca4("0012"), 5e-6, 1, 50.0, refinar_cuerda=2)
    assert (x.shape[0] - 1, x.shape[1] - 1) == cells_of_level(1, 2)
    n = 896 * 64
    interior = ("internalField   nonuniform List<scalar> \n%d\n(\n" % n + "\n".join("1" for _ in range(n))
                + "\n)\n;")
    assert _expand(interior, 2, 2).split("\n")[1] == str(4 * n)
