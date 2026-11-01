# Validación de OpenBlade

Todo lo de este documento salió del programa: malla y caso generados en la Mac, cálculo con OpenFOAM 12 en los servidores, y veredicto y ficha de cada paquete. Las campañas anteriores al 2026-10-31 no sirven como validación (§8).

## 1. Resumen

| Qué | Estado |
|---|---|
| Cl del NACA 0012, Re=6e6, de 4° a 17° | A menos de 1.7 % de Ladson, y de 1.2 % de 6° a 17°. A 2° difiere 0.010 (+4.9 %) |
| Cd del NACA 0012 en la malla por defecto | De −4.1 a +4.0 % frente a Ladson hasta 12°, dentro de su banda de malla (de ±7 a ±13 %); de +10 a +15 % de 14° a 17° |
| Cd frente a NASA TMR, malla extrapolada | −1.0 % a 10°. A 15°, +2.1 %, con un orden bajo que lo hace poco firme (§6) |
| Pérdida | **No la predice.** Ladson cae a Cl≈1.0 a 18°; SST da 1.60 |
| Reproducibilidad entre máquinas | Mismo paquete y procesos, fuerzas idénticas byte a byte en Local (Docker) y en un servidor, en una prueba corta de 300 iteraciones |
| Perfil con curvatura (NACA 4412) | Comprobado el signo de Cm y Cp frente a experimento; sin tolerancias |
| Transitorio | Estable en un caso laminar. A Re alto con y+<1 **no está validado** (§7) |
| Mallas oficiales de TMR | 449×129 no es practicable; 225×65 corre pero Cd oscila (§6) |
| Banco de validación | 35 de 40 comprobaciones; las 5 restantes declaradas (§5) |

## 2. Cómo repetirlo

```bash
python3 -m core.cli polar --maquinas usuario@a:10:2,usuario@b:9:2 --angulos 0,2,4,6,8,10,12,14,15,16,17,18 --gci 0,10,15 --salida polar reynolds=6e6
```

```bash
python3 -m core.cli banco --maquinas usuario@a:7:2 --salida banco
```

```bash
python3 -m core.cli control --hosts usuario@a,usuario@b --procesos 8
```

## 3. Condiciones

NACA 0012 de cuerda 1, Re=6×10⁶, U=15 m/s, flujo incompresible. Tu=0.052 % y νt/ν=0.009, los de TMR. k-ω SST con la pared resuelta. Malla C propia, anidada, fija en todos los ángulos (se gira el flujo), de radio 200 cuerdas:

| Nivel | Puntos | Celdas | y+ medio a 10° |
|---|---|---|---|
| 1 | 225×65 | 14 336 | 1.46 |
| 2, por defecto | 449×129 | 57 344 | 0.69 |
| 3 | 897×257 | 229 376 | 0.34 |

**Referencias.** Ladson, NASA TM 4074, Re=6×10⁶, grano 80, M=0.15. NASA TMR, *2D NACA 0012 Airfoil Validation*: CFL3D, FUN3D y NTS en 897×257, M=0.15.

**Dos diferencias de modelo que no se corrigen en las tablas:**
- Las referencias son a M=0.15 y aquí M→0. Prandtl-Glauert da 1/√(1−0.15²)=1.011: del orden de lo que falta en Cl frente a TMR.
- TMR publica SSTm (Menter 1994, limitador con vorticidad y producción μtS²). OpenFOAM 12 usa la variante de 2003, con limitador de deformación y producción limitada a 10.

## 4. Polar (nivel 2)

La banda es la de malla, calculada con GCI a 0°, 10° y 15° e interpolada entre ellos. Fuera de esos ángulos no se da banda.

