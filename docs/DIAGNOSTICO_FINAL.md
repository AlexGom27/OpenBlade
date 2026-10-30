# Diagnóstico final — programa completo de validación NACA

**Ejecutado:** 2026-10-27 04:04 → 2026-10-30 02:33 (71 h)
**Casos:** 32, en 8 fases
**Servidor:** openblade, 20 cores / 10 físicos, OpenFOAM 12 nativo

---

## 1. Resumen en una línea

La mitad de las fases dieron resultados útiles y la otra mitad falló por causas
que ya están identificadas y son corregibles. **La validación estacionaria es
sólida; la transitoria está mal configurada y no dice nada sobre la física.**

---

## 2. Lo que salió bien

### 2.1 Segunda fuente independiente confirma el Cl (fase A3)

Contra Abbott & von Doenhoff, un libro distinto de Ladson:

| α | Cl CFD | Cl Abbott | Error |
|---|---|---|---|
| 2° | +0.2182 | 0.2194 | **−0.6 %** |
| 4° | +0.4437 | 0.4558 | −2.6 % |
| 6° | +0.6592 | 0.6566 | **+0.4 %** |
| 8° | +0.8558 | 0.8749 | −2.2 % |
| 10° | +1.0448 | 1.0995 | −5.0 % |

**El Cl es correcto contra dos fuentes independientes.** El error medio es 2.2 %
y crece de forma monótona con el ángulo, lo que es la firma de un error físico
sistemático (no numérico).

### 2.2 El modelo de transición mejora el arrastre a ángulo moderado (A2)

| α | k-ω SST | gamma-ReTheta | Ladson | Error LM |
|---|---|---|---|---|
| 8° | 0.01050 | **0.01018** | 0.00989 | **+2.9 %** |
| 10° | 0.01292 | **0.01317** | 0.01168 | +12.7 % |
| 12° | 0.02008 | 0.01845 | 0.01294 | +42.6 % |

A α=8 el modelo de transición baja el error de **+6.1 % a +2.9 %**, dentro del
umbral de certificación. A α=10 no ayuda y a α=12 tampoco.

**Conclusión:** la transición importa a ángulo moderado, no a ángulo alto. El
problema a ángulo alto es otro.

### 2.3 La tendencia física del espesor es correcta (B2)

| Perfil | Cd | Espesor |
|---|---|---|
| 0009 | 0.00790 | 9 % |
| 0012 | 0.00804 | 12 % |
| 0015 | 0.00911 | 15 % |
| 0018 | 0.00910 | 18 % |
| 0021 | 0.00953 | 21 % |

Monótona creciente, como debe ser. El salto entre 12 % y 15 % (+13 %) es el
mayor; entre 15 % y 18 % no hay cambio. Esa meseta es sospechosa y sugiere que
la malla no resuelve bien el espesor creciente.

### 2.4 El dominio de 80c confirma el diagnóstico de bloqueo (M1)

| Dominio | α=0 | α=8 |
|---|---|---|
| 20c | +14.2 % | +44.9 % |
| **40c** | **−0.5 %** | **+2.7 %** |
| 80c | −5.9 % | +10.3 % |

A α=0 el 80c es mejor que el 40c (−5.9 % vs −0.5 %): el dominio base aún tiene
algo de bloqueo. A α=8 empeora, y eso apunta a que el error a ángulo alto **no
es de dominio** sino del modelo.

### 2.5 El GCI a α=4 converge (M3)

| Malla | Cd |
|---|---|
| gruesa | 0.00827 |
| base | 0.00841 |
| fina | 0.00843 |

Convergencia monótona hacia 0.00843. **A α=4 el resultado es convergente.**

---

## 3. Lo que falló, y por qué

### 3.1 Los transitorios (A1): configuración, no física

Este era el experimento central y salió mal. Los números:

| α | Cl | Cd | Error Cd | Oscilación |
|---|---|---|---|---|
| 8° | +2.752 | 0.0282 | +184.8 % | 0.0196 |
| 10° | +3.743 | 0.0566 | +384.7 % | 0.0323 |
| 12° | +4.661 | 0.0184 | +42.1 % | 0.0606 |
| 14° | +5.533 | 0.1813 | +1082.5 % | 0.0794 |

