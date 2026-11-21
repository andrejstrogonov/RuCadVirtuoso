"""Панель свойств (FR-PRP-001…005): QFormLayout из ParamSpec + валидаторы.

Изменение формируется как одна undo-операция (FR-PRP-004); переименование без
дубликатов (FR-PRP-005).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QWidget,
)

from rcad.schemas.model import ParamSpec


class PropertyPanel(QWidget):
    """Поля параметров выбранного инстанса; пустая — «нет выделения»."""

    param_changed = Signal(str, str, object)  # cell, instance, {param: value}
    rename_requested = Signal(str, str, str)  # cell, old_name, new_name

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QFormLayout(self)
        self._fields: list[QDoubleSpinBox | QLineEdit] = []
        self._cell: str | None = None
        self._instance: str | None = None
        self._specs: dict[str, ParamSpec] = {}

    def bind(self, cell: str | None, instance: str | None) -> None:
        """Привязать панель к инстансу (или None — очистить)."""
        self._cell, self._instance = cell, instance
        self._clear_fields()

    def _clear_fields(self) -> None:
        while self._layout.rowCount():
            self._layout.removeRow(0)
        self._fields = []

    def show_params(self, specs: list[ParamSpec], values: dict[str, Any]) -> None:
        self._clear_fields()
        self._specs = {}
        for spec in specs:
            label = spec.name
            current = values.get(spec.name, spec.default)
            if spec.kind == "real":
                field = QDoubleSpinBox()
                field.setDecimals(9)
                field.setRange(-1e18, 1e18)
                try:
                    field.setValue(float(current))
                except (TypeError, ValueError):
                    field.setValue(0.0)
                field.valueChanged.connect(lambda v, n=spec.name: self._emit(n, v))
            else:
                field = QLineEdit(str(current))
                field.editingFinished.connect(
                    lambda n=spec.name, fld=field: self._emit(n, fld.text())
                )
            self._layout.addRow(label, field)
            self._fields.append(field)
            self._specs[spec.name] = spec

    def _emit(self, name: str, value: Any) -> None:
        if self._cell and self._instance:
            self.param_changed.emit(self._cell, self._instance, {name: value})
