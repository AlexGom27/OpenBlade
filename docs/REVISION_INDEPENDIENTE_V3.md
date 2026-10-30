# Revisión independiente del programa v3 (Claude)

**Fecha:** 2026-10-30, ~04:40 hora del servidor
**Alcance:** monitoreo del programa v3 en el servidor `openblade`, revisión de
`validation/programa_v3.py`, `core/openfoam_setup.py`, `docs/DIAGNOSTICO_FINAL.md`,
de los resultados guardados por Jesús Ruiz y de la literatura (NASA TMR, Ladson,
IISc CAd TN 2021:05).
**Método:** solo lectura en el servidor. No se detuvo ni modificó nada.

Este documento es para que OpenClaw lo contraste. Cada afirmación lleva su
evidencia y la forma de reproducirla. Si algo no se sostiene, corregidlo aquí.

---

## 0. Resumen en cinco líneas

1. **El transitorio V1 vuelve a dar resultados no físicos**: a α=8 el Cl salta de
   0.84 a 2.69 en el *primer* paso (Δt = 2×10⁻⁶ s) y se queda en ~1.6. El
   `potentialFoam` no era la causa raíz.
2. **V1 tardará ~55 h por ángulo** (~9 días en total) y bloquea V2 (GCI), que es
   lo que pide la certificación. Recomiendo detener V1 y priorizar V2.
3. **La turbulencia de entrada es ~10⁶ veces la prescrita por NASA TMR**:
   νt/ν ≈ 12 000 en todo el dominio (TMR: 0.009). Es la hipótesis más fuerte para
   el Cd alto a α ≥ 7 y es barata de probar (≈1 h).
4. **El RANS a α=8 no converge**: residuo de p estancado en 4×10⁻³, Cl derivando.
   Los promedios de la cola ocultan esa deriva.
5. V2, V3 y V4 tienen defectos de diseño que harían inválidos sus resultados
   aunque corran bien (detalle en §3).

---

## 1. Estado del servidor al revisar

```
programa_v3.py  PID 237410, cwd /home/alejandro/OpenBlade
mpirun -np 10 foamRun  cwd /tmp/v3/V1_trans_a8   (transitorio en curso)
t = 0.00225 s de 0.4 s  |  Δt = 2.03e-6 s  |  ~1.04 s de reloj por paso
```

**Proyección:** 0.4 s / 2×10⁻⁶ s ≈ 200 000 pasos × 1 s ≈ **55 h por ángulo**.
Con 4 ángulos, V1 ocupa el servidor ~9 días antes de llegar a V2.

**Se lanzaron dos instancias a la vez** (04:16 y 04:19). Evidencia:
`out.log` contiene `[2026-[2026-10-30 04:19]` (dos procesos escribiendo la misma
línea). La segunda encontró coeficientes del RANS *a medio correr* de la primera,
lo marcó como `reutilizado` y guardó en `resultados.json`:

```
V1_trans_a8  cache=true  Cl=0.7959  Cd=0.01250  err_cd=+26.4%
```

Ese registro **no es un resultado transitorio**: es el promedio del 40 % final de
un RANS parcial. Hay que descartarlo.

---

## 2. Hallazgos con evidencia

### 2.1 El transitorio salta en el primer paso

`/tmp/v3/V1_trans_a8/postProcessing/forceCoeffs/0/forceCoeffs.dat`
(OF-12, columnas `Time Cm Cd Cl Cl(f) Cl(r)`):

| t [s] | Cd | Cl |
|---|---|---|
| 0 (campo RANS copiado) | 0.0147 | **0.837** |
| 2.04×10⁻⁶ (1er paso) | 0.2428 | **2.694** |
| 4.09×10⁻⁶ | 0.0632 | 1.883 |
| 3.0×10⁻⁴ | 0.0710 | 1.682 |
| 2.1×10⁻³ | 0.0331 | 1.604 |

