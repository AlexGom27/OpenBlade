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
    # Sin esto, cerrar abre el dialogo de guardar y la prueba se queda esperando.
    w._has_unsaved_work = False
    w.close()


def test_window_builds_headless(window):
    assert window.results_panel is not None
    assert window.tabs.tabText(window.tabs.indexOf(window.jobs_panel)) == "Trabajos"
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


def test_window_works_through_jobs(window):
    """Un paquete por clic, cada uno con su carpeta; el boton sigue disponible."""
    from core.jobs import load_jobs
    from unittest.mock import patch
    panel = window.input_panel
    panel.set_params({"exec_mode": "server", "server_host": "u@h", "server_nproc": 2})
    with patch.object(window.dispatcher, "submit") as enviar:
        panel.btn_run.click()
        panel.btn_run.click()
    panel.set_params({"exec_mode": "local"})
    assert enviar.call_count == 2
    a, b = (c.args[0] for c in enviar.call_args_list)
    assert a.id != b.id and a.case_dir != b.case_dir and a.host == "u@h" and a.nproc == 2
    assert panel.btn_run.isEnabled()
    assert window.current_job is b and window.case_dir == b.case_dir
    assert window.results_panel.case_dir == b.case_dir
    assert {a.id, b.id} <= {j.id for j in load_jobs()}
    assert window.jobs_panel.tabla.rowCount() >= 2


def test_sweep_sends_one_package_per_angle_to_the_chosen_machines(window):
    from unittest.mock import patch
    panel = window.input_panel
    window.jobs_panel.add_machine("a@h", 4)
    panel.set_params({"exec_mode": "repartir", "analysis_mode": "Barrido de Ángulos",
                      "aoa_min": 0.0, "aoa_max": 4.0, "aoa_step": 2.0})
    with patch.object(window.dispatcher, "submit") as enviar:
        panel.btn_run.click()
    panel.set_params({"exec_mode": "local", "analysis_mode": "Punto Único"})
    trabajos = [c.args[0] for c in enviar.call_args_list]
    assert [j.params["aoa"] for j in trabajos] == [0.0, 2.0, 4.0]
    assert len({j.group for j in trabajos}) == 1 and all(j.host == "" for j in trabajos)


def test_local_keeps_its_limit_even_if_it_is_not_marked_for_spreading(window):
    window._sync_machines()
    local = window.dispatcher.machines["local"]
    assert local.slots >= 1 and local.reparto is False


def test_polar_is_built_from_finished_jobs_of_the_group(window):
    from core.jobs import TERMINADO, new_job
    from core.defaults import case_params
    for aoa, estado, cl in ((0.0, "CONVERGIDO", 0.0), (4.0, "NO CONVERGIDO", 0.45), (8.0, "DIVERGIDO", 22.0)):
        job = new_job(case_params(aoa=aoa), "u@h", 2, group="g1")
        job.state = TERMINADO
        job.analysis = {"verdict": {"state": estado, "cl": cl, "cd": 0.01, "cm": 0.0}}
        window.dispatcher.jobs[job.id] = job
    window._update_polar("g1")
    assert window.aero_plot.aoas == [0.0, 4.0, 8.0]
    assert window.aero_plot.cls == [0.0, 0.45, None]
    assert "1 DIVERGIDO" in window.verdict_banner.text()


def test_grid_study_sends_three_nested_levels_and_shows_the_uncertainty(window):
    from unittest.mock import patch
    from core.jobs import TERMINADO
    panel = window.input_panel
    panel.set_params({"exec_mode": "server", "server_host": "u@h", "server_nproc": 2,
                      "analysis_mode": "Estudio de Malla", "aoa": 4.0})
    with patch.object(window.dispatcher, "submit") as enviar:
        panel.btn_run.click()
    panel.set_params({"exec_mode": "local", "analysis_mode": "Punto Único", "aoa": 0.0})
    trabajos = [c.args[0] for c in enviar.call_args_list]
    assert [j.params["grid_level"] for j in trabajos] == [1, 2, 3]
    assert len({j.group for j in trabajos}) == 1 and all(j.params["aoa"] == 4.0 for j in trabajos)
    for j, cl, cd in zip(trabajos, (0.44, 0.43, 0.4275), (0.0090, 0.0084, 0.0082)):
        j.state = TERMINADO
        j.analysis = {"verdict": {"state": "CONVERGIDO", "cl": cl, "cd": cd, "cm": 0.0}}
    window._update_group(trabajos[0].group)
    assert "GCI" in window.verdict_banner.text() and "Cd" in window.verdict_banner.text()


def test_bench_asks_first_and_then_sends_its_packages(window):
    from unittest.mock import patch
    from qtpy.QtWidgets import QMessageBox
    from core.bench import default_cases
    window.jobs_panel.add_machine("a@h", 4)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.No), \
            patch.object(window.dispatcher, "submit") as enviar:
        window.on_run_bench()
    assert enviar.call_count == 0
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
            patch.object(window.dispatcher, "submit") as enviar:
        window.on_run_bench()
    assert enviar.call_count == len(default_cases())
    assert enviar.call_args_list[0].args[0].group.startswith("banco_")


def test_project_file_restores_the_panel(window, tmp_path):
    import json
    ruta = tmp_path / "p.obp"
    ruta.write_text(json.dumps({"version": "2.0", "params": {"aoa": 7.0, "grid_level": 1}}))
    window.load_project_file(str(ruta))
    p = window.input_panel.get_params()
    assert p["aoa"] == 7.0 and p["grid_level"] == 1
    window.input_panel.set_params({"aoa": 0.0, "grid_level": 2})


