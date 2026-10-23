"""Rutas de datos de OpenBlade, separadas del código.

Motivación
----------
La app escribía mallas, JSONs temporales y el caso de OpenFOAM en el directorio
de trabajo, que era la raíz del repositorio. Consecuencias:

  * el repo se ensuciaba con archivos que no son del programa;
  * GitHub recibía ruido (o había que ignorarlo a mano);
  * en Google Drive, cada simulación subía cientos de MB de resultados;
  * el sistema de archivos acumulaba handles sobre el directorio del código.

Aquí se centraliza todo lo generado bajo un único directorio de datos, fuera
del árbol del repositorio.

Jerarquía de decisión
---------------------
1. Variable de entorno ``OPENBLADE_DATA_DIR`` (útil para tests y CI).
2. ``~/.openblade`` (por defecto).

Ninguna ruta de este módulo apunta dentro del repo.
"""

from __future__ import annotations

import os

ENV_VAR = "OPENBLADE_DATA_DIR"


def data_root() -> str:
    """Directorio raíz de datos generados. Se crea si no existe."""
    root = os.environ.get(ENV_VAR) or os.path.join(os.path.expanduser("~"), ".openblade")
    os.makedirs(root, exist_ok=True)
    return root


def case_dir() -> str:
    """Caso de OpenFOAM de la simulación en curso."""
    d = os.path.join(data_root(), "openfoam_case")
    os.makedirs(d, exist_ok=True)
    return d


def mesh_path(naca: str = "0012") -> str:
    """Malla del perfil. `naca` puede ser '0012' o 'custom'."""
    d = os.path.join(data_root(), "meshes")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"perfil_{naca}.msh")


def temp_path(name: str) -> str:
    """Archivo temporal (params json, vtk de previsualización)."""
    d = os.path.join(data_root(), "tmp")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def results_dir() -> str:
    """Salidas de validación, vídeos, informes."""
    d = os.path.join(data_root(), "results")
    os.makedirs(d, exist_ok=True)
    return d


def describe() -> dict:
    """Resumen legible, para el log de arranque."""
    return {
        "raiz": data_root(),
        "caso": case_dir(),
        "mallas": os.path.join(data_root(), "meshes"),
        "temporales": os.path.join(data_root(), "tmp"),
        "resultados": results_dir(),
    }