En 2×10⁻⁶ s el fluido avanza 0.03 mm: físicamente nada puede cambiar. Un salto
de fuerzas en un paso es una inconsistencia numérica en el reinicio, y como el
tiempo de relajación de la circulación es ~c/U = 0.067 s, en 0.002 s no se
recupera. La campaña anterior (arranque uniforme) daba el mismo patrón
(Cl = 2.75 a α=8): **el problema es de configuración del transitorio, no del
campo inicial**.

Dos mecanismos visibles en `run.log`:

**a) El PIMPLE no converge dentro de cada paso.** En cada paso el residuo
inicial de p arranca en ~1 y baja solo ×0.73 por iteración externa:

```
PIMPLE: Iteration 1   p initial residual 0.986
PIMPLE: Iteration 2   0.654
PIMPLE: Iteration 3   0.455
...                   (×0.73 por iteración)
PIMPLE: Iteration 12  ~0.03
```

Es la huella de `relaxationFactors { fields { p 0.2; } }` aplicada dentro del
bucle transitorio sin factores `Final` = 1. Cada paso termina sin converger y el
error se acumula durante cientos de miles de pasos.

**b) `phi` no se copia al reiniciar.** `correr_trans` copia
`U p k omega nut` de `processorN/2500/` a `processorN/0/`, pero no `phi`, que sí
existe en `2500/`. Sin el flujo de caras conservativo, OpenFOAM lo reconstruye
interpolando U; esa reconstrucción no es discretamente libre de divergencia, y
con Δt diminuto la corrección de presión escala como (divergencia)/Δt.

### 2.2 El paso de tiempo está fijado por las celdas de pared

`maxCo 1` con la primera celda de capa límite obliga a Δt ≈ 2×10⁻⁶ s, mientras
la escala física es c/U = 0.067 s. Courant medio: 0.00016. Es decir, el 99.98 %
del dominio avanza con un paso ~6000 veces menor del necesario.

Práctica habitual para URANS de perfiles: fijar Δt por la escala convectiva,
Δt·U/c ≈ 1/200 – 1/500 (Δt ≈ 1.3×10⁻⁴ – 3.3×10⁻⁴ s), y dejar que el Courant
local de pared sea alto, compensado con iteraciones externas PIMPLE convergidas.

### 2.3 El RANS de partida no está convergido

Historia de `run.log` a α=8 (2500 iteraciones):

| it | Cl | Cd | residuo p |
|---|---|---|---|
| 1000 | 0.8003 | 0.02057 | 1.1×10⁻² |
| 1500 | 0.7840 | 0.01267 | 5.8×10⁻³ |
| 2000 | 0.7902 | 0.01220 | 4.9×10⁻³ |
| 2250 | 0.8114 | 0.01417 | 4.2×10⁻³ |
| 2500 | 0.8371 | 0.01466 | 3.9×10⁻³ |

Últimas 500: Cl 0.7902–0.8371, Cd 0.0117–0.0150. El residuo de p no baja de
4×10⁻³ (objetivo 10⁻⁵) y el Cl sigue subiendo al final. `leer_coeffs` promedia
la cola y devuelve Cd = 0.01365 (+38 %), que es el promedio de una señal que no
ha llegado a ningún sitio.

**Los datos históricos de Jesús confirman el patrón** (`Estudiantes/Jesus Ruiz/
Validación/resultados_cfd/resultados.json`):

| Caso | Cd | Comentario |
|---|---|---|
| α=8 base / media / fina | 0.0105 / 0.0110 / 0.0132 | refinar **empeora** |
| α=10 media / fina | 0.0123 / 0.0157 | refinar empeora |
| α=14 media | **−0.0026** | Cd negativo: imposible |
| barrido α=13, 14, 15 | 0.0138, 0.0060, 0.0040 | Cd **baja** con α: imposible |

Un Cd que empeora al refinar y valores negativos son la firma de error
iterativo, no de error del modelo de turbulencia. Esto **matiza la conclusión de
`DIAGNOSTICO_FINAL.md` §2.1** ("error físico sistemático"): antes de culpar al
modelo hay que demostrar convergencia iterativa.

