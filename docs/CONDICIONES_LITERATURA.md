# Condiciones de simulación según la literatura

Investigación de las condiciones que usan las fuentes autorizadas para el
NACA 0012, y comparación con lo que hace OpenBlade. Todo lo citado está tomado
de la documentación del NASA Turbulence Modeling Resource (TMR), que es la
referencia que la propia NASA usa para validar códigos CFD.

---

## 1. Fuente principal

**NASA Turbulence Modeling Resource (TMR)**, ahora en
`tmbwg.github.io/turbmodels/` (antes `turbmodels.larc.nasa.gov`).

Páginas consultadas:

- *2D NACA 0012 Airfoil Validation* — definición del caso y datos
- *Grids — NACA 0012 Airfoil Case* — mallas oficiales
- *SSTm Model Results* — resultados de referencia con k-ω SST
- *Notes on Running the Cases with CFD* — convenciones de ejecución

---

## 2. Condiciones del caso (NASA TMR)

| Parámetro | Valor oficial |
|---|---|
| Reynolds (por cuerda) | **6 × 10⁶** |
| Mach | **0.15** (incompresible) |
| Temperatura de referencia | **540 R = 300 K** |
| Viscosidad | **Ley de Sutherland** |
| Prandtl | 0.72 (laminar), 0.9 (turbulento) |
| Capa límite | **completamente turbulenta** |

### Sobre la velocidad del viento

La NASA **no especifica una velocidad en m/s**. Da número de Mach y Reynolds,
que definen el problema por completo. Con M = 0.15 y velocidad del sonido
estándar (340.3 m/s):

```
U = 0.15 × 340.3 = 51.0 m/s
ν = U·c/Re = 51.0 × 1 / 6e6 = 8.5 × 10⁻⁶ m²/s
```

**OpenBlade usa U = 15 m/s con ν = 2.5 × 10⁻⁶**, que da el mismo Re = 6×10⁶
pero un Mach de 0.044. Para flujo incompresible es equivalente — el Mach no
entra en las ecuaciones. La diferencia es cosmética, no física.

### Condiciones de turbulencia en la entrada

Los códigos de la NASA (CFL3D y FUN3D) usan:

```
Intensidad turbulenta:  0.052 %     (no 5 %)
Viscosidad turbulenta:  0.009 × ν   (relativa a la laminar)
```

**OpenBlade usa I = 5 %**, cien veces mayor. Para un caso de capa límite
forzada la turbulencia de entrada apenas influye (se disipa antes de llegar al
perfil), pero es una diferencia respecto a la referencia.

---

## 3. Malla oficial

| Característica | NASA TMR (malla más fina) |
|---|---|
| Topología | **C-grid** (igual que OpenBlade) |
| Dimensiones | **1793 × 513** puntos |
| Puntos en el perfil | **1025** |
| Puntos en la estela | 385 |
| Primera celda en pared | **y = 4 × 10⁻⁷** |
| **y⁺ resultante** | **0.1 – 0.2** |
| Extensión del dominio | ~500 cuerdas |

Mallas intermedias de la misma familia:

```
1793 × 513   (1025 puntos en perfil)
 897 × 257   ( 513 puntos en perfil)
 449 × 129   ( 257 puntos en perfil)
 225 ×  65   ( 129 puntos en perfil)
 113 ×  33   (  65 puntos en perfil)
```

**Son mallados estructurados, con elementos cuadriláteros** (en 2D) o
hexaédricos (en la versión 3D extrudada), no triangulares.

---

## 4. Comparación con OpenBlade

| Parámetro | NASA TMR | OpenBlade | Diferencia |
|---|---|---|---|
| Topología | C-grid | C-grid | ✅ igual |
| Puntos en perfil | 1025 | **645** | 1.6× menos |
| Puntos totales | 1793×513 = 919,809 | 101,790 | **9× menos** |
| Primera celda | 4 × 10⁻⁷ | **5 × 10⁻⁴** | **1250× mayor** |
| **y⁺** | **0.1 – 0.2** | **25 – 105** | **~200× mayor** |
| Elementos | cuadriláteros | cuadriláteros | ✅ igual |
| Intensidad turbulenta | 0.052 % | 5 % | 100× mayor |

---

## 5. El hallazgo que explica el Cd

**La NASA usa y⁺ ≈ 0.15. OpenBlade está en y⁺ ≈ 50.**

Esa es la diferencia esencial. Con y⁺ de 0.1-0.2 la subcapa viscosa está
**resuelta**: las ecuaciones se integran hasta la pared. Con y⁺ ≈ 50 se
**modela** con una ley de pared, y esa ley:

