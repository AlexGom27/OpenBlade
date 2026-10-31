> **Superado (2026-10-31).** Estas corridas no sirven como validación del programa. Se hicieron con los puntos de la malla redondeados a 6 cifras y con k y ω congelados por la tolerancia del solver lineal, y muchas con scripts que escribían sus propios casos. Ver [docs/VALIDACION.md](VALIDACION.md).

# Análisis de E1 y V1, y ruta de simulaciones

Fecha: 2026-10-31. Elaborado por Claude y OpenClaw, cada uno con su análisis independiente y dos rondas de contraste.
M = medido; H = hipótesis. Ningún cálculo de esta ruta se ha lanzado todavía.

> **Actualización:** la ruta de §3 quedó reemplazada por `docs/ESTRATEGIA_PROGRAMA.md`. Las cifras del A/B de `6a19db0` son del arranque (iteraciones 57-121), no de estado.

## 1. Resultado de la campaña

| α | Cl E1 | Cl Ladson 80 | Cd E1 | Cd Ladson 80 | Cd base (I=5 %) | Rango Cd E1 |
|---|---|---|---|---|---|---|
| 0 | 0.0012 | - | 0.00706 | 0.00806 | 0.00803 | 3.8 % |
| 4 | 0.4734 | 0.4272 | 0.00725 | 0.00823 | 0.00839 | 6.6 % |
| 8 | 0.9358 | 0.8593 | 0.00784 | 0.00979 | 0.01050 | 18.1 % |
| 10 | 1.1562 | 1.0586 | 0.01014 | 0.01191 | 0.01292 | 5.1 % |

- Ningún caso E1 cumple el criterio de convergencia por fuerzas (M).
- Los dos controles de pared cayeron por SIGFPE en las iteraciones 29 y 34 (M).
- V1 a α=8 llegó a Cl = 2.96 en t = 0.133 s y se detuvo desde fuera tras ~21.6 h, sin causa registrada. V2 a V5 nunca arrancaron (M).
- El `V1_trans_a8` con `ok=true` de `resultados.json` es falso y no debe usarse (M).

## 2. Diagnóstico

### 2.1 El Cd bajo y el Cl alto de E1 son un artefacto de pared
- **M:** en `nutkWallFunctionFvPatchScalarField.C:62-66`, y+ se calcula con k de la celda de pared; por debajo de yPlusLam = 11.06, nut de pared es 0, con corte brusco.
- **M:** con k∞ bajo, k en la celda de pared cae a 1e-6-3e-5 y el perfil queda en régimen laminar hasta x/c≈0.15 a α=0 (Cf 1.45e-3), donde salta a Cf 6.1e-3. A α=8 el extradós cambia también hacia 0.15 y el intradós hacia 0.06-0.10.
- **H:** la primera celda tiene un y+ real, con u_τ, cercano a 60, así que la malla no resuelve esa zona laminar. La posición del salto dependería de la malla, no de la física.
- **H:** la capa límite turbulenta nace tarde y más delgada, lo que explica a la vez menos Cd y más Cl.
- **Descartado:** falta de trip. TMR calcula totalmente turbulento, sin trip, con este mismo inflow; el trip con grit es de Ladson.

### 2.2 El acuerdo anterior no valida el método
- **M:** con I=5 %, νt/ν ≈ 12 000 en el flujo libre y el perfil es turbulento casi desde el borde de ataque.
- **H:** el buen Cd a α≤6 venía de ese exceso de turbulencia, que evitaba el artefacto. El error crece con el ángulo (+8.5 % a α=10).
- **Consecuencia:** la cifra de 2.27 % de la campaña de 44 casos no debe citarse como validación hasta completar la línea A.

### 2.3 Controles caídos
- **M:** `checkMesh` da no ortogonalidad máx. 89.6° (media 26°) y volumen mín. 2.4e-11; p explota en GAMG hasta 3e83. y+ reportado: 6.3.
- **H:** la causa es el salto de 45× entre la capa límite y el mallado exterior por no fijar `bl_total_height`, ya documentado en `mesh_script.py:318-325`.
- **M:** la malla de validación también tiene 85.6°. **H:** puede contribuir a la oscilación de Cd.

### 2.4 Transitorio
- **M:** con relajación 1 y `nOuterCorrectors` 2, Cl queda plano hasta t=0.02 s (≈0.3 tiempos convectivos).
- **Sin demostrar:** la prueba es corta y usa mallas estructuradas (44 145 y 24 885 celdas), no la de validación (117 874). El A/B de `6a19db0` no explica un factor 3 y no se transfiere a esta malla. V1 sigue abierto.

