> **Superado (2026-10-31).** Estas corridas no sirven como validación del programa. Se hicieron con los puntos de la malla redondeados a 6 cifras y con k y ω congelados por la tolerancia del solver lineal, y muchas con scripts que escribían sus propios casos. Ver [docs/VALIDACION.md](VALIDACION.md).


---

# Refinado de malla: cuatro intentos, ninguno mejora

Después de identificar el esquema convectivo como causa principal del Cd alto,
se intentó refinar la malla siguiendo el NASA TMR. Todos los intentos fallaron.

## Referencia: qué hace el NASA TMR

Malla más fina del caso de análisis numérico:

    puntos totales:        7 169 x 2 049  (14.7 M)
    primera celda en pared: 1 x 10^-7
    ratio de crecimiento:   1.02
    puntos en superficie:   4 097
    puntos en estela:       1 537
    dominio:                500 c

## Lo que probó OpenBlade

| Intento | Celdas | ratio | capas | Resultado |
|---|---|---|---|---|
| 1 | 71 262 | 1.12 | 30 | converge, Cd +118 % |
| 2 | 71 262 | 1.2174 | 30 | aspect ratio empeora (80 860) |
| 3 | 326 952 | 1.05 | 120 | SIGFPE en iteración 25 |
| 4 | 71 262 (bl=2e-5) | 1.12 | 30 | converge con upwind (+114 %), **diverge con linearUpwind** |

## Por qué el ratio pequeño no basta

El salto de escala total es:

    mesh_size_max / bl_dist_min = 0.5 / 2e-5 = 25 000x

Con 120 capas y ratio 1.05 la progresión llega a 2e-5 x 1.05^120 = 7e-3.
Queda un salto de 0.5 / 0.007 = 71x hasta el campo lejano.

Cubrirlo entero exige ~220 capas y unos 2 000 puntos en la dirección normal,
como la malla NASA. Eso son millones de celdas, fuera del alcance de este equipo.

## Conclusión

El cuello de botella es la **topología**, no los parámetros. El C-Grid proyecta
la capa límite radialmente sobre 50 cuerdas, lo que fuerza un gradiente de
escala que ningún ajuste de ratio/capas resuelve sin llegar a millones de celdas.

Para validar arrastre de verdad hay que cambiar de topología: capa límite
confinada alrededor del perfil y transición isotrópica al exterior (malla no
estructurada u O-grid con bloque exterior independiente).

## Estado utilizable hoy

    alpha = 0, malla gruesa, linearUpwind:  Cd +34.5 %
    alpha = 4, malla gruesa, linearUpwind:  Cd +0.6 %   <- mejor caso
    Cl en todos los casos:                  -4 % a +11 %

Suficiente para uso ingenieril en el rango bajo de incidencia. No para
certificación, que exige Cd dentro del 2-3 %.