def test_closing_keeps_the_results_of_the_case(window, tmp_path):
    """Cerrar la ventana vaciaba postProcessing y los tiempos del caso."""
    caso = tmp_path / "caso"
    (caso / "postProcessing").mkdir(parents=True)
    (caso / "6000").mkdir()
    anterior = window.case_dir
    window.case_dir = str(caso)
    window.cleanup()
    window.case_dir = anterior
    assert (caso / "postProcessing").exists() and (caso / "6000").exists()


def test_cleanup_preserves_user_mesh(window, tmp_path, monkeypatch):
    """Cerrar la app no toca la carpeta desde donde se abrio."""
    workdir = tmp_path / "wd"
    workdir.mkdir()
    nombres = ["perfil_0012.msh", "perfil_0012_sweep.msh", "debug.msh"]
    for nombre in nombres:
        (workdir / nombre).write_text("del usuario")

    monkeypatch.chdir(workdir)
    window.cleanup()

    assert sorted(p.name for p in workdir.iterdir()) == sorted(nombres)


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


def test_server_tab_shows_the_state_when_the_case_has_no_error(window):
    # instantanea() siempre trae la clave "error", casi siempre con None
    panel = window.remote_panel
    panel.case = "caso"
    panel._aplicar({"caso": "caso", "status": {"state": "running"}, "error": None, "t": 5.0, "endTime": 10.0,
                    "pct": 50.0, "procesos": 4, "coeffs": None, "residuales": {}, "servidor": {}})
    assert "EN CURSO" in panel.lbl_estado.text() and "t = 5.00000 / 10 s" in panel.lbl_estado.text()
    panel._aplicar({"caso": "caso", "status": {"state": "running"}, "error": None, "t": 500.0, "endTime": 1000.0,
                    "pct": 50.0, "estacionario": True, "coeffs": None, "residuales": {}, "servidor": {}})
    assert "iteración 500 de 1000" in panel.lbl_estado.text()
    panel._aplicar({"error": "sin red"})
    assert "sin red" in panel.lbl_estado.text()


def test_residual_plot_names_its_curves(window):
    plot = window.res_plot
    plot.reset()
    plot.update_plot("p", 0.1, 1.0)
    plot.update_plot("Ux", 0.2, 1.0)
    plot.redraw()
    assert sorted(t.get_text() for t in plot.ax.get_legend().get_texts()) == ["Ux", "p"]
    plot.reset()


def test_only_the_fields_of_the_case_can_be_chosen(window):
    panel = window.results_panel
    panel._available_fields = {"U", "p", "k", "nut", "omega"}
    panel.var_selector.setCurrentIndex(5)     # epsilon
    panel._limit_selector()
    assert panel.var_selector.currentIndex() == 0
    assert not panel.var_selector.model().item(5).isEnabled()
    assert panel.var_selector.model().item(4).isEnabled()
    panel._available_fields = None
    panel._limit_selector()
    assert panel.var_selector.model().item(5).isEnabled()


def test_residual_progress_speaks_of_iterations_when_steady(window):
    plot = window.res_plot
    plot.reset()
    plot.res_iters = [100.0]
    plot._end_time = 400.0
    plot.estacionario = True
    plot._last_saved_time = lambda: 100.0
    plot._update_progress_label()
    assert "iteración 100 de 400" in plot.progress_label.text()
    plot.estacionario = False
    plot._update_progress_label()
    assert "de 400 s" in plot.progress_label.text()
    del plot._last_saved_time
    plot.reset()


def test_theme_icons_are_found_from_any_folder():
    import re
    from gui.visual_theme import STYLESHEET
    rutas = re.findall(r'url\("([^"]+)"\)', STYLESHEET)
    assert rutas and all(os.path.isabs(r) and os.path.exists(r) for r in rutas)


def test_server_tab_lists_every_server_and_its_cases(window, monkeypatch):
    panel = window.remote_panel
    monkeypatch.setattr(panel, "refrescar_resumen", lambda: None)
    panel.set_hosts(["u@a", "u@b", "local"])
    panel._aplicar_resumen({
        "u@a": {"host": "u@a", "servidor": {"cpu_pct": 80.0, "procesos": 16}, "casos": [
            {"caso": "20261103_111623_perfil_a2.0_609b", "ruta": "~/openblade_jobs/x", "estado": "running",
             "paso": "solver", "t": 7338.0, "fin": 9000.0, "pct": 81.5},
            {"caso": "20261103_111627_perfil_a6.0_4150", "ruta": "~/openblade_jobs/y", "estado": "running",
             "paso": "en cola", "t": None, "fin": 40000.0, "pct": None},
            {"caso": "20261103_083601_perfil_a8.0_09ff", "ruta": "~/openblade_jobs/z", "estado": "done",
             "paso": "fin", "t": 40000.0, "fin": 40000.0, "pct": 100.0}]},
        "u@b": {"host": "u@b", "error": "Sin respuesta del servidor; se reintenta solo"}})
    t = panel.tabla_servidores
    assert t.rowCount() == 2 and t.item(0, 3).text() == "1 / 1" and t.item(1, 1).text().startswith("⚠️")
    c = panel.tabla_casos
    assert [c.item(i, 2).text() for i in range(c.rowCount())] == ["En curso", "En cola", "Terminó"]
    assert c.item(0, 0).text().startswith("perfil_a2.0") and c.item(0, 3).text() == "82 %"
    vistos = []
    monkeypatch.setattr(panel, "watch", lambda h, caso: vistos.append((h, caso)))
    panel._caso_elegido(2, 0)
    assert vistos == [("u@a", "~/openblade_jobs/z")]


def test_server_tab_scrolls_so_the_charts_keep_their_height(window):
    panel = window.remote_panel
    assert panel.scroll.widgetResizable() and panel.subtabs.minimumHeight() >= 400
    assert panel.scroll.widget().isAncestorOf(panel.subtabs)