### 2.5 Los servidores no son equivalentes
- **M:** `openblade` tiene un parche manual en `gmshairfoil2d/geometry_def.py` que no está en `openblade2` ni en el repo. Con el mismo código, la misma prueba dio Cl 0.85 en uno y 0.90 en otro.
- **M:** la malla no estructurada sale con el mismo número de elementos en ambos, pero con distinto md5.

## 3. Ruta acordada

### Fase 0: preparación (1-2 h)
1. Incorporar el parche al repo y aplicarlo en ambos servidores.
2. Copiar la `m.msh` con su md5 en toda comparación entre servidores.
3. Corregir `programa_e1.py`: `residuo_p` (4 líneas por iteración), `ok` sin coeficientes, marca de `resultado.json` con hash de la configuración, y `bl_total_height`.
4. Registrar en cada caso Cf(x/c), y+ con u_τ y calidad de malla.
5. Fijar en commit los cambios pendientes de `core/openfoam_setup.py` antes de lanzar.

### Bloque 1: en paralelo

**openblade: control de pared B0 (4 procesos, ~1 h)**
- Malla de 118k, α=8, inflow TMR, `nutUSpaldingWallFunction`.
- Si el salto de Cf desaparece y Cd se acerca a la referencia, se revisa el alcance de la línea B: quizá baste con funciones de pared.
- Si persiste, la causa está en la malla.
- Riesgo: un comentario en `core/openfoam_setup.py` indica que Spalding no converge en la capa de amortiguamiento.

**openblade2: banco de referencia A1 (8 procesos, 4-6 h de conversión y ~1 h de cálculo)**
- Malla oficial TMR 449×129 con `plot3dToFoam -2D`, α=0 y 10, inflow TMR, `nutLowReWallFunction`.
- Separar patches a mano y comprobar la unión de la estela y el número exacto de celdas.
- Compuerta de valor: Cd(0°) = 0.0081 ± 2 % y Cl(10°) = 1.0778 ± 1 %.
- Compuerta de convergencia, evaluada aparte: sin deriva en las últimas 1000 iteraciones.

### Bloque 2: según el resultado

**openblade2: A2 (8-12 procesos, ~2 h)**
- Malla TMR 897×257, mismos casos. Separa el error de malla del error de solver.

**openblade: B1 + B2 (8-12 h)**
- B1: fijar `bl_total_height` ≈ 0.025 y las capas, dejar que gmsh calcule la razón, e iterar solo la malla (4 procesos).
- Compuerta de malla: no ortogonalidad < 70° y volumen mín. > 1e-9, ajustando el umbral de volumen si y+<1 lo exige.
- B2: α=0 y 4 con esa malla (8 procesos). Compuerta: Cd ±5 % y Cl ±3 % frente a A. α=8-10 es objetivo secundario.

Las compuertas de malla de B no se aplican a las mallas TMR.

### Bloque 3: con solver y malla decididos
- **Transitorio D:** α=8 en la malla de 118k, primero 500 pasos para medir dt. Se corren 3 tiempos convectivos (0.2 s) solo si el dt lo permite: con el dt de V1 serían ~100 000 pasos, unas 28 h.
- **Control C:** 2 casos, νt/ν = 0.009 y 1 a α=8, solo si B0 deja dudas.
- **Campaña final:** GCI en 3 niveles, polar 0-16°, URANS solo donde RANS no converja. γ-Reθ queda como estudio aparte, comparado con datos de transición libre.

### Qué decide cada resultado
| Resultado | Decisión |
|---|---|
| A pasa | Solver y condiciones absueltos; el problema está en el mallador o la pared |
| A falla en valor | Revisar esquemas, condiciones de contorno y dominio antes de tocar el mallador |
| A pasa en valor y falla en convergencia | Trabajar la estrategia de convergencia, no la física |
| B0 elimina el artefacto y acerca Cd | Modo rápido con funciones de pared como candidato; aún debe compararse con A |
| B0 no lo elimina | Pasar a y+<1 o cambiar la topología de malla |

## 4. Diferencias resueltas entre Claude y OpenClaw
- Trip: OpenClaw retiró su hipótesis tras revisar TMR.
- Barrido de νt/ν: se reduce de 8 a 2 casos y queda condicionado.
- Control con Spalding: propuesta de OpenClaw, adoptada antes de la línea B.
- Compuertas: separadas por línea y por tipo de fallo, a propuesta de OpenClaw.
- Causa de las mallas distintas: Claude corrigió a OpenClaw; es el parche, no la ausencia del paquete.
- Tiempos, corregidos por Claude: E1 tardó ~0.35 s/iter con V1 en paralelo, no 0.15. Línea D: se mide dt antes de comprometer horas.
