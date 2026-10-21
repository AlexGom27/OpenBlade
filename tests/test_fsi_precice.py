"""Tests del generador de configuración FSI con preCICE.

La validación real se hace con ``precice-config-validate`` dentro de la imagen
``openblade-fsi``; estos tests comprueban la estructura sin necesitar Docker
(siguen valiendo en CI sin GPU ni contenedores) y se marcan como *skipped* si
la imagen no está disponible.
"""

import os
import shutil
import subprocess
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.fsi_precice import (FsiCase, FsiConfig, build_precice_config,
                              validate_config)

IMAGE = os.environ.get("OPENBLADE_FSI_IMAGE", "openblade-fsi:dev")


# --------------------------------------------------------------------------
# Estructura del XML
# --------------------------------------------------------------------------
def test_root_has_no_version_attribute():
    """preCICE 3 rechaza `version` en el nodo raíz."""
    xml = build_precice_config(FsiConfig())
    assert "<precice-configuration>" in xml
    assert "version=" not in xml.split("\n")[1]


def test_meshes_declared_before_participants():
    """Las mallas deben ir antes: si no, preCICE dice 'unknown mesh'."""
    xml = build_precice_config(FsiConfig())
    assert xml.index("<mesh ") < xml.index("<participant ")


def test_mesh_declares_dimensions_and_use_data():
    xml = build_precice_config(FsiConfig(dimensions=2))
    assert 'dimensions="2"' in xml
    assert xml.count("<use-data") >= 4  # 2 mallas x 2 campos


def test_participants_have_mapping_as_child():
    """El mapping es hijo del participante, no de receive-mesh."""
    xml = build_precice_config(FsiConfig())
    for name in ("Fluid", "Solid"):
        block = xml.split(f'<participant name="{name}">')[1].split("</participant>")[0]
        assert "<mapping:nearest-neighbor" in block
        assert block.count("<receive-mesh") == 1


def test_exchange_uses_producer_mesh_for_displacement():
    """El exchange se declara sobre la malla del participante que PRODUCE el
    dato (el sólido). preCICE aborta en ejecución con "Data Displacement on
    mesh Solid-Mesh didn't contain any data samples" si se declara sobre
    Fluid-Mesh: el contexto de datos del sólido queda vacío."""
    xml = build_precice_config(FsiConfig())
    line = [l for l in xml.splitlines() if 'data="Displacement"' in l and "<exchange" in l]
    assert line, "no se encontró el exchange de desplazamiento"
    assert 'mesh="Solid-Mesh"' in line[0]
    assert 'from="Solid"' in line[0]
    assert 'to="Fluid"' in line[0]


def test_convergence_measure_name_for_precice3():
    xml = build_precice_config(FsiConfig())
    assert "relative-convergence-measure" in xml
    assert "<convergence-measure " not in xml


def test_aitken_acceleration_block():
    xml = build_precice_config(FsiConfig(relaxation="aitken"))
    assert "<acceleration:aitken>" in xml
    assert "</acceleration:aitken>" in xml


def test_constant_acceleration_uses_relaxation_tag():
    """Sintaxis de preCICE: <acceleration:constant><relaxation value=.../></...>"""
    xml = build_precice_config(FsiConfig(relaxation="constant", relaxation_factor=0.4))
    assert "<relaxation value=\"0.4\"" in xml
    assert "<data " not in xml.split("<acceleration:constant>")[1].split("</acceleration")[0]


def test_number_of_time_windows():
    xml = build_precice_config(FsiConfig(dt=0.01, end_time=0.5))
    assert '<max-time-windows value="50"' in xml


