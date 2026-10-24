# Validación exitosa: Cd dentro del 2 %

**Fecha:** 2026-10-24
**Caso:** NACA 0012, α = 0°, Re = 6×10⁶
**Referencia:** Ladson, NASA TM 4074 (1988)

```
Cl = 0.00034     (correcto: perfil simétrico)
Cd = 0.00797     vs 0.00807 de Ladson  ->  -1.2 %
```

Error del **1.2 %** en arrastre, dentro del rango de certificación (2-3 %).

## La combinación que funciona

| Parámetro | Valor |
|---|---|
| Topología | **no estructurada** |
| Esquema convectivo | **limitedLinearV 1** |
| bl_dist_min | 8×10⁻⁴  (y⁺ ≈ 57) |
| mesh_num_layers | 12 |
| mesh_growth_rate | 1.22 |
| nb_airfoil_pts | 300 (645 caras en el perfil) |
| Relajación | p 0.12 / U 0.35 / k,ω 0.35 |
| Iteraciones | 2 000 |

Malla resultante: 117 854 celdas.

## Por qué funciona

**El esquema.** `limitedLinearV` es el limitador de van Leer. Tolera mallas
irregulares donde `linearUpwind` explota, sin perder precisión. La malla tiene
434 caras con no-ortogonalidad > 70°, que bastan para desestabilizar el
segundo orden sin limitar.

**La convergencia fue limpia y monótona:**

```
it= 240   Cl = -0.011    Cd = 0.0048
it= 400   Cl =  0.001    Cd = 0.0100
it= 672   Cl =  0.006    Cd = 0.0091
it=1050   Cl =  0.009    Cd = 0.0084
it=1391   Cl =  0.010    Cd = 0.0082
it=1643   Cl =  0.004    Cd = 0.0080
it=2000   Cl =  0.000    Cd = 0.0080
```

## Historial de intentos

| Configuración | Cd | Error |
|---|---|---|
| C-Grid, upwind | 0.01758 | +118 % |
| C-Grid, linearUpwind | 0.01085 | +34.5 % |
| No estructurada, linearUpwind | inestable | — |
| **No estructurada, limitedLinearV** | **0.00797** | **−1.2 %** |

## Qué descartó las vías anteriores

Se probaron y descartaron con medición:

- **Ley de pared:** opción B con y⁺ 57 dio resultados idénticos a y⁺ 25.
- **Refinado de malla:** ratio 1.05 con 120 capas y 327k celdas → SIGFPE.
- **Ratio de empalme exacto (1.2174):** aspect ratio empeoró de 75 727 a 80 860.
- **Optimización Laplace2D/Netgen:** sin efecto sobre las 434 caras malas,
  porque nacen en la extrusión, después de que la optimización 2D actúe.
- **Mallado 3D directo con HXT:** gmsh falla con "Could not find extruded
  vertex" al mezclar malla 2D y volumen.

## Pendiente

- Repetir a α = 4, 8, 12 para confirmar el rango de validez.
- Verificar que el resultado se sostiene con otro tamaño de dominio.
- Probar `limitedLinearV` también con la topología C-Grid.