| α | Veredicto | Cl | ± | Ladson | Dif. | Cd | ± | Ladson | Dif. |
|---|---|---|---|---|---|---|---|---|---|
| 0 | CONVERGIDO | 0.0000 | 0.0000 | −0.0072 | | 0.00784 | 0.00057 | 0.00809 | −3.2 % |
| 2 | CONVERGIDO | 0.2173 | 0.0017 | 0.2071 | +4.9 % | 0.00794 | 0.00062 | 0.00816 | −2.6 % |
| 4 | CONVERGIDO | 0.4345 | 0.0034 | 0.4272 | +1.7 % | 0.00829 | 0.00069 | 0.00823 | +0.7 % |
| 6 | CONVERGIDO | 0.6504 | 0.0051 | 0.6448 | +0.9 % | 0.00891 | 0.00079 | 0.00882 | +0.9 % |
| 8 | CONVERGIDO | 0.8615 | 0.0067 | 0.8557 | +0.7 % | 0.00988 | 0.00094 | 0.01028 | −3.9 % |
| 10 | CONVERGIDO | 1.0656 | 0.0084 | 1.0586 | +0.7 % | 0.01142 | 0.00115 | 0.01191 | −4.1 % |
| 12 | CONVERGIDO | 1.2584 | 0.0310 | 1.2493 | +0.7 % | 0.01374 | 0.00181 | 0.01321 | +4.0 % |
| 14 | CONVERGIDO | 1.4301 | 0.0536 | 1.4250 | +0.4 % | 0.01732 | 0.00282 | 0.01520 | +14.0 % |
| 15 | CONVERGIDO | 1.5010 | 0.0649 | 1.4993 | +0.1 % | 0.01989 | 0.00356 | 0.01800 | +10.5 % |
| 16 | oscila | 1.5579 | | 1.5647 | −0.4 % | 0.02335 | | 0.02090 | +11.7 % |
| 17 | oscila | 1.5970 | | 1.6160 | −1.2 % | 0.02828 | | 0.02460 | +15.0 % |
| 18 | oscila | 1.6047 | | ≈1.0, en pérdida | | 0.03641 | | 0.188 | |

Ladson está interpolado entre sus ángulos medidos. «Oscila» es NO CONVERGIDO con media estable: Cd varía 1.1–1.5 % en las últimas 500 iteraciones, y se da su media. α=18 arrancó de α=17; los demás, del flujo potencial.

## 5. Banco de validación

Ocho paquetes en el nivel 2, todos CONVERGIDOS: **35 de 40 comprobaciones cumplidas**. Tolerancias en `core/bench.py`; informe en `validation/resultados/banco_validacion.pdf`. Lo que no cumple:

| Caso | Comprobación | Medido | Tope | Causa |
|---|---|---|---|---|
| SST, α=10 | Cd frente a TMR | −8.4 % | ±5 % | Malla: −4.0 % en el nivel 3 y −1.0 % extrapolado |
| SST, α=15 | Cd frente a TMR | −10.7 % | ±10 % | Malla: −6.8 % en el nivel 3 |
| SA, α=15 | Cp frente a CFL3D, RMS | 0.110 | 0.10 | Sin estudiar; pico −10.80 frente a −11.16 |
| SA, α=15 | Cf frente a CFL3D, RMS | 0.0020 | 0.0015 | Sin estudiar |
| Dominio 40c, α=10 | Cd frente a 200c | +5.8 % | ±2 % | El dominio de 40c es pequeño; 500c cambia −1.3 % |

Todas las comparaciones con Ladson cumplen. SST frente a TMR, Cl: −1.3 % a 10° y −0.5 % a 15°. SA: Cl −1.6 y −1.5 %, Cd −3.2 y −3.9 %.

## 6. Estudio de malla

Cada coeficiente con tres niveles anidados, r=2 y factor de seguridad 1.25; si el orden no es creíble, tres veces el mayor salto, sin extrapolar. El nivel 1 oscila poco a 10° y 15°, con media estable, y se usa su media.

