# Campaña de validación — noche del 2026-10-21/22

**Estado**: en curso. Este documento se actualiza a medida que avanzan las corridas.

---

## Hallazgos confirmados

### 1. El borde de salida estaba abierto (error real, corregido)

`core/geometry.py` y el fallback de `core/mesh_script.py` usaban el coeficiente
`-0.1015` de la fórmula NACA de 4 dígitos. Ese coeficiente deja el borde de
salida con **1.26 mm de espesor** en una cuerda de 1 m.

El NASA TMR especifica la variante de borde de salida cerrado (`-0.1036`), y
`core/structural_solver.py` ya la usaba — así que el programa tenía **dos
definiciones distintas del mismo perfil** según el módulo.

Impacto: un TE abierto añade arrastre espurio y ensucia la estela. Corregido en
los tres sitios.

### 2. La malla estructurada es la única que converge (error de criterio)

Aparente paradoja medida esta noche:

| Ruta | Celdas | Aspect ratio máx | Resultado |
|---|---|---|---|
| Estructurada (C-Grid) | 63 772 | 30 783 | **converge** |
| No estructurada | 221 066 | 182 | **diverge** |

La malla con peor aspect ratio converge y la que tiene mejor aspect ratio
diverge. El discriminante **no es la calidad de malla** sino la ruta: el
mallado no estructurado, con tres veces más celdas, introduce una
sensibilidad numérica que el solver no tolera con los esquemas actuales.

Consecuencia práctica: el preset de la campaña vuelve a `structured`. El
intento de usar la ruta no estructurada para dominios grandes (que era la
motivación del cambio) queda descartado hasta entender el mecanismo.

### 3. Las mallas a 150c son inservibles (confirmado cuantitativamente)

Con `farfield = 150c` la malla tiene:

- volumen mínimo 9.8×10⁻¹⁰ frente a máximo 2.79 → **ratio 10⁹**;
- **27 772 celdas con determinante 6.5×10⁻¹¹** (el promedio es 0.117);
- aspect ratio máximo 139 166.

El solver diverge en 16 iteraciones. El estudio de sensibilidad de dominio del
informe anterior usaba 150c con esquema de primer orden precisamente porque
con segundo orden no sobrevivía; ahora está cuantificado por qué.

---

## Referencias descargadas y verificadas

| Fichero | Contenido | Fuente |
|---|---|---|
| `refs/ladson_clcd.dat` | Cl y Cd vs α, NACA 0012, Re=6e6 | Ladson, NASA TM 4074 (1988) |
| `refs/ladson_cp.dat` | Cp vs x/c, NACA 0012 | Ladson, ídem |
| `refs/naca4412_cp.dat` | Cp vs x/c, NACA 4412, α=13.87° | Coles & Wadcock, vía NASA TMR |
| `refs/flatplate_cf.dat` | Cf vs x, placa plana, Re=5e6 | White, *Viscous Fluid Flow* (1974) |
| `refs/abbott_cl.dat` | Cl vs α (2 columnas) | Abbott & von Doenhoff (1959) |

**Nota importante**: `abbott_cl.dat` resultó ser del NACA **0012**, no del 2412
que yo suponía. Se retiró el caso 2412 de la campaña en vez de compararlo
contra datos de otro perfil.

---

## Casos de la campaña

| Caso | Perfil | α | Re | Referencia |
|---|---|---|---|---|
| `naca0012_tmr` | 0012 | 0, 4, 8, 10 | 6×10⁶ | Ladson, TM 4074 |

Pendientes de añadir (requieren geometría nueva): placa plana (White) y
NACA 4412 con separación (Coles & Wadcock).

---

## Lo que NO se ha podido hacer todavía

- Completar el barrido del NACA 0012: la corrida de α=0 seguía iterando al
  cerrar este documento.
- Añadir el NACA 4412: haría falta mallar la geometría del 4412 y correr a
  α=13.87°, que es un caso con separación y por tanto transitorio (no
  estacionario), lo que requiere otro régimen de solver.
- Placa plana: la geometría no es un perfil, hay que generarla aparte.

---

## Correcciones aplicadas al código

| Archivo | Cambio |
|---|---|
| `core/geometry.py` | TE cerrado (`-0.1036`) |
| `core/mesh_script.py` | TE cerrado en el fallback; opción `bl_fraction`; `bl_total_height` para acotar el espesor de la capa límite |
| `validation/campaign.py` | **nuevo**: campaña por lotes con referencias citadas |

