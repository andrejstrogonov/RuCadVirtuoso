"""Панель библиотеки (FR-LIB-001/002, FR-PLC-001): список ячеек + drag&drop."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from rcad.services.model_manager import ModelManager


class LibraryPanel(QListWidget):
    """Список примитивов и приборов из ModelManager; drag&drop на сцену."""

    cell_dragged = Signal(str, int, int)  # master, x_snap, y_snap

    def __init__(self, manager: ModelManager | None = None, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager or ModelManager()
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.refresh()

    def refresh(self) -> None:
        """Пересборка из библиотеки (FR-LIB-002: обновление после импорта VA)."""
        self.clear()
        self._masters: dict[str, str] = {}
        for entry in self.manager.panel_cells():
            item = QListWidgetItem(f"{entry.cell}  [{entry.netlist_card}]")
            item.setData(Qt.UserRole, entry.cell)
            item.setToolTip(f"{entry.role}: {entry.subckt or 'примитив'}")
            self.addItem(item)
            self._masters[entry.cell] = entry.cell
        # VA-секция скрыта, пока нет rcad.veriloga (план F8).
        if not self._va_available():
            pass

    @staticmethod
    def _va_available() -> bool:
        import importlib.util

        return importlib.util.find_spec("rcad.veriloga") is not None

    def startDrag(self, supported: Qt.DropActions) -> None:  # noqa: N802
        item = self.currentItem()
        if item is None:
            return
        master = item.data(Qt.UserRole)
        mime = QMimeData()
        mime.setText(master)
        from PySide6.QtWidgets import QDrag

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(supported)
