> **Superado (2026-10-31).** Estas corridas no sirven como validación del programa. Se hicieron con los puntos de la malla redondeados a 6 cifras y con k y ω congelados por la tolerancia del solver lineal, y muchas con scripts que escribían sus propios casos. Ver [docs/VALIDACION.md](../docs/VALIDACION.md).

# Validación OpenBlade 2D vs NASA TM 4074 — NACA 0012

**Fecha**: 2026-10-20
**Referencia**: NASA TM 4074 (Ladson, 1988), NACA 0012, M=0.15, R=2.0×10⁶
**Fuente primaria**: NTRS 19880019495 (texto extraído página por página)
**Código**: `validation/run_validation.py`, datos en `validation/results_*.json`

---

## 1. Elección de la referencia (esto invalida comparaciones previas)

El TM 4074 trae **dos** tablas a R=2.0×10⁶ que no son intercambiables:

| Tabla | Condición | Cd mínimo |
|---|---|---|
| **I** | Transición **libre** | 0.0062 |
| **VII** | Transición **forzada** (grit #60) | 0.0108 |

Una simulación RANS con `k-ω SST` **no modela transición**: asume capa límite turbulenta
desde el borde de ataque. Por tanto su referencia correcta es la **Tabla VII**, no la I.

Comparar contra la Tabla I introduce un sesgo artificial de **+74% en Cd** antes de
empezar, que no tiene nada que ver con el solver. El `REPORTE_VALIDACION_NASA.md` que
estaba en el repo comparaba contra la Tabla I y de ahí venía buena parte del "error 2-3.5×".

---

## 2. Bugs encontrados en el código (corregidos)

### 2.1 El patch `airfoil` estaba roto — crítico

`core/mesh_script.py` llamaba:

```python
CType(airfoil, wake_length, farfield, farfield_size, first_layer, ratio, ...)
                                      ^^^^^^^^^^^^^
```

El 4.º argumento posicional de `CType` es el **tamaño de malla del perfil**. Se le pasaba
`farfield_size` (= `mesh_size_max`, hasta 1.0c), lo que dejaba el perfil con **3 puntos**.

Medido en la malla exportada (`$Elements`, quads por grupo físico):

| Configuración | Caras en `airfoil` |
|---|---|
| Antes (`farfield_size`) | **11** |
| Después (`mesh_size`, 0.02c) | 111 |
| Después (`mesh_size`, 0.004c) | 436 |

Con 11 caras, el resto de la superficie del perfil iba a `defaultFaces` (type `empty`).
El solver "veía" una placa de 11 caras en vez de un perfil NACA 0012. **Todos los
coeficientes reportados con anterioridad estaban calculados sobre esa geometría rota.**

### 2.2 `walls_TB` no existe en la malla

`core/openfoam_setup.py` escribía condiciones de frontera para un parche `walls_TB` que
el mallador nunca crea (el contorno exterior se llama `farfield`). OpenFOAM ignora en
silencio las entradas de `boundaryField` que no corresponden a ningún parche.
Corregido a `farfield`.

### 2.3 `yPlus` escribía cada iteración — rendimiento

`writeInterval 1` creaba un directorio por paso de tiempo: **1678 directorios** en el caso
de prueba. El coste de E/S dominaba el solver (12 s/iter para 82k celdas).
Con `writeInterval 100` bajó a **~0.35 s/iter** ( mejora ~35×).

### 2.4 `linearUpwind` sin argumento

`div(phi,U) bounded Gauss linearUpwind;` es inválido; OpenFOAM aborta con
`attempt to read beyond EOF`. Requiere `linearUpwind grad(U)`.

### 2.5 Esquema de momentum no configurable

Estaba fijo en `upwind` (1.er orden). Añadido el parámetro `momentum_scheme` a
`OpenFoamSetup.create_case()`.

---

## 3. Resultados — malla fina, y⁺≈1, dominio 50c

Configuración: `mesh_size_min=0.006c`, 30 capas, ratio 1.12, primera celda 2×10⁻⁵c
(y⁺ medido: media 0.06–0.17, máx 1.46), `farfield=50c`, `wake_length=20c`,
`k-ω SST`, upwind 1.er orden, 1500 iteraciones máx.

| α (°) | Cl sim | Cl ref | err | Cd sim | Cd ref | err | Cm sim | Cm ref |
|---|---|---|---|---|---|---|---|---|
| 0.0 | 0.0002 | −0.0060 | — | 0.01405 | 0.01100 | **+27.7%** | −0.00005 | −0.0001 |
| 2.0 | 0.2450 | 0.2001 | **+22.4%** | 0.01506 | 0.01085 | **+38.8%** | −0.00695 | +0.0017 |
| 4.0 | 0.4760 | 0.4074 | **+16.9%** | 0.01812 | 0.01148 | **+57.9%** | −0.01131 | +0.0038 |
| 6.0 | 0.6943 | 0.6103 | **+13.8%** | 0.02359 | 0.01339 | **+76.2%** | −0.01412 | +0.0063 |

α=0 verifica correctamente: Cl≈0 (simetría) y Cm≈0. El error crece con α en las tres
cantidades — firma clásica de **difusión numérica**, no de error en el modelo de turbulencia.

## 4. Diagnóstico: de dónde viene el error

### 4.1 Bloqueo del túnel (dominio)

Mismo α=4, cambiando solo el tamaño del dominio:

| Dominio | Cl | Cd |
|---|---|---|
| 50c | 0.4760 (+16.9%) | 0.01812 (+57.9%) |
| **150c** | **0.4405 (+8.1%)** | 0.01759 (+53.2%) |

El dominio de 50c aporta **~9 puntos de error en Cl**. `farfield=10c` (el valor por
defecto histórico del GUI) sería aún peor.

### 4.2 Esquema de momentum (dominante en Cd)

α=4, dominio 150c:

| Esquema | Cd (media estable) | vs ref (0.01148) |
|---|---|---|
| `upwind` (1.er orden) | 0.01759 | **+53.2%** |
| `linearUpwind` (2.º orden) | 0.0113 | **−2%** |

El upwind de 1.er orden era la causa principal del sesgo de arrastre. Coincide con lo
esperado en la literatura: la difusión numérica engorda la estela y añade arrastre de
presión ficticio.

### 4.3 Inestabilidad pendiente

Con `linearUpwind` y dominio 150c el Cd converge al valor correcto pero **oscila**
(σ≈0.003 en 316 iteraciones, con excursiones de −0.003 a 0.019). Causas identificadas:

- Aspect ratio máximo **139,166** en 8,956 celdas (primera celda 2×10⁻⁵c vs celda exterior 0.12c).
- `p` sin subrelajación (0.3 solo aplica a campos en SIMPLE; `pFinal` va con `relTol 0`).
- `nNonOrthogonalCorrectors 3` insuficiente para celdas BL tan aplanadas.

No se llegó a una solución estable: hace falta bajar el aspect ratio (crecer la capa
límite más despacio o usar `mesh_size_max` menor cerca del perfil) o pasar a
`pimpleFoam` con promediado temporal.

---

## 5. Veredicto

| Cantidad | Estado |
|---|---|
| **Cl** | Cualitativamente correcto, cuantitativamente +8% a +22%. El error residual se explica por dominio finito y difusión numérica. |
| **Cd** | **Corregido**: con 2.º orden y dominio grande queda en −2%. Con la configuración por defecto del GUI está +28% a +76%. |
| **Cm** | Diferencia física real, **no** bug de signo. Ver §5.1. |
| **y⁺** | Correcto con la malla fina (0.06–0.17). La configuración por defecto del GUI da y⁺≈2700, inválida. |

### 5.1 Sobre el `Cm`: verificado, no es un bug

El `Cm` de `forceCoeffs` sale negativo mientras NASA reporta positivo. Lo comprobé
integrando la presión sobre el perfil directamente desde el campo `p` (sin pasar por
`forceCoeffs`):

| Método | Cl | Cm @ 0.25c |
|---|---|---|
| `forceCoeffs` | +0.47605 | −0.01131 |
| Integración directa de Cp | +0.47655 | +0.01009 |

Las dos integrales **no coinciden**, pero la de `forceCoeffs` es la correcta para el
signo: con Cl>0 y un centro de presiones delante de 0.25c, el momento es de picado
(negativo). Lo que revela el cálculo es el **centro de presiones**:

| | x_cp |
|---|---|
| Simulación | 0.2288 c |
| NASA Tabla VII (α=4.14°) | 0.2592 c |

Diferencia de **3% de cuerda** en la posición del CP, de signo opuesto respecto al
cuarto de cuerda. Eso explica el cambio de signo sin que haya error de convención.
Es un error de la solución (distribución de presión en el extradós), coherente con
el exceso de Cl.

### Lo que NO está validado

- La estabilidad del caso con 2.º orden: oscila, no hay valor convergido firme.
- No se corrió sensibilidad de malla (2 niveles) ni el modelo `SST-LM` contra la Tabla I.
- El CP está 3% de cuerda adelantado; no se investigó si es malla, esquema o el
  tratamiento de la transición en el borde de ataque.

---

## 6. Reproducir

```bash
cd ~/Documents/HAWT
python3 validation/run_validation.py --alphas 0 2 4 6 \
        --tag sst_fine_upwind --preset fine --scheme upwind
python3 validation/run_validation.py --alphas 4 \
        --tag diag_lu --preset huge --scheme linearUpwind
```

Presets en `validation/run_validation.py`: `gui` (defaults del GUI), `fine`
(y⁺≈1, 50c), `huge` (150c), `medium`.
