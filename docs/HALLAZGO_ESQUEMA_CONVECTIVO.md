# El esquema convectivo de primer orden arruina el Cd

Medido el 2026-10-24 sobre el mismo caso, la misma malla y la misma
configuración. La única variable es el esquema de convección de la velocidad.

| Esquema | Cd | Error vs Ladson (0.00807) |
|---|---|---|
| `upwind` (1er orden) | 0.01758 | **+118 %** |
| `linearUpwind` (2º orden) | 0.01079 | **+34.5 %** |

NACA 0012, α = 0°, Re = 6×10⁶, malla de 44 145 celdas, y⁺ ≈ 57.

## Por qué ocurre

`upwind` de primer orden introduce difusión numérica en la dirección del flujo.
Esa difusión engorda artificialmente la estela. Una estela más gruesa produce
una depresión falsa detrás del perfil, y esa depresión se integra como arrastre
de presión.

El efecto es de un factor **1.6** en el Cd. Es el error individual más grande
encontrado en todo el proyecto, por encima del efecto de la ley de pared (que
resultó no influir) y del refinado de malla.

## Por qué pasó desapercibido

Durante la depuración de la divergencia a α = 8 se cambió a `upwind` para
estabilizar el solver. Eso resolvió la divergencia, pero introdujo este sesgo.

No se detectó porque **el Cl apenas se ve afectado**: depende de la circulación
global, que es robusta frente a la difusión. El Cd, en cambio, depende del
detalle de la estela y se dispara.

## Consecuencia

`linearUpwind` —o cualquier esquema de segundo orden limitado— es obligatorio
para validar arrastre. Con primer orden el Cd no es comparable con la
literatura, por bien resuelta que esté la malla.

## Estado con `linearUpwind` y la malla actual

```
α = 0°:   Cl = −0.0003  (correcto, perfil simétrico)
          Cd =  0.01085  vs 0.00807  →  +34.5 %
```

El 34.5 % restante es coherente con y⁺ ≈ 57, donde la subcapa viscosa se
modela en vez de resolverse.

## Opción A (y⁺ ≈ 1): bloqueada por la malla

Se intentó con 252 048 celdas y primera celda de 2×10⁻⁶. Tres configuraciones,
todas fallidas:

| Intento | Configuración | Resultado |
|---|---|---|
| 1 | `dt` adaptativo, maxCo 3 | dt → 2.6×10⁻¹⁷, inviable |
| 2 | `dt` fijo 10⁻⁶ | SIGFPE en GAMG |
| 3 | `adjustTimeStep no` | Cd = 0.76 en el primer paso |

Además el y⁺ no bajó de **2.25** con celda de 2×10⁻⁶; haría falta ~8×10⁻⁷.

**Causa:** la malla pasa de celdas de 2×10⁻⁶ junto a la pared a celdas de 0.4
en el farfield. Cinco órdenes de magnitud en un solo salto dejan el sistema mal
condicionado y GAMG no lo resuelve.

Para que la opción A sea viable hace falta rediseñar la transición de la capa
límite al farfield de forma gradual. Es trabajo de rediseño del generador, no
de ajuste de parámetros.