- asume perfil logarítmico puro (válido solo para y⁺ > 30 sin gradiente adverso)
- sobreestima el esfuerzo cortante cuando hay separación incipiente (α = 8)
- no captura el desprendimiento en el extradós

De ahí que la fricción aporte el 48 % del Cl (debería ser ~10 %) y el Cd salga
+330 % respecto a Ladson.

**No es un problema de modelo de turbulencia. Es de resolución de malla.**

---

## 6. Modelos de turbulencia en la literatura

La NASA publica resultados para ocho modelos en el mismo caso. Todos con la
misma malla de 897 × 257:

| Modelo | Tipo | Notas |
|---|---|---|
| **Spalart-Allmaras (SA)** | 1 ecuación | El más usado en aeronáutica |
| SA-RC | 1 ecuación | Con corrección de rotación |
| **SST / SSTm** | 2 ecuaciones | El que usa OpenBlade |
| SST-Vm | 2 ecuaciones | Variante con vorticidad |
| SSG/LRR-RSM-w2012 | 7 ecuaciones | Reynolds stress completo |
| Wilcox2006-klim | 2 ecuaciones | k-ω de Wilcox |
| K-kL-MEAH2015 | 2 ecuaciones | Modelo de transición |
| EASMko2003 | algebraico | Con efectos no lineales |
| K-ε-Rt | 2 ecuaciones | k-ε con corrección |

**Dato relevante:** con la misma malla y el mismo caso, los distintos modelos
dan resultados que difieren **menos del 1 % en sustentación y 5 % en arrastre**
(según la propia página del TMR). Es decir: la elección de modelo importa mucho
menos que la resolución de la malla.

Eso refuerza el diagnóstico: el problema de OpenBlade no se arregla cambiando
de k-ω SST a Spalart-Allmaras. Se arregla refinando la pared.

---

## 7. Recomendaciones concretas

### Para validar de verdad (y⁺ ≈ 1)

```
Primera celda:   2 × 10⁻⁶ m   (no 5 × 10⁻⁴)
Capas límite:    40-50
Growth rate:     1.05-1.08
Puntos perfil:   1025 (como el TMR)
Puntos totales:  ~500,000
Modelo pared:    nutLowReWallFunction
```

**Coste estimado:** con dt ∝ dx, pasar de 5e-4 a 2e-6 multiplica los pasos por
250. La corrida de α=8 pasaría de 45 min a **~8 días**. Inviable en un equipo
doméstico, viable en un clúster.

### Para uso ingenieril (y⁺ entre 30 y 300)

```
Primera celda:   ajustar para y⁺ ∈ [40, 150] en TODO el perfil
Modelo pared:    nutkWallFunction
```

**Problema actual:** el y⁺ varía entre 25 y 105 a lo largo del perfil. Ninguna
ley de pared cubre ese rango completo. Habría que refinar la malla lo
suficiente para que el mínimo también supere 30.

### Lo que no hay que hacer

Cambiar de modelo de turbulencia esperando arreglar el Cd. Los datos del TMR
demuestran que entre modelos hay 5 % de diferencia en arrastre, no 330 %.

---

## 8. Referencias

1. **Ladson, C.L.** *Effects of Independent Variation of Mach and Reynolds
   Numbers on the Low-Speed Aerodynamic Characteristics of the NACA 0012
   Airfoil Section.* NASA TM 4074, 1988.

2. **NASA Turbulence Modeling Resource.** 2D NACA 0012 Airfoil Validation
   Case. `https://tmbwg.github.io/turbmodels/naca0012_val.html`

3. **NASA TMR.** Grids — NACA 0012 Airfoil Case.
   `https://tmbwg.github.io/turbmodels/naca0012_grids.html`

4. **NASA TMR.** SSTm Model Results.
   `https://tmbwg.github.io/turbmodels/naca0012_val_sst.html`

5. **NASA TMR.** Notes on Running the Cases with CFD.
   `https://tmbwg.github.io/turbmodels/noteonrunning.html`

6. **Menter, F.R.** *Two-Equation Eddy-Viscosity Turbulence Models for
   Engineering Applications.* AIAA Journal 32(8):1598-1605, 1994.

7. **Spalart, P.R. & Allmaras, S.R.** *A One-Equation Turbulence Model for
   Aerodynamic Flows.* La Recherche Aérospatiale 1:5-21, 1994.

8. **Thomas, J.L. & Salas, M.D.** *Far-field boundary conditions for transonic
   lifting solutions.* AIAA Journal 24(7):1074-1080, 1986.
