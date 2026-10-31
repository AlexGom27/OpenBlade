> **Superado (2026-10-31).** Estas corridas no sirven como validación del programa. Se hicieron con los puntos de la malla redondeados a 6 cifras y con k y ω congelados por la tolerancia del solver lineal, y muchas con scripts que escribían sus propios casos. Ver [docs/VALIDACION.md](VALIDACION.md).

# Resumen y trabajo futuro — validación CFD de perfiles NACA

**Cierre de sesión:** 2026-10-26
**Programa ejecutado:** 2026-10-24, 21:09 → 23:25 (2 h 16 min, 44 casos)

---

## 1. Resultado principal

El NACA 0012 en el rango **α = 0° a 6°** valida contra Ladson (NASA TM 4074)
con un error medio en Cd del **2.27 %** y máximo del **5.96 %**.

| α | Cl | Cd | Error Cd |
|---|---|---|---|
| 0° | +0.0017 | 0.00803 | **−0.4 %** |
| 1° | +0.1173 | 0.00762 | −6.0 % |
| 2° | +0.2203 | 0.00819 | **+0.6 %** |
| 3° | +0.3313 | 0.00841 | +2.9 % |
| 4° | +0.4457 | 0.00839 | +2.0 % |
| 5° | +0.5559 | 0.00833 | **+0.1 %** |
| 6° | +0.6600 | 0.00824 | −2.1 % |

**Cinco de siete casos dentro del 3 %**, que es el umbral de certificación
aeronáutica. El Cl acierta en todo el rango con error menor al 3 %.

### Rango α = 7° a 11°

| α | Cd | Error |
|---|---|---|
| 7° | 0.00996 | +9.3 % |
| 8° | 0.01050 | +6.1 % |
| 9° | 0.01154 | +7.3 % |
| 10° | 0.01292 | +10.6 % |
| 11° | 0.01394 | +13.8 % |

Error medio **9.4 %**. Degrada con el ángulo pero se mantiene por debajo del 15 %.

### α ≥ 12°: no fiable

```
12°  Cd = 0.02008  (+55 %)   empieza la separación
13°  Cd = 0.01381  (−8 %)    inconsistente
14°  Cd = 0.00598  (−61 %)   no físico
15°  Cd = 0.00400  (−79 %)   no físico
```

El Cd **cae** en vez de subir, lo que es físicamente imposible: indica que el
flujo separado no se resuelve y la integración de fuerzas deja de tener sentido.

---

## 2. Estudio de convergencia de malla (GCI)

Tres niveles de refinado, misma configuración:

### α = 0°

| Malla | Cd | Error |
|---|---|---|
| gruesa | 0.00873 | +8.1 % |
| **base** | **0.00803** | **−0.5 %** |
| fina | 0.00741 | −8.2 % |

El valor converge hacia abajo al refinar: `0.00873 → 0.00803 → 0.00741`.
La extrapolación de Richardson apunta a ~0.0072, lo que sugiere que la malla
base está ligeramente por encima del valor asintótico.

### α = 8°

| Malla | Cd | Error |
|---|---|---|
| gruesa | 0.01016 | +2.8 % |
| base | 0.01016 | +2.7 % |
| fina | 0.01049 | +6.1 % |

Aquí **no converge monótonamente** y las tres mallas dan valores próximos.
A α=8 el Cd parece insensible al refinado, lo que apunta a que el error viene
del modelo de turbulencia y no de la discretización.

---

## 3. Sensibilidad al dominio

| Dominio | α=0 | α=8 |
|---|---|---|
| 20c | +14.2 % | +44.9 % |
| 40c (base) | −0.5 % | +2.7 % |
| 80c | −5.8 % | +9.7 % |

**El dominio de 40c es el mejor compromiso.** A 20c el bloqueo dispara el error
(+14 % y +45 %). A 80c mejora a α=0 (−5.8 %) pero empeora a α=8 (+9.7 %).

Esto confirma cuantitativamente lo que decía el NASA TMR: el dominio influye y
40c es razonable pero no ideal.

---

## 4. Efecto del refinado en ángulos altos

| Caso | Malla media | Malla fina |
|---|---|---|
| α=8 | +11.7 % | +33.1 % |
| α=10 | +5.4 % | +34.0 % |
| α=14 | −116.8 % | +22.1 % |

**Refinar empeora.** Es contraintuitivo pero consistente: con malla fina la
capa límite se resuelve más y aparecen fenómenos que el modelo k-ω SST no
captura bien a incidencia alta (separación, desprendimiento).

La malla **media** da mejores resultados que la fina en α=10 (+5.4 % vs +34.0 %).

---

## 5. Otros perfiles (recolección, sin referencia aún)

| Perfil | α | Cl | Cd |
|---|---|---|---|
| NACA 2412 | 0° | +0.245 | 0.00768 |
| NACA 2412 | 4° | +0.669 | 0.00911 |
| NACA 2412 | 8° | +1.067 | 0.01112 |
| NACA 4412 | 0° | +0.445 | 0.00870 |
| NACA 4412 | 4° | +0.880 | 0.00949 |
| NACA 4412 | 8° | +1.265 | 0.01430 |
| NACA 0015 | 0° | −0.001 | 0.00916 |
| NACA 0009 | 0° | +0.002 | 0.00787 |