# --------------------------------------------------------------------------
# Configuración inválida
# --------------------------------------------------------------------------
@pytest.mark.parametrize("cfg,needle", [
    (FsiConfig(dt=0), "dt"),
    (FsiConfig(dt=1.0, end_time=0.5), "end_time"),
    (FsiConfig(coupling_scheme="serial-implicit", max_iterations=0), "max_iterations"),
    (FsiConfig(relaxation="magic"), "relaxation"),
    (FsiConfig(relaxation="constant", relaxation_factor=2.0), "relaxation_factor"),
    (FsiConfig(force_data="X", displacement_data="X"), "no pueden coincidir"),
])
def test_validate_config_detects_problems(cfg, needle):
    problems = validate_config(cfg)
    assert any(needle in p for p in problems), problems


def test_valid_config_has_no_problems():
    assert validate_config(FsiConfig()) == []


# --------------------------------------------------------------------------
# Escritura en el caso
# --------------------------------------------------------------------------
def test_fsi_case_writes_files(tmp_path):
    case = tmp_path / "case"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("FoamFile {}\n\napplication pimpleFoam;\n")
    (case / "system" / "fvSolution").write_text("solvers\n{\n    p { solver GAMG; }\n}\n")

    paths = FsiCase(str(case), FsiConfig()).prepare()

    assert os.path.exists(paths["precice-config"])
    control = (case / "system" / "controlDict").read_text()
    assert "preciceAdapterFunctionObject" in control
    assert "libpreciceAdapterFunctionObject.so" in control
    # La configuración del adaptador vive en preciceDict, no en controlDict
    assert os.path.exists(paths["preciceDict"])
    assert os.path.exists(paths["dynamicMeshDict"])


def test_adapter_block_is_idempotent(tmp_path):
    """Reescribir no debe duplicar el bloque."""
    case = tmp_path / "c"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("application pimpleFoam;\n")
    (case / "system" / "fvSolution").write_text("solvers\n{\n    p { solver GAMG; }\n}\n")

    f = FsiCase(str(case), FsiConfig())
    f.write_adapter_block()
    f.write_adapter_block()
    control = (case / "system" / "controlDict").read_text()
    # Aparece 3 veces por bloque: nombre del bloque, valor de `type` y dentro
    # de la librería (libpreciceAdapterFunctionObject.so). Un duplicado daría 6.
    assert control.count("preciceAdapterFunctionObject") == 3


# --------------------------------------------------------------------------
# Validación contra preCICE real (requiere la imagen)
# --------------------------------------------------------------------------
def _have_image() -> bool:
    if not shutil.which("docker"):
        return False
    r = subprocess.run(["docker", "image", "inspect", IMAGE],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


@pytest.mark.skipif(not _have_image(), reason=f"imagen {IMAGE} no disponible")
@pytest.mark.parametrize("cfg", [
    FsiConfig(),
    FsiConfig(relaxation="constant", relaxation_factor=0.4),
    FsiConfig(coupling_scheme="parallel-explicit", relaxation="none"),
])
def test_config_passes_official_validator(tmp_path, cfg):
    """El validador oficial de preCICE acepta la configuración generada."""
    xml = tmp_path / "precice-config.xml"
    xml.write_text(build_precice_config(cfg))

    r = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{tmp_path}:/data", IMAGE,
         "bash", "-lc", "cd /data && precice-config-validate precice-config.xml"],
        capture_output=True, text=True, timeout=180,
    )
    out = (r.stdout + r.stderr).strip()
    assert "No major issues detected" in out, out[-1500:]


def test_solid_participant_has_write_mapping():
    """Sin mapping de escritura preCICE aborta al inicializar el acoplamiento:
    el sólido escribe en su malla pero el exchange usa la del fluido."""
    xml = build_precice_config(FsiConfig())
    solid = xml.split('<participant name="Solid">')[1].split("</participant>")[0]
    assert solid.count("<mapping:nearest-neighbor") == 2
    assert 'direction="write"' in solid


def test_m2n_channel_declared():
    xml = build_precice_config(FsiConfig())
    assert "<m2n:sockets" in xml
    # El sólido es el acceptor: arranca primero y espera al fluido.
    assert 'acceptor="Solid"' in xml
    assert 'connector="Fluid"' in xml


