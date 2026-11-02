# Ruta de validación y uso en empresas

Decisiones de Alejandro, 2026-11-01. Estado de resultados en [VALIDACION.md](VALIDACION.md).

No existe, hasta donde se pudo averiguar, un certificado que valide por sí solo los resultados de un programa CFD para aeronáutica o aerogeneradores: la autoridad o la certificadora acepta el uso de la herramienta en cada proyecto. No afirmar «certificado» ni «aprobado por» EASA, FAA o DNV.

## 1. Norma por comprar: ASME V&V 20

Estándar de verificación y validación para CFD. Se compra a futuro; entretanto se documenta el método para adaptarlo.

| Dato | Valor |
|---|---|
| Edición | ASME V&V 20-2009 (R2021), vigente según BSI |
| Dónde | ASME Store, Accuris, ANSI Webstore |
| Precio | Sin confirmar en la tienda oficial. Un revendedor eslovaco lista 76.30 sin IVA, sin moneda clara. Verificar al comprar |

Ya disponible para ese expediente: GCI por punto, comparación con experimento, fichas y reproducibilidad. Falta: incertidumbre experimental y de entrada, y el error de validación con su incertidumbre, calculados según la norma.

## 2. Más perfiles

Orden, según datos utilizables. Medir con tolerancias fijadas antes de ver el resultado.

1. NACA 0012 a otros Reynolds, con las tablas de Ladson (TM 4074).
2. NACA 0012 con transición libre: en curso.
3. NACA 4412: fijar tolerancias.
4. NACA 63-418 y FFA-W3, DU o S809: perfiles de turbina. Sus datos encontrados están sobre todo en figuras; hay que digitalizarlos declarando el error, y conseguir coordenadas de origen claro.

## 3. Publicación en revista JCR

Pendiente de definir revista. Antes de enviar, confirmar en Journal Citation Reports (acceso institucional) factor y cuartil, y en la guía de autores los requisitos de código y licencia.

| Revista | Encaja si | Dato sin confirmar en JCR |
|---|---|---|
| SoftwareX | Artículo del programa: publicar antes el código y decidir licencia | FI 2.4 (2024), Q3 |
| Wind Energy Science | Hay resultados en perfiles de turbina | FI 4.9 (2024) |
| Computers & Fluids | Aporte de método: verificación y compensación de errores | Sin dato fiable |

## 4. Empresa usuaria (futuro)

Cuando haya expediente, perfiles de turbina y artículo: buscar una empresa piloto, y consultar a una certificadora qué aceptaría. Falta decidir licencia: no hay archivo `LICENSE`.
