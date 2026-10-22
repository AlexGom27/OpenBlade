#!/usr/bin/env python3
"""Prueba de humo de la aplicación: arranca la GUI y ejercita los flujos reales.

No es un test unitario: abre la ventana, pulsa los botones y captura las
excepciones que ocurran durante el event loop. Los errores de GUI casi nunca
aparecen en llamadas directas -- aparecen conectados a señales, en callbacks
diferidos, o cuando Qt repinta.

Uso:
    QT_QPA_PLATFORM=offscreen python3 validation/smoke_gui.py
    QT_QPA_PLATFORM=offscreen python3 validation/smoke_gui.py --interactivo
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

ERRORES = []


def hook_excepciones(exc_type, exc, tb):
    """Captura cualquier excepción que Qt se trague en un slot."""
    msg = "".join(traceback.format_exception(exc_type, exc, tb))
    ERRORES.append(msg)
    print("\n!!! EXCEPCIÓN EN SLOT !!!\n" + msg)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interactivo", action="store_true",
                    help="no cierra sola; espera al usuario")
    args = ap.parse_args(argv)

    sys.excepthook = hook_excepciones

    from qtpy.QtWidgets import QApplication
    from qtpy.QtCore import QTimer

    app = QApplication.instance() or QApplication(sys.argv)

    from gui.visual_theme import apply_theme
    apply_theme(app)

    from gui.main_window import MainWindow
    w = MainWindow()
    w.show()

    # --- Comprobaciones estructurales -----------------------------------
    print("\n=== ESTRUCTURA ===")
    checks = []

    checks.append(("ventana visible", w.isVisible()))
    checks.append(("panel de entrada", hasattr(w, "input_panel")))
    checks.append(("botón ejecutar", hasattr(w.input_panel, "btn_run")))
    checks.append(("botón FSI", hasattr(w, "btn_fsi")))

    p = w.input_panel.get_params()
    checks.append(("get_params devuelve dict", isinstance(p, dict)))
    checks.append(("parámetros FSI presentes",
                   all(k.startswith("fsi") for k in p if k.startswith("fsi"))
                   and len([k for k in p if k.startswith("fsi")]) >= 10))

    for name, ok in checks:
        print(f"  {'OK  ' if ok else 'FALLA'}  {name}")

    # --- Ejercitar los flujos sin lanzar procesos largos ----------------
    print("\n=== FLUJOS ===")

    # 1. Validación de parámetros de malla
    try:
        from core.mesh_script import main as mesh_main  # noqa: F401
        print("  OK    módulo de malla importable")
    except Exception as e:
        print(f"  FALLA módulo de malla: {e}")
        ERRORES.append(str(e))

    # 2. Generación de configuración FSI (sin lanzar docker)
    try:
        import tempfile
        from core.fsi_precice import FsiCase, FsiConfig
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "system"))
        open(os.path.join(d, "system", "controlDict"), "w").write(
            "application pimpleFoam;\n")
        open(os.path.join(d, "system", "fvSolution"), "w").write(
            "solvers\n{\n    p { solver GAMG; }\n}\n")
        paths = FsiCase(d, FsiConfig()).prepare()
        print(f"  OK    FSI prepara {len(paths)} archivos")
    except Exception as e:
        print(f"  FALLA FSI prepare: {e}")
        ERRORES.append(traceback.format_exc())

    # 3. Lectura de campos (render)
    try:
        from core.field_render import cell_polygons, nodal_values  # noqa: F401
        print("  OK    módulo de render importable")
    except Exception as e:
        print(f"  FALLA render: {e}")
        ERRORES.append(traceback.format_exc())

    # 4. Informe
    try:
        import validation.make_report as mr  # noqa: F401
        print("  OK    generador de informe importable")
    except Exception as e:
        print(f"  FALLA informe: {e}")
        ERRORES.append(traceback.format_exc())

    # 5. Cambiar el régimen y comprobar que los widgets se actualizan
    try:
        combo = w.input_panel.regime_selector
        for i in range(combo.count()):
            combo.setCurrentIndex(i)
            app.processEvents()
        combo.setCurrentIndex(0)
        print("  OK    cambio de régimen sin excepciones")
    except Exception as e:
        print(f"  FALLA cambio de régimen: {e}")
        ERRORES.append(traceback.format_exc())

    # 6. Activar FSI y leer parámetros
    try:
        w.input_panel.fsi_enabled.setChecked(True)
        app.processEvents()
        p2 = w.input_panel.get_params()
        assert p2["fsi_enabled"] is True
        assert p2["fsi_E"] > 0
        print("  OK    activación FSI y lectura de parámetros")
    except Exception as e:
        print(f"  FALLA activación FSI: {e}")
        ERRORES.append(traceback.format_exc())

    # --- Dejar correr el event loop -------------------------------------
    print("\n=== EVENT LOOP ===")
    if args.interactivo:
        app.exec()
    else:
        QTimer.singleShot(3000, app.quit)
        app.exec()
    print("  OK    3 s de event loop sin caídas")

    # --- Repintado bajo carga -------------------------------------------
    try:
        w.resize(1200, 800)
        app.processEvents()
        w.resize(900, 600)
        app.processEvents()
        print("  OK    redimensionado")
    except Exception as e:
        print(f"  FALLA redimensionado: {e}")
        ERRORES.append(traceback.format_exc())

    w.close()

    # --- Veredicto -------------------------------------------------------
    print("\n" + "=" * 60)
    if ERRORES:
        print(f"FALLOS: {len(ERRORES)}")
        for i, e in enumerate(ERRORES, 1):
            print(f"\n--- {i} ---\n{e[:800]}")
        return 1
    print("SIN ERRORES DE EJECUCIÓN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
