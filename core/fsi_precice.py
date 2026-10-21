"""Soporte FSI particionado con preCICE para OpenBlade 2D.

Arquitectura
------------
OpenFOAM resuelve el fluido; un solver estructural resuelve el sólido. Ambos se
comunican a través de preCICE, que se encarga de la interpolación entre mallas
y del esquema de acoplamiento.

Este módulo NO implementa el solver estructural. Genera:

  * ``precice-config.xml`` — el acoplamiento (participantes, mallas, datos,
    esquema, criterios de convergencia y de parada).
  * El bloque ``preciceAdapterFunctionObject`` dentro de ``controlDict`` para
    que OpenFOAM hable con preCICE.

El sólido se resuelve aparte. Para el caso de investigación se asume un sólido
lineal-elástico 2D (``solidDisplacementFoam`` con ``planeStress yes``) o un
solver Python (FEniCS / calculix / propio) que use los bindings de preCICE.

Referencias
-----------
Los nombres de malla, datos y esquema siguen la convención del adaptador
oficial (precice/openfoam-adapter v1.4.0) y de los tutoriales de preCICE 3.x.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from xml.dom import minidom


# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------
@dataclass
class FsiConfig:
    """Parámetros del acoplamiento fluido-estructura.

    Los valores por defecto corresponden a un caso 2D de perfil alar en agua
    o aire, acoplamiento serial implícito con sub-relajación de Aitken.
    """

    # Nombres de los participantes (deben coincidir con los usados en cada solver)
    fluid_participant: str = "Fluid"
    solid_participant: str = "Solid"

    # Nombres de malla en preCICE
    fluid_mesh: str = "Fluid-Mesh"
    solid_mesh: str = "Solid-Mesh"

    # Campo que el fluido envía al sólido y viceversa
    force_data: str = "Stress"
    displacement_data: str = "Displacement"

    # Interfaz en el lado del fluido (nombre del parche OpenFOAM)
    interface_patch: str = "airfoil"

    # Dimensión del problema: 2 para los casos 2D de OpenBlade
    dimensions: int = 2

    # Tiempo
    dt: float = 1e-3
    end_time: float = 1.0

    # Acoplamiento
    coupling_scheme: str = "serial-implicit"
    max_iterations: int = 50
    relaxation: str = "aitken"        # "aitken" | "constant" | "none"
    relaxation_factor: float = 0.5    # solo si relaxation="constant"
    convergence_measure: str = "relative-residual"
    convergence_limit: float = 1e-4

    # Interpolación entre mallas no coincidentes
    mapping_method: str = "nearest-neighbor"
    # Alternativas: "rbf-thin-plate-splines", "rbf-gaussian", "nearest-projection"

    # Salida
    exchange_directory: str = "precice-run"
    export_vtk: bool = False


# --------------------------------------------------------------------------
# Generación del XML
# --------------------------------------------------------------------------
def _sub(parent: ET.Element, tag: str, **attrs) -> ET.Element:
    """Crea un subelemento con atributos y lo añade a parent.

    Nota: los tags con ':' (p. ej. ``coupling-scheme:serial-implicit``) no son
    válidos para ``ET.SubElement``, que los interpreta como prefijo de namespace.
    Se crean con ``makeelement`` para evitarlo.
    """
    # Solo se traduce el sufijo '_' final (from_ -> from), NO los guiones bajos
    # internos: 'from_' debe quedar 'from', no 'from-'.
    clean = {}
    for k, v in attrs.items():
        key = k[:-1] if k.endswith("_") else k.replace("_", "-")
        clean[key] = str(v)
    el = parent.makeelement(tag, clean)
    parent.append(el)
    return el


def build_precice_config(cfg: FsiConfig) -> str:
    """Construye el XML de configuración de preCICE 3.x.

    Se genera como texto y no con ElementTree/minidom porque preCICE usa tags
    con dos puntos (``data:vector``, ``mapping:nearest-neighbor``, ``m2n:sockets``,
    ``coupling-scheme:serial-implicit``) que expat interpreta como prefijos de
    namespace y rechaza. preCICE sí los acepta.

    La estructura sigue el ejemplo oficial distribuido con preCICE
    (``share/precice/examples/solverdummies/precice-config.xml``).
    """
    d = cfg.dimensions
    L = []
    a = L.append

    a('<?xml version="1.0" encoding="UTF-8" ?>')
    a("<precice-configuration>")

    # --- Log ---------------------------------------------------------------
    a("  <log>")
    a('    <sink type="stream" output="stdout" filter="%Severity% > debug"'
      ' enabled="true" />')
    a("  </log>")
    a("")

    # --- Datos -------------------------------------------------------------
    a(f'  <data:vector name="{cfg.force_data}" />')
    a(f'  <data:vector name="{cfg.displacement_data}" />')
    a("")

    # --- Mallas ------------------------------------------------------------
    for mesh_name in (cfg.fluid_mesh, cfg.solid_mesh):
        a(f'  <mesh name="{mesh_name}" dimensions="{d}">')
        a(f'    <use-data name="{cfg.force_data}" />')
        a(f'    <use-data name="{cfg.displacement_data}" />')
        a("  </mesh>")
    a("")

    # --- Participantes -----------------------------------------------------
    a(f'  <participant name="{cfg.fluid_participant}">')
    a(f'    <provide-mesh name="{cfg.fluid_mesh}" />')
    a(f'    <receive-mesh name="{cfg.solid_mesh}" from="{cfg.solid_participant}" />')
    a(f'    <mapping:nearest-neighbor direction="read" from="{cfg.solid_mesh}"'
      f' to="{cfg.fluid_mesh}" constraint="consistent" />')
    a(f'    <write-data name="{cfg.force_data}" mesh="{cfg.fluid_mesh}" />')
    a(f'    <read-data name="{cfg.displacement_data}" mesh="{cfg.fluid_mesh}" />')
    a("  </participant>")
    a("")

    # El sólido escribe el desplazamiento en SU malla, pero el exchange lo
    # declara sobre la malla del fluido: hace falta un mapping de escritura
    # explícito. Sin él, preCICE aborta con
    # "Data ... on mesh Fluid-Mesh doesn't contain any samples".
    a(f'  <participant name="{cfg.solid_participant}">')
    a(f'    <provide-mesh name="{cfg.solid_mesh}" />')
    a(f'    <receive-mesh name="{cfg.fluid_mesh}" from="{cfg.fluid_participant}" />')
    a(f'    <mapping:nearest-neighbor direction="read" from="{cfg.fluid_mesh}"'
      f' to="{cfg.solid_mesh}" constraint="consistent" />')
    a(f'    <mapping:nearest-neighbor direction="write" from="{cfg.solid_mesh}"'
      f' to="{cfg.fluid_mesh}" constraint="consistent" />')
    a(f'    <write-data name="{cfg.displacement_data}" mesh="{cfg.solid_mesh}" />')
    a(f'    <read-data name="{cfg.force_data}" mesh="{cfg.solid_mesh}" />')
    a("  </participant>")
    a("")

    # --- Comunicación ------------------------------------------------------
    a(f'  <m2n:sockets acceptor="{cfg.fluid_participant}"'
      f' connector="{cfg.solid_participant}" />')
    a("")

    # --- Esquema de acoplamiento -------------------------------------------
    a(f'  <coupling-scheme:{cfg.coupling_scheme}>')
    a(f'    <participants first="{cfg.fluid_participant}"'
      f' second="{cfg.solid_participant}" />')
    a(f'    <time-window-size value="{cfg.dt}" />')
    n_windows = max(1, int(round(cfg.end_time / cfg.dt)))
    a(f'    <max-time-windows value="{n_windows}" />')

    if cfg.coupling_scheme == "serial-implicit":
        a(f'    <max-iterations value="{cfg.max_iterations}" />')
        if cfg.relaxation == "aitken":
            a('    <acceleration:aitken>')
            a(f'      <data name="{cfg.displacement_data}"'
              f' mesh="{cfg.solid_mesh}" />')
            a("    </acceleration:aitken>")
        elif cfg.relaxation == "constant":
            # Sintaxis verificada en los tests de preCICE:
            #   <acceleration:constant><relaxation value="0.5" /></acceleration:constant>
            a("    <acceleration:constant>")
            a(f'      <relaxation value="{cfg.relaxation_factor}" />')
            a("    </acceleration:constant>")
        # En preCICE 3 el tag se llama relative-convergence-measure
        a(f'    <relative-convergence-measure limit="{cfg.convergence_limit}"'
          f' data="{cfg.displacement_data}" mesh="{cfg.solid_mesh}" />')

    a(f'    <exchange data="{cfg.force_data}" mesh="{cfg.fluid_mesh}"'
      f' from="{cfg.fluid_participant}" to="{cfg.solid_participant}"'
      f' initialize="true" />')
    # El exchange se declara sobre la malla del participante que PRODUCE el
    # dato: el desplazamiento lo escribe el sólido en Solid-Mesh. Declararlo
    # sobre Fluid-Mesh hace que preCICE aborte al arrancar con
    # "Data Displacement on mesh Solid-Mesh didn't contain any data samples".
    # La transferencia a la malla del fluido la hace el mapping de escritura
    # del sólido; el fluido lo lee en su propia malla.
    a(f'    <exchange data="{cfg.displacement_data}" mesh="{cfg.solid_mesh}"'
      f' from="{cfg.solid_participant}" to="{cfg.fluid_participant}"'
      f' initialize="true" />')
    a(f"  </coupling-scheme:{cfg.coupling_scheme}>")
    a("</precice-configuration>")
    a("")
    return "\n".join(L)


# --------------------------------------------------------------------------
# Escritura
# --------------------------------------------------------------------------
class FsiCase:
    """Escribe los archivos FSI dentro de un caso OpenFOAM existente."""

    def __init__(self, case_dir: str, cfg: Optional[FsiConfig] = None) -> None:
        self.case_dir = case_dir
        self.cfg = cfg or FsiConfig()

    def write_precice_config(self) -> str:
        path = os.path.join(self.case_dir, "precice-config.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(build_precice_config(self.cfg))
        return path

    def write_adapter_block(self) -> str:
        """Inserta el functionObject del adaptador en system/controlDict.

        Idempotente: si el bloque ya existe, lo reemplaza.
        """
        control = os.path.join(self.case_dir, "system", "controlDict")
        with open(control) as f:
            text = f.read()

        block = self._adapter_block()
        # Reemplazar el bloque previo si existe (idempotente). Se busca la
        # aparición como NOMBRE de bloque (con llave a continuación), no la
        # del campo `type`, que también contiene el mismo texto.
        while True:
            new_text = self._remove_function_object(text, "preciceAdapterFunctionObject")
            if new_text == text:
                break
            text = new_text

        if "functions" not in text:
            text = text.rstrip() + "\n\nfunctions\n{\n" + block + "}\n"
        else:
            idx = text.index("functions")
            brace = text.index("{", idx)
            text = text[:brace + 1] + "\n" + block + text[brace + 1:]

        with open(control, "w") as f:
            f.write(text)
        return control

    def _adapter_block(self) -> str:
        cfg = self.cfg
        return f"""
    preciceAdapterFunctionObject
    {{
        type            preciceAdapterFunctionObject;
        libs            ("libpreciceAdapterFunctionObject.so");

        // Nombre del participante tal como aparece en precice-config.xml
        participant     {cfg.fluid_participant};

        // Parche de la interfaz fluido-estructura
        interfaces
        {{
            {cfg.interface_patch}
            {{
                patches         ({cfg.interface_patch});
                // El fluido ENVÍA fuerza y RECIBE desplazamiento
                writeData       ({cfg.force_data});
                readData        ({cfg.displacement_data});
            }}
        }}

        // Malla dinámica: el desplazamiento que llega de preCICE se aplica al
        // campo pointDisplacement, no al movimiento de cuerpo rígido.
        moveMeshOuterCorrectors  true;
    }}
