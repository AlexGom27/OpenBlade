# Pendientes de OpenBlade

Anotados durante la sesión del 2026-10-22. No implementar hasta que la
simulación en curso termine.

---

## 1. Panel de avance junto a la gráfica de convergencia

**Lo que pidió el usuario**: ver junto a las gráficas de convergencia el
porcentaje de avance, el tiempo transcurrido y el ritmo — el mismo resumen que
ya existe abajo del panel de malla, pero visible en la pestaña **Residuales**.

**Estado actual**: el resumen de progreso existe (`_update_progress` en
`gui/main_window.py`) y se muestra en `input_panel.progress_label`, debajo de
los botones Pausar/Detener. En la pestaña Residuales sólo está la gráfica, sin
texto de avance.

**Qué falta**:
- Un `QLabel` en la pestaña Residuales (o en `ResidualPlot`) con:
  ```
  t = 0.0965 de 0.5 s   (19.3%)
  Transcurrido: 74 min   ·   ETA ~5.0 h
  Ritmo: 4.0 s/paso
  ```
- Alimentarlo desde el mismo `run.log` que ya lee `load_from_log()`, para que
  funcione también con corridas lanzadas fuera de la GUI.
- Refresco con el mismo `_conv_timer` de 10 s que ya existe.

**Datos ya disponibles**: `load_from_log()` parsea `Time =` de cada bloque;
basta con guardar el último y el número de bloques para calcular el porcentaje.

---

## 2. Contador de iteraciones internas (opcional)

El gráfico usa el tiempo simulado como abscisa. Podría añadirse el número de
iteración interna del solver de presión (`No Iterations` en el log), útil para
detectar si el solver necesita más `nCorrectors`.

---

## Notas

- Verificar que `~/.openblade/openfoam_case` siga apuntando al caso en curso
  (es un symlink; se rompe si el directorio destino se mueve).
- La app debe abrirse con `stdin` válido o con el fix de `DEVNULL` ya aplicado
  (commit `f0ae085`), si no los subprocesos mueren con
  `init_sys_streams`.
