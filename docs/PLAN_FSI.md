# Plan de incorporación de FSI 2D a OpenBlade

**Fecha**: 2026-10-21
**Estado**: propuesta, pendiente de aprobación de alcance

---

## 1. Qué significa "FSI" en este contexto

"Fluido–estructura" abarca tres cosas muy distintas en coste y en valor. Conviene
elegir antes de escribir código, porque el nivel 1 y el nivel 3 no comparten
arquitectura.

| Nivel | Qué modela | Acoplamiento | Esfuerzo | ¿Encaja hoy? |
|---|---|---|---|---|
| **1. Aeroelasticidad de cuerpo rígido** | El perfil se mueve como sólido rígido (2–3 GDL) sobre resortes y amortiguadores. Malla dinámica. | Bidireccional, resuelto dentro del solver | 1–2 días | **Sí, nativo** |
| **2. FSI particionado con sólido elástico** | El perfil (o un flap) se deforma según elasticidad lineal. Dos solvers alternando. | Bidireccional por intercambio de campos | 1–2 semanas | Sí, con código de acoplamiento propio |
| **3. FSI con preCICE** | Acoplamiento genérico, mallas no coincidentes, esquemas de acoplamiento avanzados | Particionado con biblioteca externa | 1–2 meses | **No**: hay que construir imagen propia |

El nivel 1 es el que da resultado visible rápido y el que responde preguntas
reales de ingeniería (flutter, respuesta en frecuencia, amortiguamiento
aerodinámico). El nivel 2 es el que hace falta si se quiere estudiar
deformación de una placa o un flap flexible.

---

## 2. Lo que el entorno ya permite (verificado en la imagen)

Comprobado ejecutando comandos dentro de `opencfd/openfoam-default:latest`
(OpenFOAM v2512):

| Componente | Estado | Evidencia |
|---|---|---|
| `libsixDoFRigidBodyMotion.so` | ✅ presente | biblioteca del solver de cuerpo rígido |
| `librigidBodyMeshMotion.so` | ✅ presente | malla dinámica por cuerpos rígidos |
| `libfvMotionSolvers.so` | ✅ presente | `displacementLaplacian`, `velocityLaplacian` |
| `pimpleFoam` | ✅ presente | solver transitorio |
| Tutorial `wingMotion2D_pimpleFoam` | ✅ presente | perfil alar con resortes, exactamente el patrón |
| `solidDisplacementFoam` | ✅ presente | solver estructural |
| `planeStress yes` | ✅ presente | elasticidad 2D validada en `plateHole` |
| **preCICE** | ❌ ausente | no hay `python3` en la imagen; habría que construirla |
| `solidDisplacementFoam` 2D | ✅ `planeStress yes` | verificado en `plateHole` |
| `interpolationSchemes` para `pointDisplacement` | ✅ soportado | requerido por la malla dinámica |

Conclusión: **el nivel 1 se puede hacer sin tocar la imagen**. El nivel 2 se
puede hacer escribiendo el acoplamiento en Python. El nivel 3 queda fuera salvo
que se acepte mantener una imagen propia.

---

## 3. Nivel 1 — Aeroelasticidad de cuerpo rígido (recomendado)

### 3.1 Física

El perfil se trata como sólido rígido con dos grados de libertad:

- **Heave** (`h`): desplazamiento vertical, restringido a la línea `y`.
- **Pitch** (`α`): giro alrededor del eje elástico, restringido al eje `z`.

Cada GDL lleva resorte lineal y amortiguador. Las ecuaciones que resuelve
OpenFOAM son:

```
m·ḧ + c_h·ḣ + k_h·h = F_y(t)
I·α̈ + c_α·α̇ + k_α·α = M_z(t)
```

donde `F_y` y `M_z` los calcula el propio solver a partir de la presión y el
esfuerzo viscoso sobre el parche del perfil, en cada paso de tiempo.

Esto **no es una aproximación de una vía**: el movimiento modifica el campo de
flujo en el mismo paso de tiempo, y el campo modificado cambia las fuerzas. Es
FSI bidireccional real, sólo que la estructura se idealiza como rígida.

