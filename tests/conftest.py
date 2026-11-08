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