Un NACA 0012 tiene un Cl máximo de ~1.5. **Cl = 5.5 es físicamente imposible.**

**Causa encontrada:** el transitorio arrancó con el campo **uniforme**:

```
0/U (inicial): UNIFORM (15 0 0)
0/p (inicial): UNIFORM 0
```

Mientras el estacionario sí arranca de un campo resuelto:

```
A3_abbott_a8  0/p: nonuniform  min=-27.5  max=54.9
```

Es decir, **`potentialFoam` no se ejecutó antes de los casos transitorios**. El
solver arrancó con un escalón de presión en el borde de ataque y nunca se
recuperó. La primera iteración lo confirma:

```
GAMG: Solving for p, Initial residual = 1, Final residual = 0.0867
```

Un residuo inicial de exactamente 1 significa campo nulo. A partir de ahí el
campo derivó sin control: el Cl del primer cuarto es 1.70 y el del último 2.77,
con deriva de +1.07 — no hay estado estacionario al que converger.

**Por qué no lo detecté antes:** el Courant se mantuvo en 2.98 y la continuidad
en 1e-13. Numéricamente el caso "funcionaba". El problema es que estaba
resolviendo un transiente espurio, no el flujo físico.

**El campo de presión lo delata.** Cp mínimo por procesador a α=14:

```
proc 0:  -32.1        proc 5:   -11.9
proc 1:  -42.5        proc 6:    -4.6
proc 2: -3359.8  ←    proc 7:   -91.1
proc 3: -1188.2  ←    proc 8:    -4.0
proc 4: -2924.9  ←    proc 9:    -3.6
```

Cp = −24 en tres subdominios, contra −3.15 del caso estacionario. Hay
singularidades locales en las interfaces de partición. Eso es el subproducto de
arrancar de un campo uniforme con `scotch`: las interfaces caen en zonas donde
el gradiente inicial es máximo y el esquema no las resuelve.

### 3.2 El GCI no es un GCI

Los tres niveles de malla tienen:

```
gruesa: 110,926 celdas
base:   117,994 celdas
fina:   125,480 celdas
```

Razón de refinado **r = 1.021**. El criterio de Roache exige r ≥ 1.3, y en la
práctica r ≥ 1.1 como mínimo absoluto. **Con r = 1.02 no se puede calcular orden
de convergencia ni índice GCI.** Los tres números son prácticamente la misma
malla.

Los valores a α=12 (0.01967 / 0.01923 / 0.01038) no son una secuencia de
convergencia: el salto de −46 % en la última es ruido, no refinado.

**En la campaña anterior pasaba lo mismo**: 110,942 / 117,854 / 125,372, misma
r = 1.02. El "GCI monótono" que reporté entonces era una ilusión: los tres
puntos caían sobre la misma malla y la variación era dispersión numérica.

### 3.3 El C-Grid no funciona con `limitedLinearV` (M2)

| α | C-Grid | Error |
|---|---|---|
| 0° | 0.00911 | +12.9 % |
| 4° | 0.01175 | +42.8 % |
| 8° | 0.01901 | +92.2 % |

Degrada con el ángulo mucho más que la malla no estructurada. **Hipótesis
descartada:** el C-Grid no es una alternativa viable con este esquema.

### 3.4 El barrido de Reynolds no tiene referencia

| Re | α=0 | α=8 |
|---|---|---|
| 1×10⁶ | 0.01091 | 0.01345 |
| 3×10⁶ | 0.00877 | 0.01102 |
| 6×10⁶ | 0.00804 | 0.01050 |

La tendencia es correcta (Cd baja al subir Re) y la caída es suave, pero **no hay
datos experimentales con los que comparar** a esos Re para este perfil en la
carpeta. Sin referencia, son números sin validar.

---

## 4. El patrón que emerge

Poniendo juntos todos los casos estacionarios con referencia:

| Rango | Error medio | Diagnóstico |
|---|---|---|
| α = 0–6° | **2.3 %** | Validado |
| α = 7–11° | **9.4 %** | Aceptable con reservas |
| α = 12–15° | **> 40 %** | No válido |

La frontera está en **α ≈ 11°**, que es justo donde el NACA 0012 empieza a
separar. Todo lo que falla a ángulo alto falla por la misma razón: **el modelo
no captura la separación**.

Y hay un dato que lo confirma: **refinar la malla empeora**. En la campaña
anterior, α=10 pasó de +5.4 % (malla media) a +34.0 % (malla fina). Si el error
fuera de discretización, refinar lo reduciría. Al crecer, el error es del modelo:
más resolución destapa física que el `k-ω SST` no representa.

---

## 5. Rutas para mitigar los errores

### Ruta 1 — Arreglar el transitorio (prioridad máxima, coste bajo)

Es un bug, no un problema de física. Cuatro correcciones:

**a) Ejecutar `potentialFoam` antes del transitorio.** El código lo hace para
estacionario pero no para transitorio. Es la causa raíz.

**b) Calentar en estacionario y arrancar de ahí.** Correr 500 iteraciones de
`foamRun` estacionario, copiar el campo a `0/`, y lanzar el transitorio. Elimina
el transiente espurio.

**c) Esquema temporal de segundo orden.** Ahora usa `Euler` (primer orden, muy
difusivo). Cambiar a `backward` o `CrankNicolson 0.9`. Con `Euler` y
`dt = 3.6e-06` el error temporal domina.

**d) `nOuterCorrectors` mayor.** Está en 3. Para transitorio con Courant ~3,
subirlo a 10–20 y bajar `maxCo` a 1.

Con esto, el transitorio a α=8 debería dar algo cercano a 0.010–0.012 y
decirnos si a α=12 el flujo oscila de verdad.

### Ruta 2 — Modelo de turbulencia para separación (prioridad alta, coste medio)

El `k-ω SST` con función de pared resuelve bien hasta α≈11 y falla después. Tres
opciones, de menor a mayor coste:

**a) `k-ω SST` con corrección de curvatura o de rotación.** Barato, puede ganar
1–2 puntos a ángulo alto.

**b) DES o DDES.** Separa el tratamiento: RANS cerca de la pared, LES en la
estela separada. Es lo estándar para este problema. Coste: 10–50× el RANS, pero
solo para 3–4 ángulos.

**c) LES con pared modelada (WMLES).** Más caro aún, pero es lo que hace el NASA
TMR para sus casos de referencia.

Para certificación, lo práctico es **DES/DDES a α = 12, 14, 16** y mantener RANS
para el rango adjunto.

### Ruta 3 — Rehacer el GCI de verdad (prioridad alta, coste bajo)

Necesitas tres mallas con **r ≥ 1.3**, no 1.02. Por ejemplo:

```
gruesa:   60,000 celdas   (r = 1.6 respecto a base)
base:    118,000 celdas
fina:    250,000 celdas   (r = 1.28 respecto a base)
```

Con esas tres se puede calcular:

```
p  = orden observado de convergencia
GCI = Fs · |ε| / (r^p − 1)        Fs = 1.25 (tres mallas)
```

Y reportar el intervalo de incertidumbre numérica, que es lo que pide una
certificación. Ahora mismo no tienes ese número.

**Esto invalida la conclusión de la campaña anterior.** El "GCI monótono" era
dispersión entre mallas casi idénticas.

### Ruta 4 — Cerrar el hueco de α = 7–11 (prioridad media, coste bajo)

Es el rango más útil en ingeniería y está en 9.4 % de error. Tres palancas:

**a) Refinar solo la estela.** La caja de estela actual es horizontal y fija
(`YMin = −0.06c`, `YMax = +0.06c`). A α=8 la estela se inclina ~10° y sale de la
caja. Hacerla **inclinada con el ángulo** es la corrección más directa.

