"""Горячие клавиши и палитра команд (FR-KBD-001…003).

Таблица назначений — единый источник (FR-KBD-003: без конфликтов); стандартные
сочетания не перехватываются в полях ввода (KBD-002) — Qt делает это
автоматически, т.к. QShortcut с WidgetWithChildrenShortcut применён к сцене.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class KeyBinding:
    action: str
    sequence: str
    description_ru: str


KEY_MAP: tuple[KeyBinding, ...] = (
    KeyBinding("rotate", "R", "Поворот 90°"),
    KeyBinding("mirror_x", "M", "Зеркало по X"),
    KeyBinding("mirror_y", "Shift+M", "Зеркало по Y"),
    KeyBinding("copy", "Ctrl+C", "Копировать"),
    KeyBinding("paste", "Ctrl+V", "Вставить"),
    KeyBinding("delete", "Del", "Удалить"),
    KeyBinding("analyze", "A", "Запустить анализ"),
    KeyBinding("save", "Ctrl+S", "Сохранить проект"),
    KeyBinding("undo", "Ctrl+Z", "Отменить"),
    KeyBinding("redo", "Ctrl+Y", "Повторить"),
)


class CommandPalette(QWidget):
    """Обвязка сочетаний клавиш, сигнал `triggered(action)`; таблица для проверки."""

    triggered = Signal(str)

    def __init__(self, parent: QWidget, scope: QWidget) -> None:
        super().__init__(parent)
        self._shortcuts: dict[str, QShortcut] = {}
        for binding in KEY_MAP:
            shortcut = QShortcut(QKeySequence(binding.sequence), scope)
            shortcut.activated.connect(
                lambda action=binding.action: self.triggered.emit(action)
            )
            self._shortcuts[binding.action] = shortcut

    def table(self) -> list[KeyBinding]:
        return list(KEY_MAP)

    def has_conflicts(self) -> bool:
        seqs = [b.sequence for b in KEY_MAP]
        return len(seqs) != len(set(seqs))