### 3.2 Diccionarios que hay que generar

**`constant/dynamicMeshDict`**

Las claves son **planas** (sin bloque `sixDoFRigidBodyMotionCoeffs`), como en el
tutorial oficial `wingMotion2D_pimpleFoam` verificado en la imagen:

```cpp
dynamicFvMesh   dynamicMotionSolverFvMesh;
motionSolverLibs (sixDoFRigidBodyMotion);
motionSolver    sixDoFRigidBodyMotion;

updateControl   timeStep;
updateInterval  1;

patches         (airfoil);
innerDistance   0.3;        // zona que se traslada rígida
outerDistance   1.0;        // límite de la zona deformable

mass            22.9;       // kg (tutorial)
centreOfMass    (0.4975 -0.0167 0.05);
momentOfInertia (1.9589 3.9208 2.0571);
orientation
(
     0.9953705935  0.09611129781 0
    -0.09611129781 0.9953705935  0
     0              0             1
);
angularMomentum (0 0 -2);
g               (0 -9.81 0);
rho             rhoInf;
rhoInf          1;
report          on;

constraints
{
    yAxis   { sixDoFRigidBodyMotionConstraint line; axis (0 1 0); }
    zAxis   { sixDoFRigidBodyMotionConstraint axis; axis (0 0 1); }
}

    restraints
    {
        heaveSpring
        {
            sixDoFRigidBodyMotionRestraint linearSpring;
            anchor          (0.25 0 0.05);
            refAttachmentPt (0.25 0 0.05);
            stiffness       <k_h>;
            damping         <c_h>;
            restLength      0;
        }
        pitchSpring
        {
            sixDoFRigidBodyMotionRestraint linearAxialAngularSpring;
            axis            (0 0 1);
            stiffness       <k_alpha>;
            damping         <c_alpha>;
            referenceOrientation (1 0 0 0 1 0 0 0 1);
        }
    }
}
```

Los valores marcados con `<...>` los introduce el usuario en la GUI.

**`0/pointDisplacement`** — campo nuevo, obligatorio para malla dinámica:

```cpp
dimensions      [0 1 0 0 0 0 0];
internalField   uniform (0 0 0);
boundaryField
{
    airfoil         { type calculated; value uniform (0 0 0); }
    inlet           { type fixedValue; value uniform (0 0 0); }
    outlet          { type fixedValue; value uniform (0 0 0); }
    farfield        { type fixedValue; value uniform (0 0 0); }
    frontAndBack    { type empty; }
}
```

**`system/controlDict`** — la simulación pasa a transitoria:

```
application     pimpleFoam;
endTime         5;          // tutorial
deltaT          1e-5;       // tutorial
adjustTimeStep  yes;
maxCo           0.9;        // más estricto que en flujo fijo: la malla se mueve
```

Verificado en la imagen: el tutorial arranca con `deltaT 1e-5`, `maxCo 0.9` y
`endTime 5`. Para FSI conviene `maxCo ≤ 1` porque el movimiento de malla añade
error al término convectivo.

**`system/fvSchemes`** — obligatorio `Euler` en `ddtSchemes` y
`pointInterpolation` en `interpolationSchemes` para el campo de desplazamiento.

### 3.3 Arquitectura en el código

Módulo nuevo **`core/fsi_setup.py`**:

```python
class FsiSetup:
    """Escribe los diccionarios de malla dinámica y cuerpo rígido."""
    def __init__(self, case_dir: str) -> None: ...
    def write_dynamic_mesh_dict(self, patches, centre, mass, inertia,
                                k_heave, c_heave, k_pitch, c_pitch,
                                inner_distance, outer_distance) -> None: ...
    def write_point_displacement(self) -> None: ...
    def enable_transient(self, delta_t, end_time, max_co) -> None: ...
```

Módulo nuevo **`core/fsi_post.py`**:

```python
class FsiPostProcessor:
    """Extrae la historia temporal del movimiento y de las fuerzas."""
    def read_body_motion(self) -> dict      # de postProcessing/sixDoFRigidBodyState
    def read_forces(self) -> dict           # de postProcessing/forceCoeffs
    def damping_ratio(self) -> float        # ajuste exponencial del decaimiento
    def flutter_speed(self, runs) -> float  # de un barrido de U_inf
```