| α | | Nivel 1 | Nivel 2 | Nivel 3 | Convergencia | Extrapolado | Banda nivel 3 | TMR (media) |
|---|---|---|---|---|---|---|---|---|
| 0 | Cd | 0.00764 | 0.00784 | 0.00800 | no asintótica | | ±7.2 % | 0.00809 |
| 10 | Cl | 1.0671 | 1.0656 | 1.0628 | no asintótica | | ±0.8 % | 1.0794 |
| 10 | Cd | 0.01008 | 0.01142 | 0.01197 | orden 1.30 | 0.01234 | ±3.9 % | 0.01247 |
| 15 | Cl | 1.4794 | 1.5010 | 1.4969 | oscilatoria | | ±4.3 % | 1.5092 |
| 15 | Cd | 0.01864 | 0.01989 | 0.02076 | orden 0.53 | 0.02274 | ±11.9 % | 0.02227 |

**El Cd bajo frente a TMR es sobre todo de la malla.** En el nivel 2 está 8.4 % por debajo a 10° y 10.7 % a 15°. En el nivel 3, 4.0 % y 6.8 %. Extrapolado queda a −1.0 % y +2.1 %. A 15° el orden medido, 0.53, está justo sobre el mínimo aceptado, así que ese +2.1 % es poco firme: con orden 1 el extrapolado sería 0.02163 (−2.9 %), y con orden 2, 0.02105 (−5.5 %). Para Cl basta el nivel 2; para Cd a menos de 5 % de TMR a 10° hace falta el nivel 3.

**Arranque desde la malla anterior.** Los estudios de malla arrancan cada nivel de la solución del anterior:

| 897×257, α=10 | Iteraciones | Cl | Cd |
|---|---|---|---|
| Desde el flujo potencial | 34 001 | 1.0619 | 0.01200 |
| Desde el nivel 2 | 7 001 | 1.0628 | 0.01197 |

Cambiar el arranque mueve el extrapolado de Cd a 10° de 0.01242 a 0.01234 (0.6 %), menos que su banda de ±3.9 %.

A α=15 en 897×257, desde el flujo potencial el cálculo revienta hacia la iteración 1400. Desde α=10 en la misma malla queda atrapado en un ciclo grande (Cl de 1.28 a 1.43). Desde el nivel 2 converge en 8000 iteraciones. En 449×129, α=15 desde α=14 da lo mismo que en frío (Cd 0.019875 y 0.019893), en menos iteraciones. El rescate por ángulo vecino se limita a 2°.

**Mallas oficiales de TMR.**
- 449×129: 60 s por iteración con la máquina cargada, por celdas de aspecto 3×10⁷ que hacen que GAMG tarde 170 iteraciones; a la iteración 742 las fuerzas seguían lejos de su valor. No es practicable.
- 225×65: llega a 20 000 iteraciones con Cl 1.0797 y Cd 0.00965, oscilando 1.6 %. La malla propia del mismo tamaño da 1.0671 y 0.01008.

## 7. Otras comprobaciones

**Simetría (M).** α=±4, nivel 1: Cl +0.43752 y −0.43751, Cd 0.00787 en ambos, Cm ±0.0026.

**Perfil con curvatura (M).** NACA 4412, nivel 2, Re=6×10⁶: α=0 da Cl 0.455, Cd 0.00831, Cm −0.098; α=8 da Cl 1.280, Cd 0.01172, Cm −0.088. Frente a Coles y Wadcock (α=13.87, Re=1.52×10⁶): Cl 1.638 oscilando, Cp RMS 0.20 en extradós y 0.15 en intradós, pico −7.04 frente a −6.21. Sin tolerancia fijada.

**Otros modelos a α=4 (M).** Solo comprueban que corren desde el programa. Ninguno está validado.

| Modelo | Malla | Cl | Cd | Estado |
|---|---|---|---|---|
| SST | nivel 2 | 0.4345 | 0.00829 | CONVERGIDO |
| k-ω | nivel 1 | 0.4413 | 0.00848 | oscila 1.1 % |
| SST-LM, con transición | nivel 1 | 0.4314 | 0.00526 | oscila 1.6 % |
| k-ε, y+=46, ley de pared | nivel 2 | 0.4560 | 0.00531 | oscila 3.4 % |

