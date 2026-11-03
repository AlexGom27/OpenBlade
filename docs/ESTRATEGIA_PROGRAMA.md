# Estrategia: OpenBlade como programa confiable

Fecha: 2026-10-31. Acordada entre Claude y OpenClaw, a partir de la propuesta de Alejandro. Reemplaza la ruta de `docs/ANALISIS_E1_Y_RUTA.md` §3 (retirado del árbol; está en la etiqueta `archivo-2026-11-03`).
M = medido; H = hipótesis. OpenClaw reprodujo las tablas de §2 y §3 por su cuenta, con las columnas leídas por nombre.

## 1. Objetivo y regla

El proyecto principal es el programa, operativo y confiable para estudiantes, academia, investigación y empresas.

**Regla:** toda simulación sale del programa. La Mac genera la malla y el caso con OpenBlade y organiza el trabajo. Los servidores solo calculan el paquete de OpenFOAM que reciben. Quedan fuera los scripts con sus propios diccionarios o su propia lectura de fuerzas.

La propuesta es factible. Enviar el paquete desde la Mac elimina la discrepancia entre servidores.

## 2. Qué se demostró

**Flujo real (M).** Desde la ventana en la Mac: Servidor, Probar conexión, Generar Malla, Iniciar Análisis. Subió, calculó en `openblade2`, descargó y actualizó Cl/Cd y Cp. Tras bloquearse la pantalla, las demás corridas usaron el mismo `RemoteSimWorker` sin ventana.

**Mismo paquete en ambos servidores (M).** Misma malla (md5 `bbe77172`), 4 procesos, 500 iteraciones: 501 de 501 filas de `forceCoeffs` idénticas; `polyMesh` y diccionarios idénticos. Ambos servidores tienen la misma CPU y el mismo build de OpenFOAM 12, así que esto demuestra que el flujo conserva el caso, no que el resultado sea correcto ni que sea portable a otra máquina.

**Causa de la discrepancia anterior (M).** `openblade` tiene un parche manual en `gmshairfoil2d/geometry_def.py` que no está en `openblade2`, en la Mac ni en el repo. Con los mismos parámetros, generar la malla en cada servidor daba 44 145 y 24 885 celdas.

**Dos paquetes distintos a la vez (M).** α=0 en `openblade2` y α=8 en `openblade`, cada uno con su carpeta de datos. Funciona, pero hoy requiere una ventana o proceso por trabajo.

## 3. Qué devuelve hoy el programa

Malla por defecto del programa (58 608 celdas), Re=6e6, 6000 iteraciones, 8 procesos.

| Caso | Entrada | Cl | Cd | Frente a Ladson 80 |
|---|---|---|---|---|
| α=0 | I=5 % fija (hoy) | 0.000 | 0.01204 | Cd +49 % |
| α=0 | Tu=0.052 %, νt/ν=0.009 | 0.000 | 0.00776 (rango 0.12 %) | Cd −3.7 % |
| α=8 | I=5 % fija (hoy) | de −897 a +728 | negativo en 3873 de 6001 filas | Diverge; termina con rc=0 |
| α=8 | Tu=0.052 %, νt/ν=0.009 | 0.9345 (rango 0.04 %) | 0.01061 (rango 0.82 %) | Cl +8.8 %, Cd +8.4 % |

- **Valores por defecto (M):** α=8 a Re=1e6 también diverge (Cl de −958 a +500, rc=0). Con 500 iteraciones, α=0 a Re=1e6 da Cd=0.0212 aún bajando, y la ventana muestra «Simulación finalizada (Código 0)» sin aviso.
- **Causa medida:** k y ω de entrada fijos en `core/openfoam_setup.py:407-412` (νt/ν≈14 000, frente a 0.009 de TMR). Es la única variable que cambia entre esos pares de casos.
- **Fricción con la entrada corregida (M):** a α=0, Cf pasa de 5.65e-3 en x/c 0.01-0.03 a 1.57e-3 al final, sin el salto de E1.
- **Sin validar:** son dos ángulos en una sola malla, sin GCI. El +9 % de Cl a α=8 aparece también en E1 con otra malla. H: dominio de 50c o esquemas; se discrimina en E5.

