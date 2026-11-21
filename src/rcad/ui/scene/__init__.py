"""Сцена схемы: QGraphicsScene/View, сетка, снаппинг, undo/redo (FR-GRD, FR-PLC, FR-SEL).

Модель документа — pydantic `CellSchema`; сцена — её представление. Каждое
изменяющее действие — `QUndoCommand` над моделью + `sync()` (инкрементальная
перерисовка). Слой Qt: виджеты зависят от CanvasApi-контракта, а не наоборот.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPen, QUndoCommand, QUndoStack
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView

from rcad.schemas.cell import CellSchema  # noqa: F401
from rcad.schemas.symbol import SymbolSchema

GRID = 10


class SetInstanceCommand(QUndoCommand):
    """Одна undo-операция: заменить инстанс (FR-PRP-004, FR-SEL-004)."""

    def __init__(
        self,
        scene: SchematicScene,
        index: int,
        new_instance: Any,
        text: str = "изменить инстанс",
    ) -> None:
        super().__init__(text)
        self.scene = scene
        self.index = index
        self.old_instance = scene.cell.instances[index]
        self.new_instance = new_instance

    def redo(self) -> None:
        self._apply(self.new_instance)

    def undo(self) -> None:
        self._apply(self.old_instance)

    def _apply(self, instance: Any) -> None:
        instances = list(self.scene.cell.instances)
        instances[self.index] = instance
        self.scene.cell = self.scene.cell.model_copy(update={"instances": instances})
        self.scene.sync()


class PlaceCommand(QUndoCommand):
    def __init__(self, scene: SchematicScene, instance: Any, index: int) -> None:
        super().__init__("разместить")
        self.scene = scene
        self.instance = instance
        self.index = index

    def redo(self) -> None:
        instances = list(self.scene.cell.instances)
        instances.insert(self.index, self.instance)
        self.scene.cell = self.scene.cell.model_copy(update={"instances": instances})
        self.scene.sync()

    def undo(self) -> None:
        instances = list(self.scene.cell.instances)
        del instances[self.index]
        self.scene.cell = self.scene.cell.model_copy(update={"instances": instances})
        self.scene.sync()


class DeleteCommand(QUndoCommand):
    def __init__(self, scene: SchematicScene, index: int) -> None:
        super().__init__("удалить")
        self.scene = scene
        self.index = index
        self.old_instance = scene.cell.instances[index]

    def redo(self) -> None:
        instances = list(self.scene.cell.instances)
        del instances[self.index]
        self.scene.cell = self.scene.cell.model_copy(update={"instances": instances})
        self.scene.sync()

    def undo(self) -> None:
        instances = list(self.scene.cell.instances)
        instances.insert(self.index, self.old_instance)
        self.scene.cell = self.scene.cell.model_copy(update={"instances": instances})
        self.scene.sync()


class _InstanceItem(QGraphicsItem):
    def __init__(self, scene: SchematicScene, idx: int) -> None:
        super().__init__()
        self.scene_ref = scene
        self.idx = idx

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(-35, -35, 70, 70)

    def paint(self, painter, option, widget=None) -> None:  # type: ignore[no-untyped-def]
        symbol = self.scene_ref.symbol_for(self.scene_ref.cell.instances[self.idx].master_cell)
        pen = QPen(QColor("#1a5fb4"))
        pen.setWidth(1)
        painter.setPen(pen)
        if symbol is None:
            painter.drawRect(self.boundingRect())
            return
        for element in symbol.graphics:
            kind = element.type
            if kind == "line":
                painter.drawLine(QPointF(*element.points[0]), QPointF(*element.points[1]))
            elif kind == "polyline":
                pts = [QPointF(x, y) for x, y in element.points]
                for a, b in zip(pts, pts[1:], strict=False):
                    painter.drawLine(a, b)
            elif kind == "circle":
                painter.drawEllipse(QPointF(*element.center), element.r, element.r)
            elif kind == "arc":
                painter.drawRect(QRectF(element.box[0], element.box[1], element.width, element.height))


class SchematicScene(QGraphicsScene):
    """Хранит ячейку (pydantic) и список items; `sync()` перестраивает."""

    def __init__(
        self,
        cell: CellSchema,
        symbols: dict[str, SymbolSchema],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(50)  # FR-SEL-003
        self.cell = cell
        self.symbols = symbols
        self._items: list[_InstanceItem] = []
        self.setSceneRect(QRectF(-1000, -1000, 4000, 2000))
        self.setBackgroundBrush(QColor("#ffffff"))
        self.sync()

    # --- модель и представление ----------------------------------------------

    def symbol_for(self, master: str) -> SymbolSchema | None:
        return self.symbols.get(master)

    def sync(self) -> None:
        self.clear()
        self._items = []
        for idx, inst in enumerate(self.cell.instances):
            item = _InstanceItem(self, idx)
            item.setPos(inst.x, inst.y)
            item.setSelected(True)
            self.addItem(item)
            self._items.append(item)
        for wire in self.cell.wires:
            if len(wire.points) >= 2:
                self.addLine(
                    wire.points[0][0], wire.points[0][1],
                    wire.points[-1][0], wire.points[-1][1],
                    QPen(QColor("#3584e4"), 1),
                )

    def snap(self, x: float, y: float) -> tuple[int, int]:
        """Привязка к сетке 10 px (FR-GRD-001)."""
        return (round(x / GRID) * GRID, round(y / GRID) * GRID)

    def place(self, instance: Any) -> None:
        command = PlaceCommand(self, instance, len(self.cell.instances))
        self.undo_stack.push(command)

    def delete_selected(self) -> None:
        for item in self.selectedItems():
            if isinstance(item, _InstanceItem):
                index = item.idx
                existing = list(self.cell.instances)
                if index < len(existing) and existing[index] is not None:
                    self.undo_stack.push(DeleteCommand(self, index))
                break

    def instance_item_at(self, pos: QPointF) -> int | None:
        for _i, item in enumerate(self._items):
            if item.contains(pos.x(), pos.y()):
                return item.idx
        return None


class SchematicView(QGraphicsView):
    """Вью сцены: панорамирование колесом, выделение кликом."""

    def __init__(self, scene: QGraphicsScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setRenderHint(self.renderHints())
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self._panning = False

    def wheelEvent(self, event) -> None:  # noqa: N802
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
