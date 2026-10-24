"""Calcula los parametros de capa limite para que empalme con el campo exterior.

Problema medido
---------------
Con bl_dist_min = 2e-5, 30 capas y ratio 1.12, la capa limite crece hasta
2e-5 * (1.12^30 - 1)/(0.12) = 4.8e-3 m. La celda exterior vale 6e-3 m
(mesh_size). El salto es pequeno en la ultima capa... pero gmsh no lo ve asi:

    volumen minimo 9.37e-10   vs   maximo 0.330    ratio 3.5e8
    aspect ratio maximo 75727 (6908 celdas)
    13129 celdas con determinante < 1e-3 (minimo 1.77e-9)

Esas celdas mal condicionadas son las que hacen divergir linearUpwind.

Causa
-----
El campo Threshold transiciona de mesh_size a farfield_size en grow_dist
cuerdas, MIENTRAS el campo BoundaryLayer impone sus propias alturas. En la
interfaz ambos compiten y gmsh genera celdas de transicion degeneradas.

Solucion
--------
1. La ultima celda de la BL debe ser del orden de mesh_size, no menor.
   Se calcula el ratio necesario para que first*ratio^(n-1) ~ mesh_size.
2. El campo Threshold exterior debe arrancar su transicion DESDE el espesor
   total de la BL, no desde cero, para que no haya dos escalas compitiendo.
"""

from __future__ import annotations
import math


def ratio_para_empalme(first_layer: float, n_layers: int,
                       mesh_size: float) -> float:
    """Ratio geometrico tal que la ultima celda ~ mesh_size.

    La capa k mide first*ratio^(k-1). Se busca ratio tal que la ultima
    (k = n_layers) iguale mesh_size, con un tope para no deformar la BL.
    """
    if first_layer <= 0 or n_layers < 2 or mesh_size <= first_layer:
        return 1.2
    r = (mesh_size / first_layer) ** (1.0 / (n_layers - 1))
    # topes: por debajo de 1.05 la BL no crece, por encima de 1.5 es demasiado
    return max(1.05, min(r, 1.5))


def espesor_bl(first_layer: float, ratio: float, n_layers: int) -> float:
    """Altura total de la capa limite."""
    if abs(ratio - 1.0) < 1e-9:
        return first_layer * n_layers
    return first_layer * (ratio ** n_layers - 1) / (ratio - 1)


def diagnosticar(first_layer: float, n_layers: int, ratio: float,
                 mesh_size: float, farfield_size: float) -> dict:
    h = espesor_bl(first_layer, ratio, n_layers)
    r_opt = ratio_para_empalme(first_layer, n_layers, mesh_size)
    return {
        "bl_actual": {
            "ratio": ratio,
            "espesor_total": h,
            "ultima_celda": first_layer * ratio ** (n_layers - 1),
            "salto_a_mesh_size": mesh_size / (first_layer * ratio ** (n_layers - 1)),
        },
        "bl_optima": {
            "ratio": r_opt,
            "espesor_total": espesor_bl(first_layer, r_opt, n_layers),
            "ultima_celda": first_layer * r_opt ** (n_layers - 1),
            "salto_a_mesh_size": mesh_size / (first_layer * r_opt ** (n_layers - 1)),
        },
        "campo_exterior": {
            "mesh_size": mesh_size,
            "farfield_size": farfield_size,
            "salto_exterior": farfield_size / mesh_size,
        },
    }


if __name__ == "__main__":
    print("=== BL con bl=2e-5, 30 capas ===")
    for r in (1.12, 1.15, 1.20, 1.25):
        d = diagnosticar(2e-5, 30, r, 0.006, 0.5)
        a = d["bl_actual"]
        print(f"ratio={r:.2f}: espesor={a['espesor_total']:.2e}  "
              f"ultima_celda={a['ultima_celda']:.2e}  "
              f"salto={a['salto_a_mesh_size']:.1f}x")

    print()
    print("=== ratio optimo para empalme ===")
    r = ratio_para_empalme(2e-5, 30, 0.006)
    d = diagnosticar(2e-5, 30, r, 0.006, 0.5)
    b = d["bl_optima"]
    print(f"ratio={r:.4f}  espesor={b['espesor_total']:.3e}  "
          f"ultima_celda={b['ultima_celda']:.3e}  salto={b['salto_a_mesh_size']:.2f}x")
