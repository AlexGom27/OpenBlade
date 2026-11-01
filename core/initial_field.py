"""Arrancar un caso desde el resultado de otro con la misma malla.

Un transitorio que arranca del flujo potencial tarda varias cuerdas de recorrido en dejar
atras el arranque impulsivo: a 18 grados, Cl pasa de 0.6 a 1.04 en 1.5 cuerdas. Desde el
campo estacionario ese tramo no existe. Solo se copia el interior de los campos: las
condiciones de contorno son las que escribio el programa para este caso.
"""

from __future__ import annotations

import os
import re
from typing import Optional

from core.package import read_ficha, sha256_file

_INTERIOR = re.compile(r"^internalField\s.*?;", re.S | re.M)


def latest_fields(case_dir: str) -> Optional[str]:
    """Carpeta del ultimo tiempo con campos, sin contar el inicial."""
    tiempos = []
    for nombre in os.listdir(case_dir):
        try:
            t = float(nombre)
        except ValueError:
            continue
        if t > 0 and os.path.exists(os.path.join(case_dir, nombre, "U")):
            tiempos.append((t, nombre))
    return os.path.join(case_dir, max(tiempos)[1]) if tiempos else None


def start_from(origen: str, case_dir: str, msh_file: str) -> str:
    """Pasa a 0/ el interior de los campos de otra corrida. Devuelve de que tiempo salieron."""
    ficha = read_ficha(origen) or {}
    if ficha.get("archivos", {}).get("mesh.msh") != sha256_file(msh_file):
        raise ValueError(f"El campo inicial de {origen} es de otra malla")
    tiempo = latest_fields(origen)
    if tiempo is None:
        raise ValueError(f"{origen} no tiene campos de los que arrancar")
    destino = os.path.join(case_dir, "0")
    for campo in sorted(os.listdir(destino)):
        ruta = os.path.join(destino, campo)
        fuente = os.path.join(tiempo, campo)
        if not os.path.isfile(ruta):
            continue
        if not os.path.exists(fuente):
            raise ValueError(f"{origen} no tiene el campo {campo}: ¿es otro modelo de turbulencia?")
        with open(fuente, errors="replace") as f:
            hallado = _INTERIOR.search(f.read())
        with open(ruta) as f:
            texto = f.read()
        if hallado is None or _INTERIOR.search(texto) is None:
            raise ValueError(f"No se encontró internalField en {campo}")
        with open(ruta, "w") as f:
            f.write(_INTERIOR.sub(lambda _: hallado.group(0), texto, count=1))
    return os.path.basename(tiempo)
