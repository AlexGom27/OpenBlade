# Validación de OpenBlade

Todo lo de este documento salió del programa: malla y caso generados en la Mac, cálculo con OpenFOAM 12 en los servidores, y veredicto y ficha de cada paquete. Los archivos de resultados (polar, banco, control) se generan con las órdenes de §2 y no se guardan en el repositorio. Las campañas anteriores al 2026-10-31 no sirven como validación (§8).

## 1. Resumen

| Qué | Estado |
|---|---|
| Cl del NACA 0012, Re=6e6, de 4° a 17° (otros Reynolds en §7) | A menos de 1.7 % de Ladson, y de 1.2 % de 6° a 17°. A 2° difiere 0.010 (+4.9 %) |
| Cd del NACA 0012 en la malla por defecto | De −4.1 a +4.0 % frente a Ladson hasta 12°, dentro de su banda de malla (de ±7 a ±13 %), y en parte por compensación de errores (§6); de +10 a +15 % de 14° a 17° |
| Cd frente a NASA TMR, malla extrapolada | −1.0 % a 10°. A 15°, +2.1 %, con un orden bajo que lo hace poco firme (§6) |
| Pérdida | **No la predice.** Ladson cae a Cl≈1.0 a 18°; SST da 1.60 |
| Reproducibilidad entre máquinas | Mismo paquete y procesos, fuerzas idénticas byte a byte en los dos servidores, en corridas completas a α=0 y α=8 (§7) |
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

Ladson está interpolado entre sus ángulos medidos. «Oscila» es NO CONVERGIDO con media estable: Cd varía 1.1–1.5 % en las últimas 500 iteraciones, y se da su media. α=18 arrancó de α=17; los demás, del flujo potencial. En frío, α=18 no llega a estabilizarse en 40 000 iteraciones (su media de Cd aún cambia 4.5 %), pero acaba en el mismo punto: Cl 1.6040 y Cd 0.03645, frente a 1.6047 y 0.03641. No hay señal de dos soluciones.

## 5. Banco de validación

Ocho paquetes en el nivel 2, todos CONVERGIDOS: **35 de 40 comprobaciones cumplidas**. Tolerancias en `core/bench.py`: el informe PDF lo genera `python3 -m core.cli banco` (§2). Lo que no cumple:

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

**La cercanía a Ladson en el nivel 2 es en parte compensación de errores.** Cd frente a Ladson:

| α | Nivel 2 | Nivel 3 | Extrapolado | TMR (media) |
|---|---|---|---|---|
| 10 | −4.1 % | +0.5 % | +3.6 % | +4.7 % |
| 15 | +10.5 % | +15.3 % | poco firme | +23.7 % |

Refinar aleja Cd de Ladson y lo acerca a TMR. El error de malla del nivel 2 compensa una diferencia con el experimento que los códigos de referencia de TMR también muestran, así que esa diferencia no es de malla; estos datos no dicen si viene del modelo de turbulencia o del experimento. Una diferencia pequeña con Ladson en el nivel 2 no prueba por sí sola que Cd sea exacto.

**Arranque desde la malla anterior.** Los estudios de malla arrancan cada nivel de la solución del anterior:

| 897×257 | Iteraciones | Cl | Cd |
|---|---|---|---|
| α=10, desde el flujo potencial | 34 001 | 1.0619 | 0.01200 |
| α=10, desde el nivel 2 | 7 001 | 1.0628 | 0.01197 |
| α=0, desde el flujo potencial | 80 001 | 0.0000 | 0.007989 |
| α=0, desde el nivel 2 | 5 001 | 0.0000 | 0.007995 |

Cambiar el arranque mueve el extrapolado de Cd a 10° de 0.01242 a 0.01234 (0.6 %), menos que su banda de ±3.9 %.

A α=15 en 897×257, desde el flujo potencial el cálculo revienta hacia la iteración 1400. Desde α=10 en la misma malla queda atrapado en un ciclo grande (Cl de 1.28 a 1.43). Desde el nivel 2 converge en 8000 iteraciones. En 449×129, α=15 desde α=14 da lo mismo que en frío (Cd 0.019875 y 0.019893), en menos iteraciones. El rescate por ángulo vecino se limita a 2°.

**Mallas oficiales de TMR.**
- 449×129: 60 s por iteración con la máquina cargada, por celdas de aspecto 3×10⁷ que hacen que GAMG tarde 170 iteraciones; a la iteración 742 las fuerzas seguían lejos de su valor. No es practicable.
- 225×65: llega a 20 000 iteraciones con Cl 1.0797 y Cd 0.00965, oscilando 1.6 %. La malla propia del mismo tamaño da 1.0671 y 0.01008.

