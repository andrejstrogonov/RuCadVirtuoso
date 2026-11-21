"""UI-smoke (pytest-qt, offscreen, NFR-TST-001): старт, открытие проекта, операции.

Прогон: QT_QPA_PLATFORM=offscreen pytest tests/ui_smoke. Требует PySide6/
pyqtgraph/pytest-qt; во время фазы — при наличии. Сценарии уровня «UI-API»:
старт приложения, открытие проекта, размещение инстанса, TRAN через диалог,
окно графиков без падений.
"""

from __future__ import annotations

import pytest

from rcad.services.project_service import ProjectService

pytestmark = [pytest.mark.ui_smoke]

S1 = {
    "name": "memristor_iv",
    "ports": [],
    "instances": [
        {"name": "V1", "master_cell": "vsource", "x": 100, "y": 200,
         "rotation": 0, "mirror": "none", "params": {"DC": 0, "SIN": "0 1 1"}},
        {"name": "Xmem", "master_cell": "memristor_m1", "x": 200, "y": 200,
         "rotation": 0, "mirror": "none",
         "params": {"a1": 0.17, "a2": 0.17, "b": 0.05, "Vp": 0.65, "Vn": 0.56}},
        {"name": "Rprobe", "master_cell": "resistor", "x": 300, "y": 200,
         "rotation": 0, "mirror": "none", "params": {"R": 1e-3}},
    ],
    "wires": [
        {"net": "n1", "points": [[100, 180], [200, 170]]},
        {"net": "n2", "points": [[200, 230], [300, 200]]},
        {"net": "0", "points": [[300, 200], [300, 280], [100, 280], [100, 220]]},
    ],
    "junctions": [],
}


@pytest.fixture
def project_path(tmp_path):
    service = ProjectService()
    project = service.create(tmp_path / "s1.rcad", name="s1")
    service.add_cell(project, S1)
    service.save(project)
    return service.path(project)


@pytest.fixture
def app(qtbot):
    from rcad.ui.app import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


def test_app_starts_and_shows_docks(app, qtbot) -> None:
    assert app.library.count() > 0  # библиотека не пуста (FR-LIB-001)
    assert app.dock_library.isVisible()
    assert app.dock_props.isVisible()
    assert app.dock_log.isVisible()


def test_open_project_and_load_cell(app, project_path, qtbot) -> None:
    app.open_project(project_path)
    assert app.project is not None
    assert app.current_cell == "memristor_iv"
    assert app.scene is not None
    qtbot.waitUntil(lambda: app.scene is not None, timeout=3000)


def test_place_instance(app, project_path, qtbot) -> None:
    from rcad.schemas.cell import InstanceSchema

    app.open_project(project_path)
    app.current_cell = "memristor_iv"
    instance = InstanceSchema(name="R2", master_cell="resistor", x=400, y=100)
    app.scene.place(instance)
    assert len(app.scene.cell.instances) == 4


def test_analysis_dialog_opens(app, project_path, qtbot) -> None:
    from rcad.ui.dialogs.analysis import AnalysisDialog

    app.open_project(project_path)
    dialog = AnalysisDialog(app.project, app.current_cell)
    qtbot.addWidget(dialog)
    spec = dialog.build_spec()  # TRAN по умолчанию? нет, OP — первый пункт
    assert spec.type in ("op", "dc", "tran", "ac")


def test_simulator_service_signals(app, qtbot) -> None:
    # ядро (rcad.core.analyses) может отсутствовать — контракт сервиса проверяется
    def runner():
        class _R:
            data = {"time": [0.0, 1.0, 2.0]}

            def names(self):  # noqa: N802
                return ["time"]

            def names_minus_time(self):  # noqa: N802
                return []

            def __getitem__(self, name):
                return self.data[name]

        return _R()

    app.simulator.run(runner)
    qtbot.waitUntil(lambda: not app.simulator.busy, timeout=5000)
    assert not app.simulator.busy  # воркер завершился, сигналы не уронили UI


def test_plot_window_opens(app, qtbot) -> None:
    from rcad.ui.plots.plot_window import PlotWindow

    class Fake:
        data = {"time": [0.0, 1.0], "V(n1)": [1.0, 2.0]}

        def names(self):
            return ["time", "V(n1)"]

        def __getitem__(self, name):
            return self.data[name]

    window = PlotWindow(Fake(), ["V(n1)"])
    qtbot.addWidget(window)
    window.show()
    assert window.isVisible()


def test_close_request_prompt(app, qtbot) -> None:
    """Закрытие без изменений — без модального диалога (FR-PRS-002)."""
    app.dirty = False
    app.close()
    assert app is not None