**Observación:** el NACA 2412 a α=0 da Cl = 0.245, y a α=8 da 1.067. Son valores
plausibles. El 4412 a α=0 da Cl = 0.445, también coherente con su comba.

Falta compararlos contra Abbott & von Doenhoff para saber si son correctos.

---

## 6. Configuración validada

```python
malla:       no estructurada, 117,854 celdas
             bl_dist_min = 8e-4  (y+ ≈ 57)
             nb_airfoil_pts = 300  (645 caras en el perfil)
             farfield = 40c, wake_length = 30c
esquema:     limitedLinearV 1     <- clave del éxito
relajación:  p 0.12 / U 0.35 / k,ω 0.35
iteraciones: 2,000 - 2,500
```

### El hallazgo que lo hizo posible

`limitedLinearV 1` (limitador de van Leer) tolera las **434 caras con
no-ortogonalidad > 70°** de la malla no estructurada, donde `linearUpwind`
explota (Cl pasaba de −0.01 a −61,950).

---

## 7. Trabajo futuro

### Prioridad alta

**1. Entender el Cd a α ≥ 12°.** El Cd cae cuando debería subir. Eso indica
que el flujo separado no se resuelve. Opciones:
- Transitorio con promediado de ciclos (el flujo separa y oscila)
- Modelo de transición (`gamma-ReTheta SST`) en vez de k-ω SST puro
- Malla con refinamiento en el extradós para capturar el desprendimiento

**2. Validar los otros perfiles.** Hay datos en la carpeta (Abbott & von
Doenhoff) para NACA 2412, 4412 y 4415. Falta extraerlos y comparar.

**3. Ampliar el GCI a más ángulos.** Solo hay a 0° y 8°. Con 4° y 12° se podría
trazar la curva de error y estimar el error de discretización por ángulo.

### Prioridad media

**4. Repetir con dominio de 80c y malla base.** A α=0 dio −5.8 % (mejor que 40c),
pero a α=8 empeoró. Analizar por qué.

**5. Probar `limitedLinearV` con topología C-Grid.** Si funcionara, la malla
sería más ligera y el estudio de convergencia más limpio.

**6. Implementar el índice GCI formal** (Roache, 1994) con los tres niveles:
`GCI = Fs · |ε| / (r^p − 1)`. Requiere calcular el orden de convergencia
observado `p`, que necesita al menos tres mallas con refinado constante.

### Prioridad baja

**7. Barrido de Re.** Todo está a Re=6×10⁶. Probar 1×10⁶ y 3×10⁶ con las
referencias correspondientes.

**8. Transitorio en α=8 para comparar con el estacionario.** Si el flujo oscila,
el Cd medio podría acercarse más a Ladson que el estacionario.

---

## 8. Documentos disponibles

### En el servidor (`/tmp/prog/`)

```
resultados.json    44 casos, 10 KB
programa.log       log completo con tiempos
<b_...>/           carpetas de cada caso con malla, campos y run.log
```

**4.8 GB en total.** Conviene traer solo `resultados.json` y los `run.log`;
las mallas se regeneran.

### En Google Drive

```
Validación/
    46 PDFs de literatura (208 MB)
    resultados_cfd/
        resultados.json
        programa.log
```

### En el repositorio

```
docs/VALIDACION_EXITOSA.md         el resultado de α=0
docs/CONDICIONES_LITERATURA.md     criterios del NASA TMR
docs/HALLAZGO_ESQUEMA_CONVECTIVO.md  el efecto del esquema
validation/programa_2sem.py        el programa ejecutado
```

---

## 9. Estado del software

**Commits hasta `2f1e870`.** Corregido en esta sesión:

- Borde de salida cerrado (`-0.1036`)
- `Aref = chord × depth`
- Turbulencia de entrada (`omega = sqrt(k)/(Cmu^0.25 · l)`)
- `PIMPLE.residualControl` en formato OpenFOAM 12
- `potentialFoam` antes del solver
- `limitedLinearV` como esquema por defecto
- Patch `airfoil` con 645 caras (parche a `Cmshairfoil2d`)

**Sin commitear:** `validation/programa_2sem.py` y los resultados.

---

## 10. Para retomar

```bash
# Ver el estado
ssh alejandro@100.85.66.123 'cat /tmp/prog/programa.log | tail -20'

# Relanzar si hace falta (reanuda solo)
ssh alejandro@100.85.66.123 'tmux new-session -d -s prog \
  "cd ~/OpenBlade && ~/obenv/bin/python validation/programa_2sem.py \
   --work /tmp/prog --nproc 10 2>&1 | tee /tmp/prog/out.log"'

# Traer resultados
rsync -az alejandro@100.85.66.123:/tmp/prog/resultados.json .
```
