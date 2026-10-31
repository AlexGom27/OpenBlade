# Bitácora de monitoreo: campañas V3 y E1

Revisiones de solo lectura del servidor `openblade`. Horas en UTC del servidor.
Referencia: `docs/REVISION_INDEPENDIENTE_V3.md`. Se separa dato medido (M) de hipótesis (H).

## 2026-10-30 16:25 (primera entrada, sin comparación previa)

**Infraestructura (M):** servidor responde. Carga 14 sobre 14 núcleos / 20 hilos. Memoria disponible
11 GiB de 15. Disco 40 G de 466 G (9 %). Sin FOAM FATAL, SIGFPE real ni Killed en los `run.log` activos.

**V3 (M):** vivo, `programa_v3.py` PID 237410, lanzado a las 04:16. Sigue en la fase V1, caso
`V1_trans_a8`, sin haber pasado de él en 12 h.

| Dato | Valor |
|---|---|
| Tiempo simulado | t = 0.0880 s de 0.4 s (22 %) |
| dt / Courant máx. | 2.007e-6 s / 1.00 |
| Cl últimas 500 escrituras | media 2.808, rango 0.259 |
| Cd últimas 500 escrituras | media 0.0185, rango 0.049 |
| Residuo inicial de p (final del paso) | ~2.5e-4 |
| `run.log` | 591 MB |

**E1 (M):** vivo, `programa_e1.py` PID 253789, lanzado a las 16:17; el smoke `E1_smoke_a0` terminó con
rc=0. Caso actual `E1_a0`, iteración ~1200 de 8000, ~0.38 s/iter. A los 5 h aprox. terminaría la
campaña si los otros casos cuestan lo mismo (H: los controles usan malla nueva y pueden costar más).
Aún es pronto para evaluar: Cl = -0.0114, Cd = 0.00725 y bajando, residuo de p ~1e-3.
νt/ν de entrada = 0.009 confirmado en el smoke. En el smoke, y+ medio = 60 (mín. 0.12, máx. 275).

### Anomalías

1. **V1_trans_a8 da un Cl no físico y creciente (M).** Cl medio por ventana: 1.65 (t<0.01), 1.88,
   2.15, 2.41, 2.59, 2.73 (0.08–0.09 s), frente a Ladson 0.86 y 0.81 del RANS de partida: ~3.2 veces
   la referencia. Cd oscila entre -0.068 y +0.053 en la última ventana; un Cd negativo no es físico.
   El caso no se está recuperando con el tiempo simulado.
2. **V1_trans_a8 agotará su timeout (proyección).** `programa_v3.py:302` fija `timeout=86400`, así que
   cortará hacia las 04:20 del 31-oct, con t ≈ 0.13–0.16 s de 0.4 s. Según el código devolverá
   `ok=false` y pasará a `V1_trans_a10`. Con 4 ángulos, V1 ocuparía unos 4 días y no daría ningún
   resultado completo; V2 no empezaría hasta entonces.
3. **`resultados.json` contiene un `V1_trans_a8` falso marcado `ok=true, cache=true` (M):** Cl = 0.7959,
   Cd = 0.01250. Es un promedio de RANS parcial, de la instancia lanzada a las 04:19, ya documentado
   en §1 de la revisión. Debe excluirse de cualquier análisis. Sigue ahí.
4. **E1 frena a V1 (M; causa H).** V1 pasó de ~1.10 s/paso a ~2.19 s/paso en los últimos 200 pasos,
   coincidiendo con el arranque de E1. H: competencia por núcleos, 14 rangos sobre 14 núcleos con
   E1 en `--bind-to none`. Cuando E1 termine debería volver a ~1.1 s/paso; se comprobará.

**`V1_trans_a10` (M):** directorio huérfano de las instancias duplicadas; `run.log` detenido a las
04:20 en la iteración 173, sin proceso asociado. No es un caso en curso.

**Sin acción en el servidor.** Detener V1 sigue siendo decisión de Alejandro (§4 y §6 de la revisión).
