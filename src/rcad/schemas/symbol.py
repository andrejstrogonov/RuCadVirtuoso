"""Символьное представление (УГО) ячейки: `symbols/<cell>.json` (ТЗ п. 6.1, FR-PRJ-010, FR-HIE-004).

Файл символа описывает графику и выводы независимо от схемы. Координаты — в
пикселях холста, ось Y направлена вниз (как у `QGraphicsScene`); начало
координат — центр символа. Выводы обязаны лежать на сетке 10 px (ТЗ п. 10.1),
поэтому 0 является допустимой координатой, а `side` выводится из положения пина.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GRID = 10
MAX_STROKE = 10

Point = tuple[int, int]
Side = Literal["left", "right", "top", "bottom"]


class _Element(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Line(_Element):
    type: Literal["line"] = "line"
    points: Annotated[list[Point], Field(min_length=2)]
    width: Annotated[int, Field(ge=0, le=MAX_STROKE)] = 1


class Polyline(_Element):
    type: Literal["polyline"] = "polyline"
    points: Annotated[list[Point], Field(min_length=2)]
    closed: bool = False
    fill: Literal["none", "background"] = "none"
    width: Annotated[int, Field(ge=0, le=MAX_STROKE)] = 1


class Circle(_Element):
    type: Literal["circle"] = "circle"
    center: Point
    r: Annotated[int, Field(ge=1)]
    fill: Literal["none", "background"] = "none"
    width: Annotated[int, Field(ge=0, le=MAX_STROKE)] = 1


class Arc(_Element):
    """Дуга/эллипс, вписанный в рамку `box`, углы в градусах против часовой стрелки."""

    type: Literal["arc"] = "arc"
    box: Point
    width: Annotated[int, Field(ge=1)]
    height: Annotated[int, Field(ge=1)]
    start: float = 0.0
    span: float = 360.0
    width_px: Annotated[int, Field(ge=0, le=MAX_STROKE)] = 1


Shape = Annotated[Line | Polyline | Circle | Arc, Field(discriminator="type")]


def side_of(point: Point) -> Side:
    """Сторона, с которой вывод приходит к символу: вывод на оси Y уходит
    вправо, всё остальное определяется знаком координаты."""
    x, y = point
    if y < 0:
        return "top"
    if y > 0:
        return "bottom"
    return "right" if x > 0 else "left"


class Pin(_Element):
    name: Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")]
    x: int
    y: int
    side: Side

    @property
    def point(self) -> Point:
        return (self.x, self.y)


class SymbolSchema(_Element):
    cell: Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
    kind: Literal["auto", "manual"] = "manual"
    pins: Annotated[list[Pin], Field(min_length=1)]
    graphics: list[Shape]

    @model_validator(mode="after")
    def _check(self) -> SymbolSchema:
        names = [pin.name for pin in self.pins]
        if len(set(names)) != len(names):
            raise ValueError(f"{self.cell}: имена выводов повторяются: {names}")
        points = [(pin.x, pin.y) for pin in self.pins]
        if len(set(points)) != len(points):
            raise ValueError(f"{self.cell}: два вывода в одной точке: {points}")
        for pin in self.pins:
            if pin.x % GRID or pin.y % GRID:
                raise ValueError(f"{self.cell}: вывод {pin.name} вне сетки {GRID} px: {(pin.x, pin.y)}")
            expected = side_of(pin.point)
            if pin.side != expected:
                raise ValueError(
                    f"{self.cell}: вывод {pin.name} в точке {(pin.x, pin.y)} должен иметь side={expected}"
                )
        return self