## 7. Otras comprobaciones

**Simetría (M).** α=±4, nivel 1: Cl +0.43752 y −0.43751, Cd 0.00787 en ambos, Cm ±0.0026.

**Perfil con curvatura (M).** NACA 4412, nivel 2, Re=6×10⁶: α=0 da Cl 0.455, Cd 0.00831, Cm −0.098; α=8 da Cl 1.280, Cd 0.01172, Cm −0.088. Leído de un archivo de coordenadas con 6 decimales, la vía de cualquier perfil propio, α=8 da Cl 1.2803, Cd 0.01170, Cm −0.0875: difiere 0.004 % en Cl y 0.2 % en Cd. Frente a Coles y Wadcock (α=13.87, Re=1.52×10⁶): Cl 1.638 oscilando, Cp RMS 0.20 en extradós y 0.15 en intradós, pico −7.04 frente a −6.21. Sin tolerancia fijada.

**Otros modelos a α=4 (M).** Solo comprueban que corren desde el programa. Ninguno está validado.

| Modelo | Malla | Cl | Cd | Estado |
|---|---|---|---|---|
| SST | nivel 2 | 0.4345 | 0.00829 | CONVERGIDO |
| k-ω | nivel 1 | 0.4413 | 0.00848 | oscila 1.1 % |
| SST-LM, con transición | nivel 1 | 0.4314 | 0.00526 | oscila 1.6 % |
| k-ε, y+=46, ley de pared | nivel 2 | 0.4560 | 0.00531 | oscila 3.4 % |

k-ε da Cd 36 % por debajo de SST: no se recomienda para coeficientes.

**Transición libre con SST-LM: no validada (M).** NACA 0012, nivel 2, Re=5.97×10⁶, frente a la Tabla I de Ladson interpolada, cuya turbulencia de túnel no se conoce. Entrada Tu=0.2 %, νt/ν=1:

| α | Veredicto | Cl | Dif. | Cd | Ladson | Dif. |
|---|---|---|---|---|---|---|
| 0 | CONVERGIDO | 0.0000 | | 0.00462 | 0.00650 | −28.9 % |
| 4 | CONVERGIDO | 0.4243 | −1.8 % | 0.00553 | 0.00753 | −26.6 % |
| 8 | CONVERGIDO | 0.8315 | −2.9 % | 0.00739 | 0.00787 | −6.1 % |
| 12 | CONVERGIDO | 1.2594 | −0.7 % | 0.01078 | 0.01226 | −12.1 % |
| 15 | oscila | 1.5291 | +1.1 % | 0.01556 | 0.01816 | −14.3 % |

Con Tu=0.052 % y νt/ν=0.009 sale casi lo mismo: Cd −32.3 % a 0° (sin convergir) y −29.2 % a 4°. Ladson señala que la turbulencia de su túnel adelantó la transición. En 200 cuerdas la turbulencia de entrada decae: de 0.2 % a cerca de 0.006 % según la ecuación de decaimiento de SST, y por eso no influye. Lo confirma subir la que llega al perfil (estimada, no medida):

| Entrada | Tu estimada en el perfil | Cd a 0° | 4° | 8° | 12° | Cl, máxima dif. |
|---|---|---|---|---|---|---|
| Tu=0.2 %, νt/ν=1 | 0.006 % | −28.9 % | −26.6 % | −6.1 % | −12.1 % | −2.9 % |
| Tu=0.6 %, νt/ν=1000 | 0.2 % | −7.3 % | −7.1 % | +9.5 % | −4.1 % | +0.7 % |
| Tu=1 %, νt/ν=10 000 | 0.6 % | +2.7 % | +0.2 % | +18.8 % | +4.4 % | +0.5 % |

Todos CONVERGIDOS salvo lo indicado arriba. La tendencia es correcta, pero es una calibración: la turbulencia del túnel de Ladson se desconoce, así que elegir la Tu que mejor coincide no valida el modelo. Además νt/ν de 1000 o más es muy alta, sin estudiar su efecto, y a 8° la tabla de Ladson tiene un valor bajo (0.0080) que ningún caso sigue. Falta un caso con Tu medida. Laminar a Re=5000, α=0: Cd 0.0543, CONVERGIDO.

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

**Caso de control (M).** Mismo paquete en los dos servidores, 8 procesos, lanzado desde el programa. Pasa todas las compuertas:

| α | Iteraciones | Cl | Cd | md5 de las fuerzas | Diferencia máxima entre servidores |
|---|---|---|---|---|---|
| 0 | 16 001 | 0.0000 | 0.00784 | `42c7aa517468` en ambos | 0 en todas las filas |
| 8 | 13 001 | 0.8615 | 0.00987 | `8bd26dd455ac` en ambos | 0 en todas las filas |

Las fichas coinciden en archivos, parámetros y versiones; la malla es `c2ed1a996956` en los dos. Cada corrida, con otra simultánea en la misma máquina, tardó de 16 a 24 minutos con subida y descarga. Los dos servidores tienen el mismo procesador y la misma compilación de OpenFOAM: con otro procesador no está medido.

**Reproducibilidad.** Local (Docker emulado) y `openblade2`, 2 procesos y 300 iteraciones: fuerzas idénticas, md5 `6086045a3719`. Es una prueba corta, y el resultado vale para el mismo número de procesos. Un clon nuevo con un entorno nuevo da la misma malla: sha256 `c2ed1a996956` en el nivel 2, con numpy 2.4.0 y 2.4.6.

**Otros Reynolds (M).** NACA 0012, SST, nivel 2, frente a Ladson con grano 80, interpolado. Todos CONVERGIDOS. Sin estudio de malla a estos Reynolds, y sin tolerancias fijadas de antemano:

| α | Re=3.99×10⁶, Cl | Cd | Re=2×10⁶, Cl | Cd |
|---|---|---|---|---|
| 0 | | −3.3 % | | −6.3 % |
| 4 | +1.7 % | +1.5 % | +1.5 % | −4.2 % |
| 8 | +1.1 % | −4.2 % | +3.3 % | −6.7 % |
| 10 | +1.1 % | −4.0 % | +3.7 % | −9.5 % |
| 12 | +1.4 % | +4.9 % | +3.9 % | −5.8 % |
| 14 | +1.4 % | +3.4 % | +4.9 % | −7.8 % |

A Re=2×10⁶ Cl sale alto y Cd bajo con más diferencia. No se estudió por qué. A ese Reynolds el grano de Ladson pesa más, lo cual el modelo no representa, pero no está demostrado que esa sea la causa.

**Tolerancias fijadas el 2026-11-02, antes de correr.** Todo con SST, malla C, nivel 2, y lanzado desde la ventana:

| Caso | Referencia | Criterio |
|---|---|---|
| NACA 0012, Re=2×10⁶ y 3.99×10⁶, estudio de malla a 0° y 10° | Ladson, grano 80 | Nivel 2: Cl a 10° ≤3 %, Cd a 0° ≤5 %, Cd a 10° ≤10 %, como a 6×10⁶. Se informa la banda GCI |
| NACA 4412 y NACA 63₃-418, Re=6×10⁶, α=0, 4, 8 y 12 | Abbott y von Doenhoff, apéndice IV, digitalizado de figura | Cl ≤5 % de 0° a 8°, contra el perfil liso. Cd entre el liso y el de rugosidad estándar: SST es totalmente turbulento, pero sin rugosidad. Cm a menos de 0.01. A 12° solo se informa |

La lectura de las figuras de Abbott añade su error, estimado en ±0.02 en Cl y ±0.0004 en Cd. Las coordenadas del 63₃-418 son las de Abbott, apéndice III: `validation/refs/naca63-3-418_abbott.dat`.

**Resultado frente a esas tolerancias (M).**

NACA 0012, estudio de malla: a Re=3.99×10⁶ cumple todo (Cd a 0° −3.3 %, Cl a 10° +1.1 %, Cd a 10° −4.0 %). A Re=2×10⁶ falla Cd a 0° (−6.3 %, tope 5 %) y Cl a 10° (+3.7 %, tope 3 %); Cd a 10° cumple justo (−9.5 %). En Cd la malla fina explica casi toda la diferencia (extrapolado −1.2 % a 0° y −4.4 % a 10°); en Cl no, porque la banda de malla es ±0.7 %.

Perfiles con curvatura, Re=6×10⁶, nivel 2:

| Perfil | α | Cl | Abbott | Dif. | Cd dentro de liso-rugoso | Cm, dif. |
|---|---|---|---|---|---|---|
| 4412 | 0 | 0.455 | 0.41 | **+11.0 %** | sí | −0.008 |
| 4412 | 4 | 0.876 | 0.82 | **+6.8 %** | sí | −0.003 |
| 4412 | 8 | 1.281 | 1.21 | **+5.9 %** | sí | −0.004 |
| 63₃-418 | 0 | 0.360 | 0.30 | **+19.9 %** | sí | −0.003 |
| 63₃-418 | 4 (oscila) | 0.822 | 0.69 | **+19.1 %** | sí | |
| 63₃-418 | 8 | 1.251 | 1.08 | **+15.8 %** | sí | 0.000 |

