"""Иерархия ячеек (FR-HIE-001…005): дерево, вход/выход, пометка битого мастера."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from rcad.services.project_service import ProjectDoc


class HierarchyNavigator(QTreeWidget):
    """Дерево ячеек проекта; клик открывает ячейку (master_cell — поддерево).

    Проект может отсутствовать (пустой экземпляр до открытия); `set_project`
    привязывает контекст и перестраивает дерево.
    """

    cell_activated = Signal(str)

    def __init__(self, project: ProjectDoc | None = None, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.setHeaderLabels(["Ячейка"])
        self.itemActivated.connect(self._on_activated)

    def set_project(self, project: ProjectDoc) -> None:
        self.project = project
        self.refresh()

    def refresh(self) -> None:
        self.clear()
        if self.project is None:
            return
        for name in self.project.cell_names:
            cell = self.project.cell(name)
            node = QTreeWidgetItem([name])
            child_masters = sorted(
                {inst.master_cell for inst in cell.instances},
                key=str,
            )
            for master in child_masters:
                child = QTreeWidgetItem(
                    [f"{master}  (инстанс)"] if master not in self.project.cells
                    else [f"{master}  (ячейка)"]
                )
                if master not in self.project.cells:
                    child.setForeground(0, Qt.red)  # FR-HIE-005: отсутствующий мастер
                node.addChild(child)
            for port in cell.ports:
                child = QTreeWidgetItem([f"порт {port.name} ({port.direction})"])
                child.setForeground(0, Qt.blue)
                node.addChild(child)
            self.addTopLevelItem(node)

    def _on_activated(self, item: QTreeWidgetItem, column: int) -> None:
        if self.project is None:
            return
        text = item.text(0)
        name = text.split("  ")[0].removeprefix("порт ")
        if name in self.project.cells:
            self.cell_activated.emit(name)
