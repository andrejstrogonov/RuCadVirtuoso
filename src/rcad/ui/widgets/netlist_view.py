"""Netlist-вью (FR-NLV-001…005): read-only QPlainTextEdit, автообновление, импорт/экспорт."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPlainTextEdit

from rcad.services.project_service import ProjectDoc


class NetlistView(QPlainTextEdit):
    """Текст netlist текущей иерархии; обновляется при изменении схемы.

    Только-чтение (FR-NLV-002); экспорт/импорт — через сервисы/диалоги.
    """

    export_requested = Signal()
    import_requested = Signal()

    def __init__(self, project: ProjectDoc | None = None, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

    def refresh_cell(self, cell: str | None) -> None:
        if cell is None or self.project is None or cell not in self.project.cells:
            self.clear()
            return
        from rcad.services.netlister import export_netlist

        try:
            self.setPlainText(export_netlist(self.project, cell))
        except Exception as exc:  # граница UI: ошибка в лог, не крашимся
            self.setPlainText(f"; ошибка netlist: {exc}")