Cl no cumple en ningún punto; Cd y Cm cumplen en todos.

**Corrección del 2026-11-03: la referencia del 63₃-418 estaba mal leída.** Dos repeticiones independientes de los mismos datos de Abbott, la de Ehrmann y White (2014, fig. 7) y la del catálogo de Risø (Bertagnolio et al. 2001, fig. 30), dan Cl≈0.32 a 0°, ≈0.78 a 4° y ≈1.19 a 8°, entre 0.06 y 0.09 más que mi lectura. Ehrmann además mide el perfil limpio y coincide con Abbott en la zona lineal. Frente a esos valores OpenBlade queda a +12 % a 0° (Cl pequeño), +5.4 % a 4° y +5 % a 8°. El código Navier-Stokes del catálogo de Risø (EllipSys2D, SST con transición) da casi lo mismo que OpenBlade, 0.85 a 4° y 1.25 a 8°, y su informe cuenta una diferencia media de 5.1 % con el experimento en la zona lineal; XFOIL da lo mismo. La tolerancia sigue sin cumplirse, pero por un margen mucho menor. Segunda fuente del 4412: Pinkerton (1937, NACA TR-563, `validation/refs/pinkerton_4412_tr563.dat`), túnel de densidad variable, Re≈3×10⁶, con la sección central corregida al ángulo efectivo. Ángulo de sustentación nula −4.0° (OpenBlade −4.25°); Cl interpolado ≈0.39 a 0° y ≈0.79 a 4°, frente a 0.455 y 0.876 de OpenBlade (+17 % y +11 %). Las dos fuentes, aunque antiguas, quedan por debajo de OpenBlade. La geometría no es la causa: el NACA 4412 que genera el programa coincide con las ordenadas de Abbott a 0.01 % de la cuerda. En el 4412, SST sobrestima Cl entre 6 y 17 % según la fuente; no se ha determinado la causa, y no hay una fuente moderna abierta a este Reynolds.

**¿Corrige la transición esa diferencia? No (M).** NACA 63₃-418 a Re=2.4×10⁶, el de Ehrmann, frente a su perfil limpio (Cl≈0.32, 0.78 y 1.19, leído de su fig. 7; Tu del túnel 0.25 %):

| Modelo | α | Cl | Dif. | Cd |
|---|---|---|---|---|
| SST | 0 | 0.352 | +9.9 % | 0.0103 |
| SST | 4 | 0.806 | +3.3 % | 0.0117 |
| SST | 8 (oscila) | 1.219 | +2.4 % | 0.0149 |
| SST-LM, Tu≈0.24 % en el perfil | 0 | 0.384 | +20 % | 0.0056 |
| SST-LM | 4 (oscila) | 0.850 | +9.0 % | 0.0072 |
| SST-LM | 8 (oscila) | 1.266 | +6.4 % | 0.0112 |

Con transición Cl sube en vez de bajar, porque la capa límite laminar es más delgada; Cd en cambio se acerca al medido por Ehrmann (≈0.006–0.007 entre Cl 0.3 y 0.8), que SST sobrestima. La malla tampoco es: a 4°, Cl cambia 0.2 % del nivel 1 al 3 en los dos perfiles (4412: 0.881, 0.876, 0.874; GCI 0.13 %). Con SST, a este Reynolds el 63₃-418 queda a +2.4 y +3.3 % en Cl a 4° y 8°. El ángulo de sustentación nula coincide (4412: −4.25° frente a −4.13°; 63₃-418: −3.11° frente a −3.08°). Lo que difiere es la pendiente: 0.105 frente a 0.100 por grado en el 4412, y 0.114 frente a 0.098 en el 63₃-418. No se ha determinado si viene del modelo, de la lectura de las figuras o de las correcciones de túnel del experimento.

**Tolerancias fijadas el 2026-11-03, antes de correr.** NACA 63₃-418, Re=2.4×10⁶, frente a Ehrmann (`validation/refs/ehrmann_63418_re2.4e6.dat`), α de 2° a 10°: SST, Cl ≤5 %; SST-LM con Tu≈0.24 % en el perfil, Cd ≤15 % a Cl de 0.2 a 1.0. Estudio de malla de SST-LM a 4°.

**Resultado frente a esas tolerancias (M).** NACA 63₃-418, Re=2.4×10⁶, nivel 2, frente a Ehrmann:

