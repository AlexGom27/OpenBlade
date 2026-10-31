# validation/

Scripts históricos de las campañas anteriores. Escriben sus propios casos o usan otra versión de OpenFOAM, y sus resultados tienen los defectos descritos en `docs/VALIDACION.md`. **No validan el programa** y no se usan para nada nuevo.

La validación vigente sale del programa:

```bash
python3 -m core.cli banco --maquinas usuario@a:10:1,usuario@b:8:1 --salida carpeta
```

```bash
python3 -m core.cli polar --maquinas usuario@a:10:1 --angulos 0,4,8 --gci 0,8 reynolds=6e6
```

En la ventana: botón **Banco de Validación**, y **Análisis: Estudio de Malla**.

`refs/` sí está vigente: son los datos de referencia, de NASA TMR (`tmr_*`) y Ladson (NASA TM 4074).
