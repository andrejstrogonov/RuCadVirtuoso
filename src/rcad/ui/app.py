"""Приложение и главное окно (NFR-UI-001…005, FR-PRS-002, FR-SIM, FR-PLT).

Компоновка: библиотека слева, сцена в центре, свойства справа, логи снизу.
Закрытие окна с несохранёнными изменениями — «Сохранить/Не сохранять/Отмена».
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
)

from rcad.services.project_service import ProjectDoc, ProjectService
from rcad.ui.dialogs.analysis import AnalysisDialog
from rcad.ui.dialogs.simulator_service import SimulatorService
from rcad.ui.event_bus import EventHub
from rcad.ui.plots.plot_window import PlotWindow
from rcad.ui.scene import SchematicScene, SchematicView
from rcad.ui.widgets.command_palette import CommandPalette
from rcad.ui.widgets.hierarchy import HierarchyNavigator
from rcad.ui.widgets.library_panel import LibraryPanel
from rcad.ui.widgets.message_log import MessageLog
from rcad.ui.widgets.netlist_view import NetlistView
from rcad.ui.widgets.property_panel import PropertyPanel


def create_app(argv: list[str] | None = None) -> QApplication:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)  # NFR-UI-004
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("RuCadVirtuoso")
    return app


class MainWindow(QMainWindow):
    def __init__(self, service: ProjectService | None = None, parent=None) -> None:
        super().__init__(parent)
        self.service = service or ProjectService()
        self.project: ProjectDoc | None = None
        self.current_cell: str | None = None
        self.dirty = False
        self.events = EventHub()

        self.scene: SchematicScene | None = None
        self._setup_ui()
        self._setup_shortcuts()
        self._setup_autosave()

    # --- UI -------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("RuCadVirtuoso")
        self.resize(1280, 800)

        self.library = LibraryPanel(self.service.model_manager)
        self.hierarchy = HierarchyNavigator(self)
        self.properties = PropertyPanel()
        self.log = MessageLog()
        self.netlist_view = NetlistView()

        self._scene_view = None
        self.dock_library = QDockWidget("Библиотека", self)
        self.dock_library.setWidget(self.library)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_library)

        self.setCentralWidget(self._placeholder())

        self.dock_props = QDockWidget("Свойства", self)
        self.dock_props.setWidget(self.properties)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_props)

        self.dock_hier = QDockWidget("Иерархия", self)
        self.dock_hier.setWidget(self.hierarchy)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_hier)

        self.dock_log = QDockWidget("Сообщения", self)
        self.dock_log.setWidget(self.log)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock_log)

        self.dock_nlv = QDockWidget("Netlist", self)
        self.dock_nlv.setWidget(self.netlist_view)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock_nlv)

        self._build_menus()
        self.simulator = SimulatorService(self)
        self.simulator.finished.connect(self._on_sim_finished)
        self.simulator.failed.connect(lambda msg: self.log.append(
            _error_diag(msg)
        ))

    def _placeholder(self):

        label = QLabel("Схема: откройте проект")
        label.setAlignment(Qt.AlignCenter)
        self._placeholder_label = label
        self._placeholder_label.setObjectName("placeholder")
        return label

    def _build_menus(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("Файл")
        open_action = QAction("Открыть проект...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_dialog)
        file_menu.addAction(open_action)
        save_action = QAction("Сохранить", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._save)
        file_menu.addAction(save_action)
        exit_action = QAction("Выход", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        sim_menu = menubar.addMenu("Анализ")
        run_action = QAction("Запустить анализ...", self)
        run_action.setShortcut("A")
        run_action.triggered.connect(self._open_analysis)
        sim_menu.addAction(run_action)

    def _setup_shortcuts(self) -> None:
        self.palette = CommandPalette(self, self)
        self.palette.triggered.connect(self._on_command)

    def _setup_autosave(self) -> None:
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(5 * 60 * 1000)  # FR-PRS-001: 5 минут
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()

    # --- проект ------------------------------------------------------------

    def open_project(self, path: Path | str) -> None:
        self.project = self.service.open(path)
        self.setWindowTitle(f"RuCadVirtuoso — {self.project.name}")
        for diag in self.project.diagnostics:
            self.log.append(diag)
        self.current_cell = next(iter(self.project.cell_names), None)
        self.hierarchy.set_project(self.project)
        self.hierarchy.cell_activated.connect(self._on_cell_activated)
        if self.current_cell:
            self._load_cell(self.current_cell)
        if self.current_cell is None:
            self.properties.bind(None, None)

    def _open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Открыть проект", "", "Проект (*.rcad)")
        if path:
            self.open_project(Path(path))

    def _load_cell(self, name: str) -> None:
        if self.project is None or name not in self.project.cells:
            return
        cell = self.project.cell(name)
        sym = {
            c: self.service.model_manager.symbol(c)
            for c in self.service.model_manager.cell_names()
            if self.service.model_manager.symbol(c) is not None
        }
        self.scene = SchematicScene(cell, sym)
        self.setCentralWidget(SchematicView(self.scene))
        self._selected_cell = name
        self.netlist_view.project = self.project
        self.netlist_view.refresh_cell(name)
        self.properties.bind(name, None)

    def _on_cell_activated(self, name: str) -> None:
        self._load_cell(name)

    def _save(self) -> None:
        if self.project is None:
            return
        self.service.save(self.project)
        self.dirty = False
        self.statusBar().showMessage(f"Сохранено: {self.project.name}", 3000)

    def _autosave(self) -> None:
        if self.project is not None and self.dirty:
            self.service.autosave(self.project, changed_cells=set(self.project.cells))
            self.statusBar().showMessage("Автосохранение", 2000)

    # --- команды ------------------------------------------------------------

    def _on_command(self, action: str) -> None:
        if action == "save":
            self._save()
        elif action == "analyze":
            self._open_analysis()
        elif self.scene is not None:
            if action == "rotate":
                self._rotate_selected()
            elif action in ("mirror_x", "mirror_y"):
                self._mirror_selected(action)
            elif action == "delete":
                self.scene.delete_selected()
                self.dirty = True

    def _rotate_selected(self) -> None:
        if self.scene is None or self._selected_cell is None:
            return
        cell = self.project.cell(self._selected_cell)
        for item in self.scene.selectedItems():
            idx = getattr(item, "idx", None)
            if idx is None or idx >= len(cell.instances):
                continue
            inst = cell.instances[idx]
            updated = inst.model_copy(update={"rotation": (inst.rotation + 90) % 360})
            self.scene.undo_stack.push(_SetInstance(self.scene, idx, updated))
        self.dirty = True

    def _mirror_selected(self, axis: str) -> None:
        if self.scene is None or self._selected_cell is None:
            return
        cell = self.project.cell(self._selected_cell)
        for item in self.scene.selectedItems():
            idx = getattr(item, "idx", None)
            if idx is None or idx >= len(cell.instances):
                continue
            inst = cell.instances[idx]
            mirror = "x" if axis == "mirror_x" else "y"
            updated = inst.model_copy(update={"mirror": mirror})
            self.scene.undo_stack.push(_SetInstance(self.scene, idx, updated))
        self.dirty = True

    def _open_analysis(self) -> None:
        if self.project is None or not self._selected_cell:
            return
        dialog = AnalysisDialog(self.project, self._selected_cell, self)
        if dialog.exec() == dialog.Accepted:
            self._start_analysis(dialog)

    def _start_analysis(self, dialog: AnalysisDialog) -> None:
        error = dialog.validate()
        if error:
            self.log.append(_error_diag(error))
            return
        spec = dialog.build_spec()
        cell = self._selected_cell
        self.dialog_series = dialog.selected_series()

        def runner():
            from rcad.core.analyses import run_analysis
            from rcad.services.netlister import netlist_for

            directive = spec.to_directive()
            netlist = netlist_for(self.project, cell,
                                  dc=directive if spec.type == "dc" else None,
                                  tran=directive if spec.type == "tran" else None,
                                  ac=directive if spec.type == "ac" else None)
            return run_analysis(netlist, directive)

        self.simulator.run(runner)

    def _on_sim_finished(self, result) -> None:
        if self.project is None:
            return
        from rcad.schemas.result import ResultMeta

        names = [n for n in result.names() if n != "time"]
        meta = ResultMeta(analysis_type="tran" if "time" in result.names() else "dc", rows=len(result["time"]))
        self.log.append_meta(meta)
        self.last_result = result
        self.plot_window = PlotWindow(result, names if not self.dialog_series else self.dialog_series)
        self.plot_window.show()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.project is not None and self.dirty:
            answer = QMessageBox.question(
                self, "Несохранённые изменения",
                "Сохранить изменения перед закрытием?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            )
            if answer == QMessageBox.Save:
                self._save()
            elif answer == QMessageBox.Cancel:
                event.ignore()
                return
        event.accept()


def _SetInstance(scene, index, instance):
    """Re-export небольшого undo-команда для вращения/зеркала."""
    from rcad.ui.scene import SetInstanceCommand

    return SetInstanceCommand(scene, index, instance)


def _error_diag(message: str):
    from rcad.diagnostics import Diagnostic, DiagnosticCode

    return Diagnostic(code=DiagnosticCode.E_ANALYSIS, message=str(message),
                      hint_ru="Ошибка анализа: см. сообщение выше.")