| α | SST: Cl | Dif. | ¿≤5 %? | SST-LM: Cl | Cd | Cd de Ehrmann al mismo Cl | Dif. |
|---|---|---|---|---|---|---|---|
| 0 | 0.352 | +9.9 % | (fuera del rango) | 0.384 | 0.00561 | 0.0064 | −12.4 % |
| 2 | 0.582 | +5.9 % | **no** | 0.622 | 0.00602 | 0.0068 | −11.6 % |
| 4 | 0.806 | +3.3 % | sí | 0.850 (oscila) | 0.00716 | 0.0080 | −11.0 % |
| 6 | 1.019 | −0.1 % | sí | 1.070 (oscila) | 0.00865 | | (Cl > 1.0) |
| 8 | 1.219 (oscila) | +1.6 % | sí | 1.266 (oscila) | 0.01115 | | (Cl > 1.0) |
| 10 | 1.392 (oscila) | +11.3 % | **no** | 1.436 (oscila) | 0.01502 | | (Cl > 1.0) |

SST cumple Cl en 3 de 5 ángulos; a 10° el experimento ya se aparta de la zona lineal (Ehrmann: «diverge de Abbott después de 9°») y SST no predice esa caída. SST-LM cumple Cd en los 3 puntos dentro del rango (−11 a −12 %), mientras que SST lo sobrestima de 49 a 62 % en esos mismos ángulos. Pero el estudio de malla de SST-LM a 4° no da banda: los niveles 1 y 2 oscilan, y Cd va de 0.00738 a 0.00773 y luego a 0.00653 (nivel 3), sin convergencia monótona. Además, el mismo caso del nivel 2 dio Cd 0.00716 arrancando del flujo potencial y 0.00773 arrancando del nivel 1: el punto de arranque mueve el resultado un 8 %. **SST-LM sigue sin validar:** acierta Cd en el nivel 2, pero la malla y el arranque lo mueven tanto como la tolerancia.

## 8. Por qué lo anterior no sirve

Las corridas previas al 2026-10-31 tienen estos defectos, y sus documentos llevan el aviso «Superado»:
1. `writePrecision 6` redondeaba los puntos de la malla a 6 cifras al convertirla: no ortogonalidad de 85.9° en una malla de 39°.
2. La tolerancia 1e-6 del solver lineal congelaba k y ω: «No Iterations 0» y fuerzas estables falsas, con veredicto CONVERGIDO.
3. Muchas salían de scripts que escribían sus propios casos: lo validado no era lo que corre la ventana. Cada servidor generaba su propia malla, y de ahí la discrepancia entre servidores.

## 9. Límites declarados

- No predice la pérdida: SST sigue a Cl 1.60 a 18°, donde el experimento cae a 1.0.
- A partir de 14° Cd está 10–15 % por encima de Ladson, y refinar la malla aumenta la diferencia.
- Nivel 2 sirve para Cl. Para Cd a menos de 5 % de TMR, nivel 3.
- La banda de malla de Cl a 15° es grande (±4.3 %) porque el nivel 1 es pobre ahí.
- Transitorio a Re alto con y+<1: no validado.
- k-ε con ley de pared y k-ω: solo comprobados en funcionamiento.
- SST-LM: el programa avisa si la turbulencia de entrada se disipa antes del perfil. Cd depende de la que llega, de −32 a +19 % frente a la transición libre de Ladson. Sin Tu medida es una calibración, no una validación. La entrada por defecto se disipa antes de llegar al perfil.
- Fuera del NACA 0012 no hay tolerancias.
- Interacción fluido-estructura (Análisis FSI): experimental. El benchmark de Turek y Hron no se completó porque el acoplamiento diverge; no usar sus resultados.
- `polar_xfoil.txt` lleva solo los puntos convergidos, sin banda ni CDp. Su formato no se ha probado todavía importándolo en QBlade, que además exige completar la polar a 360°.
- Borde de salida abierto: la malla C propia lo cierra, así que no representa perfiles romos. Hasta 0.2 % de la cuerda solo lo anota en la ficha; hasta 2 %, avisa del arrastre de base que falta (Hoerner), y eso no entra en la banda de malla; con más, rechaza el perfil. Un perfil de 30 % con 2 % de abertura queda 11 % más delgado en x/c=0.8.
- Cada servidor guarda su propia cola: lo enviado sigue aunque la computadora que lo lanzó se apague. Dos cosas siguen dependiendo de ella: la parada temprana (sin conexión, el cálculo llega al tope de iteraciones) y los niveles finos de un estudio de malla, que arrancan del campo del nivel anterior.
