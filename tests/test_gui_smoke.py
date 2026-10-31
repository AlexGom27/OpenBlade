"""Smoke test de la GUI en modo headless.

Cubre los bugs encontrados en la auditoría:
- MainWindow debe construirse sin servidor gráfico (antes: SIGSEGV de VTK).
- Las figuras para el informe PDF deben existir como `.fig`.
- El estado de ejecución debe liberarse al terminar/fallar.
"""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

pytest.importorskip("qtpy")

from qtpy.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture(scope="module")
def window(app):
    from gui.main_window import MainWindow

    w = MainWindow()
    yield w
    w.close()


def test_window_builds_headless(window):
    assert window.results_panel is not None
    # En headless el plotter 3D debe estar desactivado, no reventar.
    assert window.results_panel.plotter is None


def test_default_params(window):
    p = window.input_panel.get_params()
    assert p["naca"] == "0012"
    assert p["aoa"] == 0.0
    assert "simpleFoam" in p["regime"]


def test_report_figures_exist(window, tmp_path):
    for name, plot in (("res", window.res_plot), ("aero", window.aero_plot), ("cp", window.cp_plot)):
        out = tmp_path / f"{name}.png"
        plot.fig.savefig(out, dpi=50)
        assert out.exists() and out.stat().st_size > 0


def test_run_state_resets(window):
    window._sim_running = True
    window.input_panel.btn_run.setEnabled(False)
    window._reset_run_state()
    assert window._sim_running is False
    assert window.input_panel.btn_run.isEnabled()
    assert not window.input_panel.btn_stop_sweep.isVisible()


def test_force_data_uses_captured_aoa(window):
    window._current_aoa = 6.0
    window.on_force_data("Cl", "0.7")
    window.refresh_plots()
    assert window.aero_plot.aoas == [6.0]
    assert window.aero_plot.cls == [0.7]


def test_cleanup_preserves_user_mesh(window, tmp_path, monkeypatch):
    """Abrir la app no debe borrar las mallas que generó el usuario."""
    workdir = tmp_path / "wd"
    workdir.mkdir()
    keep = workdir / "perfil_0012.msh"
    keep.write_text("malla del usuario")
    sweep = workdir / "perfil_0012_sweep.msh"
    sweep.write_text("temporal")

    monkeypatch.chdir(workdir)
    window.cleanup()

    assert keep.exists(), "cleanup borró la malla del usuario"
    assert not sweep.exists(), "cleanup dejó la malla temporal del barrido"


def test_exec_mode_defaults_to_local_and_round_trips(window):
    panel = window.input_panel
    p = panel.get_params()
    assert p["exec_mode"] == "local"
    panel.set_params({"exec_mode": "server", "server_host": "u@h", "server_nproc": 6})
    p = panel.get_params()
    assert (p["exec_mode"], p["server_host"], p["server_nproc"]) == ("server", "u@h", 6)
    panel.set_params({"exec_mode": "local"})


def test_aero_coefficients_have_their_own_subtabs(window):
    tabs = window.aero_plot.subtabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["Cl", "Cd", "Cm"]
    window.aero_plot.update_plots([0.0, 10.0], [0.0, 1.1], [0.01, 0.02], [0.0, 0.1])
    window.aero_plot.redraw()
    _, _, ax, _ = window.aero_plot._charts["cl"]
    ymin, ymax = ax.get_ylim()
    assert ymin <= 0.0 and ymax >= 1.1


def test_steady_progress_counts_iterations_not_seconds(window):
    """Antes mostraba «t = 500 de 0.5 s (100000 %)» en estacionario."""
    import time
    window._sim_t0 = time.time() - 60
    window._sim_transient = False
    window._sim_end_time = 6000.0
    window._update_progress(1500.0, 1500)
    texto = window.input_panel.progress_label.text()
    assert "iteración 1500 de 6000" in texto and "(25.0%)" in texto


def test_verdict_banner_never_says_finished_without_a_state(window):
    from core.verdict import DIVERGIDO, Verdict
    v = Verdict(DIVERGIDO, "|Cl| llega a 26.7 en la ventana final", cl=22.0, cl_amp=1.0,
                cd=2.0, cd_amp=1.0, cm=0.0, cm_amp=0.0)
    window._current_aoa = 8.0
    window._show_analysis(({"verdict": v.to_dict(), "yplus": None, "yplus_notice": None}, 0))
    assert window.verdict_banner.text().startswith("💥 DIVERGIDO")
    assert "22.0" not in window.verdict_banner.text()
    assert window.aero_plot.aoas == []


def test_polar_does_not_draw_diverged_points_and_marks_doubtful_ones(window):
    window.aero_plot.update_plots([0.0, 4.0, 8.0], [0.0, 0.4, None], [0.008, 0.009, None],
                                  [0.0, 0.0, None],
                                  ["CONVERGIDO", "NO CONVERGIDO", "DIVERGIDO"])
    window.aero_plot.redraw()
    _, _, _, linea = window.aero_plot._charts["cl"]
    assert list(linea.get_xdata()) == [0.0, 4.0]
    assert list(window.aero_plot._dudosos["cl"].get_xdata()) == [4.0]
    window.aero_plot.update_plots([], [], [], [], [])
    window.aero_plot.redraw()