Reutilización directa: `core/mesh_script.py`, `core/solver.py` (ya acepta
`algo_name="pimpleFoam"`) y `core/postprocessing.py` no cambian.

### 3.4 Fases

| # | Entregable | Criterio de terminado |
|---|---|---|
| 1 | `FsiSetup` escribe los tres diccionarios | El caso arranca con `pimpleFoam` y el perfil se mueve |
| 2 | Reproducir el tutorial `wingMotion2D` con los mismos parámetros | Amplitud y frecuencia coinciden con el tutorial (±5%) |
| 3 | Caso de oscilación libre en aire en reposo | El decaimiento reproduce `ω_n = √(k/m)` y el amortiguamiento pedido |
| 4 | Caso en corriente con amortiguamiento negativo | Se detecta el cruce a flutter al subir `U_inf` |
| 5 | GUI: pestaña FSI con masa, inercia, resortes, amortiguamientos | Se puede lanzar sin tocar archivos |
| 6 | Post-proceso: gráfica h(t), α(t), y envolvente de flutter | Figura en el informe PDF |

### 3.5 Advertencia técnica importante

La malla actual (y⁺ ≈ 0.04, 30 capas, celdas de 2×10⁻⁵ contra 0.006) **no es
buena para malla dinámica**. Las celdas de capa límite con relación de aspecto
300:1 se distorsionan con el movimiento y el solver pierde precisión o diverge.

Para FSI hay que usar una malla distinta:

- Menos capas de capa límite (10–15) y primera celda más gruesa, aceptando
  y⁺ ≈ 30–100 con función de pared.
- O bien una **zona rígida** alrededor del perfil (`innerDistance`) que se
  traslada sin deformarse, y la deformación confinada al anillo exterior.

El tutorial `wingMotion` usa precisamente la segunda estrategia. Es la que
recomiendo.

---

## 4. Nivel 2 — FSI particionado con sólido elástico

### 4.1 Idea

Dos mallas distintas (fluido y sólido), dos solvers, acoplamiento por
intercambio de campos en cada paso de tiempo:

```
para cada paso t:
    1. CFD resuelve el fluido con la geometría actual
    2. extraer presión sobre la interfaz
    3. aplicar presión como carga al sólido (solidDisplacementFoam)
    4. extraer desplazamiento de la interfaz
    5. mover la malla del fluido según ese desplazamiento
    6. comprobar convergencia del acoplamiento; si no, iterar 2–5
```

Sin preCICE hay que implementar los pasos 2–6 en Python.

### 4.2 Lo que hay que construir

- **`core/structural_setup.py`**: escribe el caso sólido (malla del perfil como
  dominio, `mechanicalProperties` con `E`, `nu`, `planeStress yes`, condiciones
  de empotramiento en el borde de ataque).
- **`core/fsi_coupling.py`**: el bucle escalonado. Interpolación de presión
  fluido→sólido y de desplazamiento sólido→fluido sobre la interfaz. Como en 2D
  las mallas del perfil son la misma curva, basta interpolación 1D por
  longitud de arco; no hace falta proyección 3D.
- **`core/mesh_morph.py`**: aplicar el desplazamiento a la malla del fluido.
  Dos opciones: `displacementLaplacian` con difusividad, o mover los puntos
  directamente con `pointDisplacement` fijo por paso.

### 4.3 Sub-pasos y estabilidad

El acoplamiento escalonado explícito es inestable cuando la relación
densidad-sólido/densidad-fluido es alta (el "added mass effect"). Para un
perfil delgado en agua esto rompe; en aire es manejable. Hay que:

- Sub-relajar el desplazamiento transferido (Aitken o factor fijo 0.5).
- Iterar hasta que el cambio de desplazamiento en la interfaz < 1e-6.
- Limitar a 3–5 iteraciones de acoplamiento por paso.

### 4.4 Fases