### Ley de pared y y+
- `nutLowReWallFunction` y `nutkWallFunction` con y+<11 dan ambos nut de pared = 0, por lo que sus fuerzas salen idénticas (M). La prueba no demuestra que la ley de pared sea irrelevante: falta un caso con y+>30.
- El y+ que escribe OpenFOAM depende de la condición: `nutkWallFunction` usa k en la celda (`.C:126`, medio 0.205) y `nutLowReWallFunction` usa la fricción real (`.C:94`, medio 2.46). El programa debe calcular su propio y+ con u_τ.

## 4. Defectos del programa

| Defecto | Dónde | Fase |
|---|---|---|
| Lectores de fuerzas separados, por posición de columna | `gui/workers.py:420-429`, `core/remote_runner.py` y scripts sueltos | E0 |
| Sin veredicto de convergencia ni divergencia; toma la última fila | `gui/main_window.py:645`, `coeficientes_finales` | E3 |
| y+ sin definición única ni comprobación de régimen | no existe | E3 |
| Turbulencia de entrada fija e invisible | `core/openfoam_setup.py:407` | E2 |
| `bl_dist_min`, `depth` y `momentum_scheme` no llegan al caso desde la GUI, así que lo validado por scripts no era lo que corre la GUI | `core/solve_script.py:12-26` | E2 |
| La rueda del ratón cambia valores numéricos al desplazar el panel (AoA pasó de 0 a 1) | `gui/input_panel.py` | E2 |
| Progreso en estacionario: «t = 500 de 0.5 s (100000 %)» | `gui/main_window.py:576-595` | E2 |
| `nb_airfoil_pts` depende de un parche externo, se ignora en silencio y la GUI no lo envía | `core/mesh_script.py:164-169` | E2 |
| Paquete sin verificación de integridad ni ficha; versiones sin fijar | `core/remote_runner.py`, `requirements.txt` | E1 |
| `estado()` da «running» si `status.json` no se puede leer | `core/remote_runner.py` | E1 |
| Dos lanzamientos en el mismo segundo comparten carpeta: uno se pierde y ambos terminan con rc=0 (medido) | `RemoteJob.__init__` | E4 |
| Una ventana lleva un solo trabajo; `case_dir` y `remote_job.json` son únicos | `core/paths.py:38-42`, `gui/main_window.py:391` | E4 |
| Local usa `opencfd/openfoam-default` sin versión (ESI); los servidores usan OpenFOAM 12 (Foundation). Nunca comparados | `core/solver.py:7` | E4/E5 |

## 5. Fases, en orden

| Fase | Entrega | Criterio de salida | Estimación |
|---|---|---|---|
| **E0** | Un solo lector de fuerzas, con columnas por nombre, para GUI, remoto, informe y `validation/` | Si falta una columna, falla; no adivina | 2 h |
| **E3** | Veredicto CONVERGIDO, NO CONVERGIDO o DIVERGIDO, con media ± amplitud, en GUI y PDF; y+ propio con u_τ y aviso si la malla no corresponde | α=8 divergente se muestra como DIVERGIDO y α=0 de 500 iteraciones como NO CONVERGIDO | 4 h |
| **E2** | Tu y νt/ν como parámetros visibles (`k=1.5(U·Tu)²`, `ω=k/(νt/ν·ν)`), por defecto 0.052 % y 0.009; `bl_dist_min` y demás llegan al caso; rueda y progreso corregidos | Control α=0 pasa la física; α=8 ya no diverge | 1 día |
| **E1** | Ficha por caso (sha256 de malla y diccionarios, versiones, parámetros, y+, checkMesh) verificada en el servidor antes de calcular; versiones fijadas; parche integrado al repo | Un paquete alterado se rechaza | 1 día |
| **E4** | Carpeta única por trabajo y panel que reparte paquetes entre Local y N servidores; Local con OpenFOAM 12 fijado | Dos trabajos → dos carpetas → dos resultados, desde una sola ventana | 2-3 días |
| **E5** | Banco de validación dentro del programa, con informe: NACA 0012 frente a TMR y Ladson; prueba de dominio 40c frente a 200c; mallas oficiales TMR | Tolerancias publicadas y cumplidas o declaradas | 3-5 días |
| **E6** | Campaña en paquetes: polar, GCI y URANS donde RANS no converja | Polar con incertidumbre | según E5 |