"""

    @staticmethod
    def _remove_function_object(text: str, name: str) -> str:
        """Elimina un bloque functionObject por nombre, respetando llaves."""
        key = text.find(name)
        if key < 0:
            return text
        brace = text.find("{", key)
        if brace < 0:
            return text
        depth = 0
        i = brace
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        start = text.rfind("\n", 0, key)
        return text[:start] + text[i + 1:]

    def prepare(self) -> Dict[str, str]:
        """Escribe todos los archivos FSI. Devuelve las rutas generadas."""
        return {
            "precice-config": self.write_precice_config(),
            "controlDict": self.write_adapter_block(),
        }


# --------------------------------------------------------------------------
# Validación de la configuración
# --------------------------------------------------------------------------
def validate_config(cfg: FsiConfig) -> List[str]:
    """Comprueba coherencia. Devuelve lista de problemas (vacía si todo bien)."""
    problems: List[str] = []

    if cfg.dt <= 0:
        problems.append("dt debe ser > 0")
    if cfg.end_time <= cfg.dt:
        problems.append("end_time debe ser mayor que dt")
    if cfg.coupling_scheme == "serial-implicit" and cfg.max_iterations < 1:
        problems.append("max_iterations debe ser >= 1 en serial-implicit")
    if cfg.relaxation not in ("aitken", "constant", "none"):
        problems.append(f"relaxation desconocido: {cfg.relaxation}")
    if cfg.relaxation == "constant" and not (0 < cfg.relaxation_factor <= 1):
        problems.append("relaxation_factor debe estar en (0, 1]")
    if cfg.force_data == cfg.displacement_data:
        problems.append("force_data y displacement_data no pueden coincidir")
    if cfg.fluid_participant == cfg.solid_participant:
        problems.append("los participantes deben tener nombres distintos")

    return problems