### 2.4 La turbulencia de entrada es enorme ← hipótesis principal

`core/openfoam_setup.py` (líneas ~387-398) usa I = 5 % y l = 0.07c. En el caso
real a α=8:

```
0/k     inlet  0.844  m²/s²
0/omega inlet  23.96  1/s
νt/ν en la entrada = (k/ω)/ν = 0.0352 / 2.5e-6 ≈ 14 000
```

Medido sobre las 117 874 celdas del campo convergido (`processor*/2500/nut`):

```
νt/ν   p10 = 581   mediana = 11 948   p90 = 13 100
```

Prescripción de NASA TMR para este mismo caso (fichero
`n0012clcd_cfl3d_sst.dat`): `k/a² = 9e-9`, `ω·μ/(ρ·a²) = 1e-6`. Con a = U/M =
15/0.15 = 100 m/s y ν = 2.5×10⁻⁶ m²/s:

```
k   = 9.0e-5  m²/s²   (Tu = 0.052 %)
ω   = 4000    1/s
νt/ν = 0.009
```

**Diferencia: k ×9 400, νt/ν ×1.3 millones.** Dentro de una capa límite
turbulenta a Re = 6×10⁶ el pico de νt/ν es del orden de cientos; aquí el flujo
libre tiene más viscosidad turbulenta que la propia capa límite. Engrosa la capa
límite, sube el arrastre de fricción y de forma, y el efecto crece con α (capa
límite del extradós más gruesa). Es coherente con: Cd bien a α=0–6, Cd alto a
α ≥ 7, Cl ligeramente bajo a α=10 (−5 % vs Abbott).

El comentario del código dice que el valor anterior (I = 1 %, ω = k/(10ν),
νt/ν = 10) "colapsaba" con SIGFPE y se cambió a I = 5 %. Ese cambio fue en la
dirección contraria a la correcta. El SIGFPE debió tener otra causa (malla de
aquella época); TMR usa ω aún mayor sin problema.

### 2.5 La referencia experimental tiene ±3–7 % de dispersión

`validation/refs/ladson_clcd.dat` (Re = 6×10⁶, tripped) tiene tres rugosidades.
Interpolado a los ángulos del programa:

| α | Cd 80 grit | Cd 120 grit | Cd 180 grit | dicc. `LADSON` | dispersión |
|---|---|---|---|---|---|
| 4 | 0.00823 | 0.00876 | 0.00814 | 0.00823 (80) | 7.4 % |
| 8 | 0.01028 | 0.00989 | 0.00979 | 0.00989 (120) | 4.9 % |
| 10 | 0.01191 | 0.01166 | 0.01149 | 0.01168 (≈120) | 3.6 % |
| 14 | 0.01601 | 0.01565 | 0.01520 | 0.01533 (≈180) | 5.2 % |

1. El diccionario `LADSON` **mezcla zonas de rugosidad según el ángulo**. Hay que
   fijar una (TMR compara con 80 grit) o usar la media con su dispersión como
   incertidumbre.
2. Un umbral de "dentro del 3 %" está **por debajo de la incertidumbre de la
   propia referencia** a α ≥ 4.
3. Los propios códigos de NASA con SST (tabla abajo) quedan +3 % sobre Ladson a
   α=10 y +17 % a α=15. Pedirle a SST ±3 % contra Ladson a ángulo alto es
   pedirle algo que el modelo no hace.

### 2.6 Referencia numérica oficial (verificación, no validación)

NASA TMR, `tmbwg.github.io/turbmodels/naca0012_val_sst.html`, SST, malla 897×257,
farfield ~500c con corrección de vórtice puntual:

| Código | Cl α=10 | Cl α=15 | Cd α=0 | Cd α=10 | Cd α=15 |
|---|---|---|---|---|---|
| CFL3D | 1.0778 | 1.5068 | 0.00809 | 0.01236 | 0.02219 |
| FUN3D | 1.0840 | 1.5109 | 0.00808 | 0.01253 | 0.02275 |
| NTS | 1.0765 | 1.5100 | 0.00809 | 0.01251 | 0.02187 |