| # | Entregable | Criterio |
|---|---|---|
| 1 | Caso sólido aislado: placa empotrada con carga | Flecha coincide con `FL³/3EI` |
| 2 | Acoplamiento 1 vía: presión CFD → sólido | Deformación estática razonable |
| 3 | Acoplamiento 2 vías con sub-relajación | Converge en <5 iteraciones por paso |
| 4 | Benchmark Turek & Hron (2D, canal con obstáculo elástico) | Comparar con la fuente primaria |

El benchmark de Turek & Hron es el estándar de facto para FSI 2D. Antes de
usarlo hay que descargar el artículo y transcribir los valores de referencia;
no se deben citar de memoria.

---

## 5. Nivel 3 — preCICE (fuera de alcance propuesto)

Requeriría:

- Construir imagen propia con preCICE compilado contra OpenFOAM v2512.
- Mantener el adaptador `openfoam-adapter` versionado.
- Añadir Python 3 a la imagen (hoy no lo tiene).

Coste estimado: 3–6 semanas sólo de infraestructura, más el mantenimiento.
No lo recomiendo salvo que el objetivo sea publicar con acoplamiento
particionado avanzado.

---

## 6. Cambios por archivo (nivel 1)

| Archivo | Cambio |
|---|---|
| `core/fsi_setup.py` | **nuevo** — diccionarios de malla dinámica y cuerpo rígido |
| `core/fsi_post.py` | **nuevo** — historia temporal, amortiguamiento, flutter |
| `core/openfoam_setup.py` | `create_case()` gana el flag `dynamic_mesh`; escribe `pointDisplacement` |
| `core/solve_script.py` | acepta `simulation_type="fsi"` y usa `pimpleFoam` |
| `gui/input_panel.py` | sección colapsable "FSI / Aeroelasticidad": masa, inercia, resortes, amortiguamientos, zona deformable |
| `gui/workers.py` | `FsiWorker` (hilo) que lanza el pipeline completo |
| `gui/main_window.py` | botón "Análisis FSI", conecta señales |
| `gui/plots.py` | `FsiPlot`: h(t), α(t), plano de fases |
| `core/report_generator.py` | sección FSI en el PDF |
| `tests/test_fsi_setup.py` | **nuevo** — los diccionarios son válidos y OpenFOAM los lee |

Nada de lo existente se rompe: el flujo actual (`simpleFoam`) queda como está
y FSI es una ruta paralela.

---

## 7. Validación propuesta

Antes de dar por buena la funcionalidad hay que pasar tres pruebas, en orden:

1. **Reproducir el tutorial `wingMotion2D_pimpleFoam`** con sus parámetros
   exactos. Si no coincide, algo está mal en los diccionarios generados.
2. **Oscilación libre en aire quieto**: se desplaza el perfil y se suelta.
   La frecuencia debe dar `f = (1/2π)√(k/m)` y el decaimiento debe corresponder
   al amortiguamiento pedido. Esto valida la parte estructural sin contaminación
   aerodinámica.
3. **Barrido de velocidad → flutter**: subir `U_inf` hasta que el amortiguamiento
   efectivo cambie de signo. Comparar la velocidad crítica con la teoría
   bidimensional de Theodorsen (fuente a transcribir, no de memoria).

Sólo después de esas tres se puede afirmar que la implementación es correcta.

---

## 8. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Malla actual inadecuada para movimiento | Alto | Malla específica FSI con zona rígida interior |
| Celdas de capa límite se invierten al deformarse | Alto | `displacementLaplacian` con difusividad `quadratic inverseDistance`; limitar amplitud |
| Inestabilidad del acoplamiento (nivel 2) | Medio | Sub-relajación + iteraciones de acoplamiento |
| Coste computacional | Medio | 2D y pocos ciclos; empezar con `maxCo 1` y malla gruesa |
| Confundir FSI rígido con FSI elástico | Medio | Nombrar la funcionalidad "aeroelasticidad de cuerpo rígido", no "FSI" a secas |

---

## 8-bis. Estado de la implementación (nivel 3, 2026-10-21)

Decisión del usuario: **nivel 3 (preCICE)** por ser para investigación.

### Imagen construida y verificada

`docker/Dockerfile.openblade-fsi` construye sobre `opencfd/openfoam-default` y añade:

| Componente | Versión | Verificación |
|---|---|---|
| preCICE | 3.4.1 | `/usr/local/lib/libprecice.so.3.4.1` |
| openfoam-adapter | v1.4.0 | `libpreciceAdapterFunctionObject.so`, `ldd` resuelve `libprecice` |
| Python 3 | 3.12 | disponible en la imagen |

**Hallazgo importante**: preCICE publica `.deb` sólo para **amd64**. En Apple
Silicon (arm64) no existe binario, así que la imagen compila preCICE desde
fuente. El Dockerfile lo hace siempre para ser reproducible en ambas
arquitecturas. Tiempo de build: ~13 min (con caché de dependencias, ~1 min).

### Código

`core/fsi_precice.py`:

- `FsiConfig` — dataclass con todos los parámetros del acoplamiento.
- `build_precice_config()` — genera el XML. Se escribe como **texto**, no con
  ElementTree: preCICE usa tags con `:` (`data:vector`, `m2n:sockets`,
  `coupling-scheme:serial-implicit`) que expat interpreta como prefijos de
  namespace y rechaza.
- `FsiCase` — escribe `precice-config.xml` e inserta el functionObject del
  adaptador en `controlDict` de forma idempotente.
- `validate_config()` — comprobaciones de coherencia.

### Validación realizada

1. `precice-config-validate` (validador oficial) → **"No major issues detected"**
   para las tres variantes: aitken, constant y parallel-explicit.
2. **Acoplamiento real ejecutado**: dos `solverdummy` de C++ intercambiaron
   datos durante 3 ventanas de tiempo con `m2n:sockets` y cerraron limpiamente.
3. 23 tests unitarios + 3 que invocan el validador dentro de la imagen.

### Errores corregidos durante la implementación

Todos encontrados ejecutando, no leyendo documentación:

| Síntoma | Causa real |
|---|---|
| `unbound prefix` al parsear | tags con `:` no son XML válido para expat |
| `unknown attribute "version"` | preCICE 3 ya no lo acepta en el nodo raíz |
| `unknown mesh` | las `<mesh>` deben declararse antes de los `<participant>` |
| `missing attribute "dimensions"` | obligatorio en preCICE 3 |
| `unknown tag api-access` | eliminado en preCICE 3 |
| `missing attribute "from"` | `<receive-mesh>` lo requiere |
| `unknown tag convergence-measure` | en v3 es `relative-convergence-measure` |
| `data not exchanged over mesh` | el exchange de desplazamiento debe usar la malla del fluido |
| `unknown attribute "value"` en acceleration | la sintaxis es `<relaxation value="..."/>` |
| `data doesn't contain any samples` (runtime) | falta el mapping de **escritura** del sólido |

Ese último sólo apareció al ejecutar el acoplamiento de verdad; el validador
estático no lo detecta.

### Pendiente

- El solver **estructural** no está implementado. `solidDisplacementFoam` está
  en la imagen, pero el acoplamiento sólido↔preCICE requiere escribir el bucle
  de intercambio en el lado del sólido (o usar un solver Python con los
  bindings).
- El adaptador OpenFOAM exige malla dinámica con `pointDisplacement`; falta
  conectarlo con la ruta FSI del GUI.
- Falta el benchmark de Turek & Hron para validación cuantitativa.

## 9. Recomendación

**Empezar por el nivel 1.** Es lo que el software puede hacer hoy sin
infraestructura nueva, cubre los casos de aeroelasticidad que se suelen querer
(flutter, respuesta dinámica, amortiguamiento), y su resultado es verificable
contra un tutorial oficial de OpenFOAM.

Si el objetivo docente o de investigación exige deformación elástica real,
el nivel 2 es viable pero requiere implementar el acoplamiento, y conviene
planificarlo como proyecto aparte.

---

## 10. Decisión pendiente

1. ¿Nivel 1, nivel 2, o ambos por fases?
2. ¿El interés es docencia (que el alumno vea el fenómeno) o investigación
   (publicar comparación con benchmarks)?
3. ¿Se acepta una malla específica para FSI, distinta de la de la validación
   actual?