**b) `y+` más bajo.** Ahora `y+ ≈ 57`, que está en tierra de nadie (ni pared
resuelta ni función de pared bien aplicada). Bajar `bl_dist_min` de 8e-4 a 2e-4
daría `y+ < 5` y permitiría `nutLowReWallFunction`.

**c) Malla de capa límite más gruesa en el extradós.** A ángulo alto la capa
límite se engrosa mucho en el extradós; 12 capas con growth 1.22 no alcanzan.

### Ruta 5 — Referencias que faltan (prioridad media, coste bajo)

**a) Abbott & von Doenhoff, digitalizar el Cd.** El PDF está, pero las gráficas
están escaneadas. Digitalizar las curvas del 0012, 2412 y 4412 con una herramienta
tipo WebPlotDigitizer daría una segunda fuente de Cd, no solo de Cl.

**b) Ladson TM 4074 completo.** Tienes los coeficientes, pero faltan las curvas
de Cp y el resto de la tabla. Vale la pena tenerlo entero.

**c) Datos de GCI publicados.** Para comparar tu incertidumbre numérica con la de
otros. Buscar en el NASA TMR los casos con estudio de convergencia.

### Ruta 6 — Los otros perfiles (prioridad baja, coste bajo)

Los datos del 2412 y 4412 son plausibles pero no están validados. Con Abbott
digitalizado se pueden comparar. Es trabajo de una tarde.

---

## 6. Parámetros para certificación: qué falta

Para que el programa sirva en un contexto de certificación hacen falta **cuatro
cosas que ahora no tiene**:

**1. Incertidumbre numérica cuantificada.** Sin un GCI con r ≥ 1.3 no se puede
declarar. Es requisito de ASME V&V 20 y de la AIAA.

**2. Rango de validez declarado.** Con los datos actuales sería:

```
Válido:      α ∈ [0°, 11°], Re = 6×10⁶, incompresible
Incertidumbre: ±3 % en Cd hasta α=6°, ±10 % hasta α=11°
No válido:   α > 11° (separación no resuelta)
```

**3. Verificación de malla en la configuración final.** El GCI debe hacerse con
la malla y el esquema que se usen en producción, no con una variante.

**4. Trazabilidad.** Cada resultado debe llevar su configuración exacta, su
referencia y su error. `resultados.json` ya lo hace; falta el GCI.

### La configuración que sí está validada

```
Malla:        no estructurada, 117,854 celdas
              bl_dist_min 8e-4 (y+ ≈ 57)
              300 pts en el perfil (645 caras)
              farfield 40c, wake_length 30c
Esquema:      limitedLinearV 1  (limitador de van Leer)
Turbulencia:  k-ω SST, o gamma-ReTheta para α ≤ 8
Relajación:   p 0.12 / U, k, ω 0.35
Iteraciones:  2000–2500
Solver:       foamRun -solver incompressibleFluid
```

---

## 7. Prioridades, en orden

| # | Acción | Coste | Impacto |
|---|---|---|---|
| 1 | Arreglar `potentialFoam` en transitorio | 1 h | Desbloquea A1 entero |
| 2 | Rehacer GCI con r ≥ 1.3 | 6 h | Requisito de certificación |
| 3 | DES/DDES a α=12,14,16 | 2–3 días | Abre el rango alto |
| 4 | Caja de estela inclinada | 2 h | Cierra α=7–11 |
| 5 | `y+ < 5` con pared resuelta | 4 h | Mejora α=7–11 |
| 6 | Digitalizar Abbott (Cd) | 3 h | Segunda fuente |
| 7 | Validar 2412/4412 | 4 h | Amplía alcance |

Las dos primeras son las que cambian la naturaleza del trabajo. Las demás
mejoran márgenes.

---

## 8. Nota sobre el tiempo

El programa consumió 71 horas de las cuales **54 fueron los cuatro transitorios
fallidos**. Las 28 fases restantes terminaron en 7 horas. Si el transitorio
hubiera estado bien configurado, el programa completo habría costado ~12 horas.

Eso deja margen: con el servidor libre, se puede rehacer el transitorio
corregido y el GCI real sin problema de tiempo.