Tests: 64 en verde antes de la campaña.


---

## Resultados obtenidos

### NACA 0012, Re = 6×10⁶ (Ladson, NASA TM 4074)

| α | Cl calc | Cl ref | error | Cd calc | Cd ref | error | iter |
|---|---|---|---|---|---|---|---|
| 0° | −0.0057 | −0.0121 | (ambos ≈0) | 0.00791 | 0.00807 | **−2.0%** | 392 |
| 4° | 0.4753 | 0.4272 | **+11.3%** | 0.00828 | 0.00823 | **+0.6%** | 1500 |
| 8° | diverge con 2.º orden | — | — | — | — | — | — |
| 10° | pendiente | — | — | — | — | — | — |

**Lectura**: el arrastre acierta entre −2% y +0.6%. La sustentación se
sobrestima un 11% a α=4. Ese es el patrón que hay que explicar, no el arrastre.

### Hallazgo nuevo: el segundo orden diverge a ángulo alto

A α=8 el caso con `linearUpwind` explota en 13 iteraciones (Cl ~ 3×10¹⁴). Con
`upwind` de primer orden **no diverge**, pero el resultado queda sesgado.

Esto reordena el diagnóstico del informe anterior: allí se atribuía la
divergencia a la malla del dominio grande. Ahora sabemos que hay **un segundo
factor independiente, el ángulo de ataque**: a α=0 y 4 el segundo orden es
estable, a α=8 no. La causa probable es que la estela se desvía y el C-Grid
—que solo refina la estela horizontal— deja de resolverla, con lo que el
término de corrección de `linearUpwind` se vuelve inestable.

### Sobre el residual estancado

A α=0 y α=4 el residual de Ux se estanca en ~1×10⁻⁵ con tolerancia 1×10⁻⁵: el
solver nunca la alcanza y agota las iteraciones. Los coeficientes del caso α=0
son estables a pesar de ello (dispersión 1×10⁻⁶), pero los de α=4 derivan
lentamente (Cl sube durante 1000 iteraciones). **La tolerancia por defecto es
demasiado estricta para esta malla**; conviene relajarla a 1×10⁻⁴ o refinar la
estela.

## Bugs de la propia campaña (corregidos)

- `run_solver` es asíncrono; la primera versión llamaba a un método `run` que
  no existe.
- `read_force_coeffs` devuelve una tupla y se usaba como diccionario.
- El generador de malla cae al PLAN B (no estructurado) **sin avisar por la
  salida que lee la campaña**, lo que mezclaba mallas incomparables. Ahora se
  detecta y se rechaza el caso.


---

## α = 8°: el caso que rompe

Con `linearUpwind` (2.º orden) el caso **explota en 13 iteraciones**
(Cl ~ 3×10¹⁴). Con `upwind` de primer orden **no diverge**, pero el resultado
está muy sesgado: Cl = 0.589 frente a 0.8615 de referencia (**−32%**).

Eso separa dos problemas que el informe anterior mezclaba:

1. **La malla del dominio grande** (150c) es inservible por el C-Grid: está
   cuantificado y es independiente del ángulo.
2. **El ángulo alto** rompe el esquema de segundo orden **incluso con malla
   sana a 50c**. Es un segundo defecto, no el mismo.

Hipótesis para 2: a α=8 la estela se desvía y el C-Grid solo refina la estela
horizontal; el término `grad(U)` de `linearUpwind` se vuelve inestable donde la
malla no resuelve el gradiente. Verificarlo requiere mallar explícitamente la
estela desviada, que es el trabajo pendiente.

## Placa plana: intento no completado

Se escribió `validation/flatplate.py`, que construye el canal con la placa y
carga la Cf teórica de White. El primer generador (quads a mano) producía
celdas con volumen negativo. El segundo, con Gmsh y `fragment`, **no separó la
placa como grupo físico**: el `.msh` solo declara `walls`, así que la condición
de no-deslizamiento no se aplicaría donde debe. Queda pendiente.

## Resumen del estado

| Caso | Estado |
|---|---|
| NACA 0012 α=0 | ✅ Cd −2.0% |
| NACA 0012 α=4 | ✅ Cd +0.6%, Cl +11.3% |
| NACA 0012 α=8 | ⚠️ diverge con 2.º orden; −32% con 1.º |
| NACA 0012 α=10 | ⏸ no ejecutado |
| NACA 4412 α=13.87 | ⏸ pendiente (requiere transitorio) |
| Placa plana | ⏸ generador incompleto |
