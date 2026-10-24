
---

## 9. Nota sobre la geometría exacta

OpenBlade genera el perfil con la fórmula NACA de 4 dígitos con borde de salida
cerrado:

    y = 5*t*(0.2969*sqrt(x) - 0.1260*x - 0.3516*x^2 + 0.2843*x^3 - 0.1036*x^4)

Espesor máximo: 12.0007 % de la cuerda.

NASA TMR usa una variante escalada para que el borde de salida sea afilado sin
desplazar la cuerda:

    y = ±0.594689181*(0.298222773*sqrt(x) - 0.127125232*x
                      - 0.357907906*x^2 + 0.291984971*x^3 - 0.105174606*x^4)

Espesor máximo: 11.894 % de la cuerda.

Diferencia: +0.876 %.

**Decisión (2026-10-24)**: no se corrige. Un 0.88 % de espesor es menor que el
error de discretización de la malla y muy inferior al desvío del Cd que se está
investigando (+330 %). Cambiar la geometría invalidaría las comparaciones ya
hechas y obligaría a regenerar todas las mallas.

Queda documentado como fuente de error sistemático conocida y acotada.