Dispersión código a código: <1 % en Cl, <5 % en Cd. **Esta es la meta correcta
para verificar OpenBlade+SST**: si con la misma física (Tu, νt/ν, farfield)
OpenBlade cae dentro de esa banda, la implementación está verificada; la
diferencia restante con Ladson es error del modelo SST, no de OpenBlade.

Notas TMR relevantes: farfield a ~500c o corrección de vórtice puntual (OpenBlade
usa 40c con U fija arriba/abajo); αmax = el mayor ángulo con solución
estacionaria sin oscilación de fuerzas, que se reporta, no se fuerza.

---

## 3. Defectos de diseño en las fases pendientes (V2–V5)

### V2 — GCI

| Problema | Dónde | Efecto |
|---|---|---|
| `gci_roache()` nunca se llama | `main()` | V2 no calcula GCI, solo corre casos |
| `celdas={r['n']}` imprime el nº de muestras de la cola, no de celdas | log V2 | El log dirá "celdas=1000" |
| Exponente 1/3 para r | `gci_roache` | La malla es 2D (una celda de espesor): r = (N₂/N₁)^(1/2). Con 45k/118k/250k: r = 1.62 y **1.46**, no 1.38 y 1.28 |
| Los niveles cambian `bl_dist_min` 2e-3 / 8e-4 / 4e-4 | `niveles` | y+ ≈ 140 / 57 / 28: cambia el **régimen** de la ley de pared entre niveles. La diferencia mezcla error de modelado con error de discretización |
| Mallas no estructuradas generadas por separado | gmsh | No son geométricamente semejantes |
| Sin control de convergencia iterativa | `leer_coeffs` | Con el RANS estancado de §2.3 el GCI medirá ruido |

Metodología recomendada (IISc CAd TN 2021:05 y NASA TMR): **una sola familia
anidada** por subdivisión uniforme (cada celda → 4 en 2D, r = 2 exacto),
reproyectando los nodos de pared sobre el perfil, con y+ < 1 en *todos* los
niveles y ley de pared low-Re. Alternativa inmediata: usar las mallas C de TMR
(familia de 7 niveles, farfield 500c) con `plot3dToFoam` + `extrudeMesh`.

### V3 — DES

Corre con `correr_est` (estacionario, `ddt steadyState`, 4000 iteraciones) sobre
un dominio 2D de una celda con `frontAndBack empty`. DES es un método de
resolución de escalas: requiere tiempo preciso **y** dominio 3D con extensión en
envergadura (≥ ~1c, resuelta). En 2D estacionario el resultado no tiene
significado físico. Recomendación: retirar V3 de esta campaña; si se quiere
ángulo alto, URANS-SST bien configurado (§4) y declarar αmax.

### V4 — y+ bajo

`bl_dist_min = 2e-4` da y+ ≈ 10–14 (el comentario de `openfoam_setup.py` mide
2.5e-4 → y+ medio 11.9). Eso cae en la **capa de amortiguamiento**, que el mismo
comentario documenta como el peor régimen (Cd +310 %). Para y+ < 1 hace falta
`bl_dist_min ≈ 2e-5` (también medido en el comentario), con la malla de capa
límite revisada (el comentario de `mesh_script.py` advierte que 2e-5 con 30 capas
produjo celdas degeneradas).

### V5 — estela inclinada

El código existe (`mesh_script.py` ~298) y es opt-in. Sin objeciones de diseño,
pero su efecto quedará enmascarado por §2.3–2.4 si no se corrigen antes.

### Infraestructura

- **Caché falsa**: `correr_trans` da por "reutilizado" un caso con ≥30 filas de
  coeficientes, aunque sean del RANS o de una corrida parcial (pasó en §1).
  Hay que marcar el final con un fichero (`DONE_trans`) y comprobar eso.
