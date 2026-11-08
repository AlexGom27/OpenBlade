"""Las pruebas nunca tocan los datos del usuario.

Al cerrar, la ventana limpia su caso: sin esto, `pytest` actuaba sobre
~/.openblade/openfoam_case, que puede ser un enlace a una corrida real.
"""

import os
import tempfile

import pytest

os.environ["OPENBLADE_DATA_DIR"] = tempfile.mkdtemp(prefix="openblade_pruebas_")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def sin_campanas_ajenas(monkeypatch):
    """Apaga `hay_cli_vivo` y devuelve la de verdad.

    `owner.hay_cli_vivo()` mira los procesos del sistema: con una campana real
    corriendo, las mismas pruebas darian otro resultado. Quien necesite simular una,
    o probar esta funcion, recibe la autentica como valor del fixture.
    """
    from core import owner

    real = owner.hay_cli_vivo
    monkeypatch.setattr(owner, "hay_cli_vivo", lambda: False)
    return real


@pytest.fixture(scope="session", autouse=True)
def _datos_de_prueba_en_tmp():
    """El programa escribe en OPENBLADE_DATA_DIR, y en las pruebas eso es un tmp.

    Los 12 trabajos `c0..c5` que aparecieron en ~/.openblade/jobs los dejo una
    sonda suelta que corrio fuera de pytest; dentro de pytest la regla se puede
    comprobar, y aqui se comprueba en cada prueba: nada cae en el directorio real.
    """
    from core import paths

    raiz = os.path.realpath(paths.data_root())
    assert raiz.startswith(os.path.realpath(tempfile.gettempdir())), raiz
    assert raiz != os.path.realpath(os.path.expanduser("~/.openblade")), raiz
    yield raiz