Las estimaciones son de OpenClaw. La física se ataca después de que el programa diga la verdad sobre lo que calcula. Una ficha que certifica un caso con la entrada incorrecta no aporta confiabilidad, por eso E1 va después de E3 y E2.

## 6. Reparto

**Trabajo**
- **Claude:** edita el repo, usa OpenBlade en la Mac y anuncia cada entrega con su commit y el número que debe cambiar.
- **OpenClaw:** no edita el repo. Regenera el caso de control desde cero en ambos servidores, publica una tabla antes/después y ataca lo entregado.
- **Alejandro:** decide alcance y prioridades.

**Máquinas**
| Máquina | Papel | Procesos |
|---|---|---|
| Mac | GUI, malla, ficha, lectura de resultados | gmsh |
| `openblade` | Cálculo principal | 10 |
| `openblade2` | Cálculo secundario y caso de control | 8 |

## 7. Caso de control de cada entrega

NACA 0012, cuerda 1, Re=6e6, α=0, valores por defecto de la GUI, 6000 iteraciones, 8 procesos, un cálculo en cada servidor.

| # | Compuerta | Tolerancia |
|---|---|---|
| 1 | md5 de `mesh.msh` igual en Mac y ambos servidores | exacto |
| 2 | md5 de `forceCoeffs.dat` igual entre servidores | exacto, mientras CPU y build sean iguales |
| 3 | `Cl` y `Cd` leídos por nombre | si faltan, falla |
| 4 | Rango de Cd en las últimas 500 iteraciones | < 1 % |
| 5 | \|Cl\| > 2 en toda la corrida, o algún Cd < 0 en esa misma ventana | falla |
| 6 | Cd frente a Ladson 80 grit | ±5 % |
| 7 | \|Cl\| a α=0 | < 0.01 |
| 8 | y+ con u_τ, calculado por el programa, igual entre servidores | ±1 % |

Si fallan 1 o 2, se arregla el flujo antes de discutir física. Cuando α=0 pase, se añade α=8: Cl y Cd frente a Ladson 80 grit ±10 %, rango < 1 %. Esas tolerancias detectan errores gruesos; no certifican precisión.

Hoy el control pasa 1-5 y 7, y falla 6 (+49 %). La compuerta 8 no se puede evaluar hasta E3.

## 8. Estado de la ejecución (2026-11-01)

| Fase | Estado | Commit |
|---|---|---|
| E0 | Hecha | `bcb814a` |
| E3 | Hecha | `b263b60` |
| E2 | Hecha | `1472da2` |
| E1 | Hecha | `ed7aac8` |
| E4 | Hecha | `c2317cb` |
| E5 | Hecha: banco, malla propia, tolerancias declaradas | `c7ff71c` en adelante |
| E6 | Hecha en estacionario: polar con banda de malla. URANS no validado a Re alto | `04cf1b3` en adelante |

Los resultados, con sus tolerancias y lo que no cumplen, están en [VALIDACION.md](VALIDACION.md). El caso de control con la malla nueva pasa: fuerzas idénticas byte a byte en los dos servidores. Las tablas de §2 y §3 son de antes de corregir `writePrecision` y la tolerancia del solver lineal: solo explican cómo se llegó aquí.

**Abierto**
- Transitorio a Re alto con y+<1: Courant 30 revienta y Courant 10 da fuerzas ruidosas con la capa límite desarrollada. Falta probar relajación y más correctores externos.
- `core/openfoam_setup.py` sigue con un cambio ajeno sin subir (PIMPLE: `nOuterCorrectors 2`, `outerCorrectorResidualControl`). Las pruebas de transitorio se hicieron con él. Decide Alejandro.
- La cola vive en la Mac. Con la tapa cerrada no se envía lo pendiente; se retoma con `polar --continuar` o al abrir la ventana.
