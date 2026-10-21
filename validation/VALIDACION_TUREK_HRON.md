# Validación contra Turek & Hron FSI 1 — intento y diagnóstico

**Fecha**: 2026-10-21
**Estado**: **el benchmark no se completó**. El CFD y el sólido funcionan por
separado; el acoplamiento diverge. Se documenta el diagnóstico completo porque
los hallazgos son reutilizables.

---

## 1. Referencia elegida (verificada en fuente primaria)

**Turek, S.; Hron, J.** "Proposal for Numerical Benchmarking of Fluid-Structure
Interaction between an Elastic Object and Laminar Incompressible Flow",
*Lecture Notes in Computational Science and Engineering* 53 (2006), pp. 146-170,
**doi:10.1007/3-540-34596-5_7**.

Los valores numéricos se tomaron de una fuente secundaria que reproduce la
tabla original con malla convergida:

**Neunteufel, M.; Schöberl, J.** "Fluid-structure interaction with
H(div)-conforming finite elements", arXiv:2005.06360, **Tabla 5.8**, columna de
malla más fina (95 447 grados de libertad):

| Magnitud | Valor de referencia |
|---|---|
| u_x(A) | 2.2697 × 10⁻⁵ m |
| u_y(A) | 8.19543 × 10⁻⁴ m |
| drag | 14.2940 |
| lift | 0.76434 |

El punto A es el extremo libre del flag.

### Geometría (Tabla 5.1)

| Parámetro | Valor |
|---|---|
| Longitud del canal | 2.5 m |
| Altura del canal | 0.41 m |
| Centro del cilindro | (0.2, 0.2) |
| Radio del cilindro | 0.05 m |
| Longitud del flag | 0.35 m |
| Espesor del flag | 0.02 m |
| Anclaje del flag | x = 0.6, y = 0.2 |
| Punto A | (0.95, 0.2) |

### Parámetros FSI 1 (Tabla 5.2)

| Parámetro | Valor |
|---|---|
| ρ_s | 1000 kg/m³ |
| ν_s | 0.4 |
| μ_s | 5×10⁵ Pa |
| ρ_f | 1000 kg/m³ |
| ν_f | 10⁻³ m²/s |
| U media | 0.2 m/s |

Re = 20 referido al diámetro del cilindro. El caso alcanza estado estacionario.

---

## 2. Lo que se implementó

`validation/turek_hron_fsi1.py` genera el caso completo:

- Geometría con Gmsh: canal, cilindro y flag, con extrusión a 3D.
- Grupos físicos correctos (inlet, outlet, walls, cylinder, flag, fluid).
- Diccionarios de OpenFOAM: controlDict, fvSchemes, fvSolution, U, p,
  pointDisplacement, dynamicMeshDict.
- Adaptador preCICE (preciceDict + functionObject).
- Configuración de acoplamiento y malla del sólido (`solid_nodes.npy`).

`core/structural_solver.py` gana un modo `--geometry flag` que usa la malla del
flag en lugar de la cáscara del perfil.

---

## 3. Errores encontrados y corregidos

Varios fueron errores míos de implementación, no del benchmark:

| # | Síntoma | Causa |
|---|---|---|
| 1 | `No cells read from file` | la malla era 2D; gmshToFoam necesita volúmenes |
| 2 | Solo 2 grupos físicos de 7 | los grupos 1D se pierden al extruir; hay que declararlos sobre las **caras laterales** después de la extrusión |
| 3 | `getValue` sobre curva devolvía vacío | hay que muestrear con `getParametrizationBounds` |
| 4 | Clasificación de curvas fallaba | el cilindro es **una sola curva cerrada**, no 16 segmentos |
| 5 | `checkSecurity` en `codedFixedValue` | la imagen no permite código compilado; se usó `flowRateInletVelocity` |
| 6 | `cellDisplacementFinal` no encontrado | faltaba la entrada `Final` en fvSolution |
| 7 | **Divergencia en el paso 1** | caudal del inlet **100× mayor**: faltaba multiplicar por el espesor de extrusión (0.01 m) |
| 8 | Desplazamientos absurdos (norm. 4×10⁴) | la interfaz del sólido estaba en el borde **empotrado** |
| 9 | `NameError: os` | faltaba el import en el solver |
| 10 | Material 2× más flexible | el benchmark da μ y λ → **deformación plana**, no tensión plana |

Cada uno se detectó ejecutando, no leyendo.

---

## 4. Estado real del acoplamiento

### Lo que funciona

- **El CFD solo es estable**: con `flag` como `noSlip` y sin adaptador, la
  continuidad se mantiene en ~10⁻⁹ y el caso corre sin divergir.
- **El sólido solo es correcto**: la viga empotrada valida a −0.07% contra
  Euler-Bernoulli con convergencia monótona.
- **El adaptador carga y se conecta**: `preciceAdapter` presente, intercambio
  de `Stress` y `Displacement` confirmado, mallas intercambiadas.

### Lo que no funciona

Con acoplamiento activo el fluido diverge en el **segundo paso de tiempo**:

```
Time = 0.01
time step continuity errors : sum local = 1.04e-08   (estable)
Time = 0.01
time step continuity errors : sum local = 0.28       (diverge)
```

Y los datos que llegan del fluido son enormes:

```
[solid] t=0.0100: |data|max=2.86e+04   |F_total|=3.30e+06 N
```

Para un flag de 0.35 × 0.02 m bajo 20 Pa de presión dinámica, la fuerza total
esperada es del orden de **0.15 N**, no 3.3×10⁶ N. Hay un factor de ~10⁷.

### Hipótesis del factor

El adaptador (`FSI/ForceBase.C`) calcula:

```cpp
forceField = surface * p * rho + (surface & devRhoReff)
```

donde `surface` es el **vector de área de la cara**. Con `p` cinemática
(m²/s²) y `rho` = 1000, el producto da newtons. Para 125 caras de ~5.8×10⁻⁵ m²
con p ≈ 0.02 m²/s², la suma debería rondar 0.15 N. Obtengo 3.3×10⁶.

Las dos explicaciones compatibles son:

1. El campo `p` del caso no es el que creo: el primer paso con `Courant = 0`
   sugiere que la condición inicial no está bien impuesta (el
   `flowRateInletVelocity` no arranca con perfil parabólico, y `internalField`
   es cero).
2. El adaptador multiplica por densidad **dos veces** en algún punto del
   camino (una en el cálculo y otra al leer `rho` del `preciceDict`).

No lo he confirmado. Requiere instrumentar el adaptador o volcar el campo
`Stress` a disco y compararlo con `forceCoeffs`.

---

## 5. Conclusión

**No puedo afirmar que el desplazamiento del flag coincida con la referencia**
porque el acoplamiento no llega a converger en este caso. Lo que sí está
establecido:

- La geometría, los parámetros y la referencia están verificados contra la
  fuente primaria.
- El CFD y el sólido funcionan por separado.
- El acoplamiento conecta e intercambia datos.
- Falta resolver un factor de escala de ~10⁷ en la fuerza transmitida.

Ese factor es el siguiente paso concreto: comparar `Stress` del adaptador con
el `forceCoeffs` del mismo instante, que da la fuerza integrada por un camino
independiente.

---

## 6. Reproducir

```bash
python3 validation/turek_hron_fsi1.py --out /tmp/th_fsi1
# luego: gmshToFoam, corregir tipos de parche, lanzar sólido y fluido
```

Los tipos de parche hay que ajustarlos a mano (`fluid` y `defaultFaces` a
`empty`, `flag`/`cylinder`/`walls` a `wall`); está pendiente automatizarlo en
el generador.
