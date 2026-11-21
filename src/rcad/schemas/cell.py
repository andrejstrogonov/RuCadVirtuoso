"""Схема ячейки (`cells/<cell>.json`, ТЗ п. 6.1, FR-CEL-001…007).

Модель документа — неизменяемые pydantic-объекты; сцена — их представление
(ARCH §8.2). Сериализация канонична: `model_dump_json` с полями в порядке
объявления, чтобы reopen-сравнение S1 (побайтовое равенство JSON) проходило.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Rotation = Literal[0, 90, 180, 270]
Mirror = Literal["none", "x", "y"]
PortDirection = Literal["in", "out", "inout", "bi"]

Point = tuple[int, int]

_NET_NAME = r"^[A-Za-z_$][A-Za-z0-9_$]*$|^0$"
_INST_NAME = r"^[A-Za-z_$][A-Za-z0-9_$]*$"
_CELL_NAME = r"^[A-Za-z_$][A-Za-z0-9_$]*$"


def transform_point(
    x: int,
    y: int,
    rotation: Rotation = 0,
    mirror: Mirror = "none",
) -> tuple[int, int]:
    """Преобразование координат вывода при повороте/зеркале инстанса (FR-CEL-003).

    Сначала зеркало (отражение относительно оси символа), затем поворот на 90°
    по часовой стрелке `rotation` шагами. Осевые символы (R/C) не обязательно
    симметричны; правило едино для всех.
    """
    if mirror == "x":
        x, y = -x, y
    elif mirror == "y":
        x, y = x, -y
    steps = rotation // 90
    for _ in range(steps):
        x, y = -y, x  # поворот на 90° по часовой: (x, y) → (−y, x)
    return x, y


class PortSchema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[str, Field(pattern=_NET_NAME, min_length=1)]
    direction: PortDirection = "inout"
    x: int
    y: int


class InstanceSchema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[str, Field(pattern=_INST_NAME, min_length=1)]
    master_cell: Annotated[str, Field(pattern=_CELL_NAME, min_length=1)]
    x: int = 0
    y: int = 0
    rotation: Rotation = 0
    mirror: Mirror = "none"
    params: dict[str, float | int | str] = Field(default_factory=dict)
    nodes: list[str] = Field(default_factory=list)


class WireSchema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    net: Annotated[str, Field(pattern=_NET_NAME, min_length=1)]
    points: Annotated[list[Point], Field(min_length=2)]


class JunctionSchema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    x: int
    y: int


class CellSchema(BaseModel):
    """Схема одной ячейки: инстансы, провода, порты, junction-точки.

    `hierarchy_children` — имена мастеров, являющихся локальными ячейками проекта
    (S4: `subckt` → ячейки). Поддерживается при создании/импорте, чтобы
    `export_netlist` воспроизводил `.subckt`-заглушки.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[str, Field(pattern=_CELL_NAME, min_length=1)]
    ports: list[PortSchema] = Field(default_factory=list)
    instances: list[InstanceSchema] = Field(default_factory=list)
    wires: list[WireSchema] = Field(default_factory=list)
    junctions: list[JunctionSchema] = Field(default_factory=list)
    hierarchy_children: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_unique_names(self) -> CellSchema:
        inst_names = [inst.name for inst in self.instances]
        dup_inst = {name for name in inst_names if inst_names.count(name) > 1}
        if dup_inst:
            raise ValueError(f"{self.name}: имена инстансов повторяются: {sorted(dup_inst)}")
        net_names = [wire.net for wire in self.wires]
        dup_net = {name for name in net_names if net_names.count(name) > 1}
        if dup_net:
            raise ValueError(f"{self.name}: имена net повторяются: {sorted(dup_net)}")
        return self

    def net_names(self) -> set[str]:
        return {wire.net for wire in self.wires}