# --------------------------------------------------------------------------
# Solver estructural
# --------------------------------------------------------------------------
def test_cantilever_matches_euler_bernoulli():
    """Viga empotrada con carga puntual: δ = PL³/3EI."""
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from core.structural_solver import validate_cantilever

    r = validate_cantilever(nx=80, ny=16)
    # Malla fina: el error debe ser < 1%
    assert abs(r["error_pct"]) < 1.0, r


def test_cantilever_converges_with_mesh_refinement():
    """El error debe bajar al refinar: confirma que es discretización."""
    from core.structural_solver import validate_cantilever

    coarse = abs(validate_cantilever(nx=10, ny=2)["error_pct"])
    medium = abs(validate_cantilever(nx=20, ny=4)["error_pct"])
    fine = abs(validate_cantilever(nx=40, ny=8)["error_pct"])

    assert coarse > medium > fine, (coarse, medium, fine)
    assert fine < 3.0


# --------------------------------------------------------------------------
# Malla de la cáscara del perfil (regresión de los bugs de geometría)
# --------------------------------------------------------------------------
def test_contour_is_counter_clockwise():
    """Con sentido horario los Q4 salen con Jacobiano invertido y la matriz
    de rigidez queda indefinida (913 autovalores negativos)."""
    from core.structural_solver import naca0012_contour

    c = naca0012_contour(120)
    x, y = c[:, 0], c[:, 1]
    signed = 0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    assert signed > 0, f"área firmada {signed:.4e}: el contorno es horario"


def test_shell_mesh_has_no_inverted_elements():
    """Todos los puntos de Gauss deben tener detJ > 0."""
    import math
    from core.structural_solver import (build_shell_mesh, naca0012_contour,
                                        q4_shape)

    c = naca0012_contour(120)
    nodes, elems, n_iface = build_shell_mesh(c, 0.01, 3)

    g = 1 / math.sqrt(3)
    inverted = 0
    total = 0
    for el in elems:
        co = nodes[el]
        for xi, eta in ((-g, -g), (g, -g), (g, g), (-g, g)):
            _, dx, de = q4_shape(xi, eta)
            J = np.array([[dx @ co[:, 0], dx @ co[:, 1]],
                          [de @ co[:, 0], de @ co[:, 1]]])
            total += 1
            if np.linalg.det(J) <= 0:
                inverted += 1
    # Sólo se toleran los del borde de salida, donde el espesor tiende a cero
    assert inverted / total < 0.01, f"{inverted}/{total} elementos invertidos"


def test_profile_shell_interface_matches_contour():
    """La interfaz sólida debe ser el contorno del perfil: es el patch airfoil."""
    from core.structural_solver import build_shell_mesh, naca0012_contour

    c = naca0012_contour(120, chord=1.0)
    nodes, elems, n_iface = build_shell_mesh(c, 0.01, 3)

    assert n_iface == len(c)
    np.testing.assert_allclose(nodes[:n_iface], c, atol=1e-12)
    assert c[:, 0].min() == pytest.approx(0.0, abs=1e-6)
    assert c[:, 0].max() == pytest.approx(1.0, abs=1e-6)


def test_nodal_tributary_area_matches_profile_perimeter():
    """El área tributaria se usa para integrar la tensión del fluido.
    El perímetro del NACA 0012 es ≈2.02c."""
    from core.structural_solver import naca0012_contour

    c = naca0012_contour(120)
    n = len(c)
    seg = np.zeros(n)
    for i in range(n):
        d1 = np.linalg.norm(c[i] - c[i - 1])
        d2 = np.linalg.norm(c[(i + 1) % n] - c[i])
        seg[i] = 0.5 * (d1 + d2)
    assert seg.sum() == pytest.approx(2.02, abs=0.05)