- **Sin bloqueo** contra dos instancias: añadir un lockfile en `--work`.
- **Promedio sin criterio**: `leer_coeffs` promedia el 20–40 % final sin
  comprobar que la señal sea estacionaria.

---

## 4. Ruta recomendada (ordenada por información / coste)

**Paso 0 — Decidir sobre V1 en curso.** Recomiendo detenerla: dará un resultado
no físico (Cl ≈ 1.6 a α=8) después de ~55 h. Decisión vuestra.

**E1 — Turbulencia de entrada TMR (≈1 h, 4 casos estacionarios).**
α = 0, 4, 8, 10, misma malla base, mismos esquemas. Única diferencia:

```
k_inlet     = 9.0e-5     (Tu = 0.052 %)
omega_inlet = 4000       (νt/ν = 0.009)   para U = 15, ν = 2.5e-6
```

(en general: k = 1.5·(U·Tu)², ω = k/(0.009·ν)). Opcional si OF-12 lo admite en
`kOmegaSST`: `decayControl yes; kInf ...; omegaInf ...;` para que no decaigan.
**Qué decide:** si Cd a α=8–10 baja hacia 0.0102–0.0125, §2.4 era la causa
principal y todo lo demás se reevalúa con esta física.

**E2 — Criterio de convergencia iterativa (se incorpora a todo).**
Un caso estacionario cuenta solo si en las últimas 500 iteraciones:
|ΔCl|/Cl < 0.1 %, |ΔCd|/Cd < 0.5 % y el residuo de p bajó ≥ 3 órdenes. Si no se
cumple, el caso se reporta como **no convergido**, no se promedia. Si sigue
oscilando con amplitud estable, ese α está por encima de αmax estacionario.

**E3 — Farfield (≈1 h).** Con E1 aplicado: α=10 con farfield 40c y 200–500c
(celdas muy estiradas lejos, coste bajo en 2D). TMR recomienda 500c.

**E4 — GCI real (≈6–10 h).** Familia anidada r = 2, y+ < 1 en todos los
niveles, α = 0, 4, 10 (10 para comparar con TMR). Calcular p y GCI con
exponente 1/2. Alternativa: mallas TMR 2DN00.

**E5 — Transitorio, solo si hace falta (α ≥ αmax).** Configuración propuesta:

```
ddt            backward
Δt             1.3e-4 s fijo (Δt·U/c = 1/500); sin maxCo
PIMPLE         nOuterCorrectors 20, nCorrectors 2,
               residualControl que corte las iteraciones externas al
               converger (verificar la sintaxis exacta en OF-12)
relaxation     fields { p 0.3; pFinal 1; }
               equations { ".*" 0.7; ".*Final" 1; }
reinicio       copiar también phi; arrancar del RANS solo si E2 lo da por convergido
duración       ≥ 10 c/U de transitorio + 10 c/U de estadística
```

Coste estimado: ~3000 pasos × ~5 s ≈ 4 h por ángulo, frente a 55 h.

### Criterio de aceptación propuesto (ASME V&V 20)

Para cada α: E = S − D y u_val = √(u_num² + u_input² + u_D²), con u_num del GCI
(E4), u_D de la dispersión entre rugosidades de Ladson (§2.5). Declarar validado
donde |E| ≤ u_val. Por separado, verificación contra TMR (§2.6): banda ±1 % Cl,
±5 % Cd.

---

## 5. Preguntas para OpenClaw

1. ¿El paso de I = 1 % a I = 5 % se hizo antes o después de la campaña que validó
   α = 0–6 con <2.3 %? Si fue antes, esos resultados ya incluyen el efecto §2.4
   y su acierto a α bajo sería en parte compensación de errores.
2. ¿OF-12 aplica relajación en la última iteración PIMPLE si no hay factores
   `Final`? El log sugiere que sí (§2.1a); conviene confirmarlo en el código.
3. ¿Hubo SIGFPE con ω alto en la malla actual (117 874 celdas) o solo en mallas
   anteriores? E1 lo responde de paso.
4. ¿Se puede añadir el lockfile y la marca `DONE` antes de relanzar?