k-ε da Cd 36 % por debajo de SST: no se recomienda para coeficientes. Laminar a Re=5000, α=0: Cd 0.0543, CONVERGIDO.

**Salida (M).** Laminar, Re=1000, α=30: el reflujo en la esquina superior de la salida crecía de Ux=−23 m/s en t=0.8 s a −309 en t=2.2 s, y Cl acababa en −23. Con `inletOutlet` llega a t=4 s desprendiendo vórtices. En estacionario no cambia nada donde el flujo sale: Cd 0.00764 a 0° y Cl 1.4794, Cd 0.01864 a 15°, como antes.

**Transitorio a Re=6×10⁶ con y+<1: no validado (M).** Nivel 1, α=18:

| Arranque | Courant máximo | Resultado |
|---|---|---|
| Flujo potencial | 100 | Revienta en t≈0.015 s |
| Flujo potencial | 30 | Revienta en t≈0.04 s, también con la salida nueva |
| Flujo potencial | 10 | Estable hasta t=0.1 s, 1.5 cuerdas; Cl sube de 0.61 a 1.04 |
| Campo estacionario | 30 | Revienta en t≈0.0023 s |
| Campo estacionario | 10 | Fuerzas ruidosas, Δt≈2.5×10⁻⁶ s; con y sin copiar `phi` |

El ruido con la capa límite desarrollada indica que el acoplamiento presión-velocidad no aguanta esos Δt. Estas pruebas usan el bloque PIMPLE sin subir (`nOuterCorrectors 2`, sin relajación). A α≤18 el estacionario no diverge, así que la polar no ha necesitado URANS.

**Parada y veredicto.** La deriva se mide entre los dos últimos quintos de la corrida. Reproducido sobre historias reales, la parada temprana queda a menos de 0.02 % de corridas mucho más largas a 10° y 15°, y a 0.1 % a 0°. Con ventanas fijas de 500 iteraciones, 897×257 parecía convergida con Cd aún 1 % alto.

**Reproducibilidad.** Local (Docker emulado) y `openblade2`, 2 procesos y 300 iteraciones: fuerzas idénticas, md5 `6086045a3719`. Es una prueba corta, y el resultado vale para el mismo número de procesos. Un clon nuevo con un entorno nuevo da la misma malla: sha256 `c2ed1a996956` en el nivel 2, con numpy 2.4.0 y 2.4.6.

## 8. Por qué lo anterior no sirve

Las corridas previas al 2026-10-31 tienen estos defectos, y sus documentos llevan el aviso «Superado»:
1. `writePrecision 6` redondeaba los puntos de la malla a 6 cifras al convertirla: no ortogonalidad de 85.9° en una malla de 39°.
2. La tolerancia 1e-6 del solver lineal congelaba k y ω: «No Iterations 0» y fuerzas estables falsas, con veredicto CONVERGIDO.
3. Muchas salían de scripts que escribían sus propios casos: lo validado no era lo que corre la ventana. Cada servidor generaba su propia malla, y de ahí la discrepancia entre servidores.

## 9. Límites declarados

Pendiente: repetir el caso de control con esta malla en los dos servidores.


- No predice la pérdida: SST sigue a Cl 1.60 a 18°, donde el experimento cae a 1.0.
- A partir de 14° Cd está 10–15 % por encima de Ladson.
- Nivel 2 sirve para Cl. Para Cd a menos de 5 % de TMR, nivel 3.
- La banda de malla de Cl a 15° es grande (±4.3 %) porque el nivel 1 es pobre ahí.
- Transitorio a Re alto con y+<1: no validado.
- k-ε con ley de pared, k-ω y SST-LM: solo comprobados en funcionamiento.
- Fuera del NACA 0012 no hay tolerancias.
- La cola de trabajos vive en la computadora que los lanza: si se duerme, lo que corre sigue en su máquina y lo pendiente espera.
