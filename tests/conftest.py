"""Las pruebas nunca tocan los datos del usuario.

Al cerrar, la ventana limpia su caso: sin esto, `pytest` actuaba sobre
~/.openblade/openfoam_case, que puede ser un enlace a una corrida real.
"""

import os
import tempfile

os.environ["OPENBLADE_DATA_DIR"] = tempfile.mkdtemp(prefix="openblade_pruebas_")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
