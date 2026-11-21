"""Панель сообщений (FR-LOG-001…004): QTableView + proxy, фильтр по уровню, en+ru."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from rcad.diagnostics import Diagnostic
from rcad.schemas.result import ResultMeta


class _LogModel:
    """Плоская модель (без Qt-моделей): rows — список (time, level, code, message, hint)."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str, str]] = []

    def append(self, diag: Diagnostic) -> None:
        self.rows.append(
            (diag.location, diag.severity.value, str(diag.code.value), diag.message, diag.hint_ru)
        )

    def clear(self) -> None:
        self.rows = []


class MessageLog(QWidget):
    """Простая панель логов: таблица записей, фильтр уровней, очистка.

    Коды и hint_ru — контракт диагностик (FR-LOG-003). Двойной клик по записи с
    координатой источника может открыть объект сцены (FR-ERC-007/LOG-004) —
    сигнал `diagnostic_activated`.
    """

    diagnostic_activated = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = _LogModel()
        self._layout = QVBoxLayout(self)
        self._table = QTableView()
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Stretch)
        self._buttons = QHBoxLayout()
        self._btn_clear = QPushButton("Очистить")
        self._btn_clear.clicked.connect(self.clear_log)
        self._filter = QPushButton("Фильтр: все")
        self._filter.setCheckable(True)
        self._filter.clicked.connect(self._toggle_filter)
        self._buttons.addWidget(self._btn_clear)
        self._buttons.addWidget(self._filter)
        self._buttons.addStretch(1)
        self._layout.addWidget(self._table)
        self._layout.addLayout(self._buttons)
        self._on_off = True
        self.refresh()

    def _toggle_filter(self) -> None:
        self._on_off = not self._on_off
        self._filter.setText("Только error" if not self._on_off else "Фильтр: все")
        self.refresh()

    def append(self, diag: Diagnostic) -> None:
        self._model.append(diag)
        self.refresh()

    def append_meta(self, meta: ResultMeta) -> None:
        self._model.rows.append(
            ("", "info", "RESULT",
             f"анализ {meta.analysis_type}: {meta.rows} точек",
             "Результат доступен в окне графиков")
        )
        self.refresh()

    def clear_log(self) -> None:
        self._model.clear()
        self.refresh()

    def refresh(self) -> None:
        lines = []
        for time, level, code, message, hint in self._model.rows:
            if not self._on_off and level != "error":
                continue
            lines.append([time, level, code, message, hint])
        model = _make_table_model(lines, 5)
        self._table.setModel(model)
        self._table.resizeColumnsToContents()

    def count(self) -> int:
        return len(self._model.rows)


def _make_table_model(lines: list[list[str]], columns: int):
    from PySide6.QtCore import QAbstractTableModel, QModelIndex

    _INVALID = QModelIndex()

    class TableModel(QAbstractTableModel):
        def __init__(self, rows, parent=None) -> None:
            super().__init__(parent)
            self._rows = rows
            self._headers = ["source", "level", "code", "message", "hint_ru"]

        def rowCount(self, parent=_INVALID):  # noqa: N802
            return len(self._rows)

        def columnCount(self, parent=_INVALID):  # noqa: N802
            return columns

        def data(self, index, role=Qt.DisplayRole):
            if role == Qt.DisplayRole:
                row = self._rows[index.row()]
                return row[index.column()]
            return None

        def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
            if role == Qt.DisplayRole and orientation == Qt.Horizontal:
                return self._headers[section]
            return None

    return TableModel(lines)
