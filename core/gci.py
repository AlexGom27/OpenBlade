"""Incertidumbre de malla con el indice de convergencia de malla (GCI, Roache).

Con tres niveles anidados de factor 2 se estima el orden observado, el valor
extrapolado y la banda de error del nivel mas fino. Es el procedimiento habitual
(Celik et al., J. Fluids Eng. 130, 2008), con el factor de seguridad 1.25.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Sequence

FACTOR_SEGURIDAD = 1.25
ORDEN_MIN = 0.5
ORDEN_MAX = 2.0
FACTOR_MALLA = 2.0


@dataclass
class GridStudy:
    fina: float
    media: float
    gruesa: float
    convergencia: str       # "monotona", "oscilatoria", "no asintotica" o "sin cambio"
    orden: Optional[float]
    extrapolado: Optional[float]
    gci_fina: float         # banda relativa sobre el valor de la malla fina
    banda: float            # la misma banda, absoluta
    gci_media: float = 0.0  # banda relativa si el resultado que se usa es el de la malla media
    banda_media: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def grid_study(fina: float, media: float, gruesa: float, r: float = FACTOR_MALLA) -> GridStudy:
    """GCI de un coeficiente. fina, media y gruesa son los valores de los tres niveles."""
    e21 = media - fina
    e32 = gruesa - media
    referencia = abs(fina) if abs(fina) > 1e-12 else max(abs(media), abs(gruesa), 1e-12)
    if abs(e21) < 1e-12 and abs(e32) < 1e-12:
        return GridStudy(fina, media, gruesa, "sin cambio", None, fina, 0.0, 0.0)
    cociente = e32 / e21 if e21 != 0.0 else math.inf
    if cociente <= 0.0 or not math.isfinite(cociente):
        # El signo cambia entre niveles: no hay orden que estimar. Se usa el mayor
        # salto entre niveles con un factor de seguridad de 3 (Roache), sin extrapolar.
        banda = 3.0 * max(abs(e21), abs(e32))
        relativa = banda / referencia
        return GridStudy(fina, media, gruesa, "oscilatoria", None, None, relativa, banda, relativa, banda)
    orden = math.log(cociente) / math.log(r)
    if orden < ORDEN_MIN:
        # La malla fina casi no mejora a la media: no se esta en el rango asintotico y
        # extrapolar daria una banda demasiado estrecha. Se trata como la oscilatoria.
        banda = 3.0 * max(abs(e21), abs(e32))
        relativa = banda / referencia
        return GridStudy(fina, media, gruesa, "no asintotica", None, None, relativa, banda, relativa, banda)
    # Un orden mayor del que puede dar el esquema no se cree: se acota, y la banda crece.
    orden = min(orden, ORDEN_MAX)
    extrapolado = fina + (fina - media) / (r ** orden - 1.0)
    banda = FACTOR_SEGURIDAD * abs(e21) / (r ** orden - 1.0)
    # La malla media dista del valor extrapolado lo que distan entre si las dos mas
    # gruesas, con el mismo orden: es la banda de una polar calculada en la media.
    banda_media = FACTOR_SEGURIDAD * abs(e32) / (r ** orden - 1.0)
    ref_media = abs(media) if abs(media) > 1e-12 else referencia
    return GridStudy(fina, media, gruesa, "monotona", orden, extrapolado, banda / referencia, banda,
                     banda_media / ref_media, banda_media)


def study_from_levels(valores: Sequence[float]) -> GridStudy:
    """Los valores van del nivel mas grueso al mas fino; se usan los tres ultimos."""
    if len(valores) < 3:
        raise ValueError("El GCI necesita tres niveles de malla")
    return grid_study(valores[-1], valores[-2], valores[-3])
