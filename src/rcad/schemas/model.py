"""Метаданные библиотеки моделей (`data/Libraries/*.json`) и спецификации параметров.

`ModelEntry` повторяет схему файлов библиотек; `ParamSpec` — контракт параметра
прибора (FR-PRP-001…003): тип, диапазон, единица. Диапазон берётся из метаданных
модели; при отсутствии `bounds` панель свойств не накладывает числовых ограничений.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["device", "primitive"]
Card = Literal["R", "C", "L", "V", "I", "E", "G", "F", "H", "M", "X", "D", "Q", "B"]
ParamKind = Literal["real", "int", "choice"]


class ParamSpec(BaseModel):
    """Спецификация одного параметра модели (имя, тип, диапазон, единица)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[str, Field(min_length=1)]
    kind: ParamKind = "real"
    default: float | int | str = 0.0
    unit: str | None = None
    bounds: tuple[float, float] | None = None
    description_ru: str = ""
    description_en: str = ""

    def validate_value(self, value: object) -> None:
        """Проверка типа и диапазона; на провал кидает соответствующие исключения.

        Вызывается панелью свойств и CanvasApi (FR-PRP-002/003, FR-PRP-001).
        """
        from rcad.diagnostics import ParameterRangeError, ParameterTypeError

        if self.kind in ("real", "int"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ParameterTypeError(param=self.name, value=value)
            number = float(value)
            if self.kind == "int" and int(number) != number:
                raise ParameterTypeError(param=self.name, value=value)
            if self.bounds is not None:
                low, high = self.bounds
                if not (low <= number <= high):
                    raise ParameterRangeError(
                        param=self.name, value=value, bounds=self.bounds
                    )
        # kind == "choice": любое значение передаётся модели как есть
        # (строковые PULSE-параметры не нормализуются — контракт S3).


class ModelEntry(BaseModel):
    """Запись технологической библиотеки: примитив или встроенный/VA-прибор."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cell: Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
    role: Role
    netlist_card: Card
    params: dict[str, float | int | str] = Field(default_factory=dict)
    include: str = "*"
    subckt: str | None = None
    pins: list[str] = Field(default_factory=list)

    @property
    def is_native(self) -> bool:
        """Нативный прибор: карта без `.include` внешнего файла."""
        return self.include == "*"


class LibrarySchema(BaseModel):
    """Один файл библиотеки (`data/Libraries/*.json`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
    title: str = ""
    node: str = ""
    cells: list[ModelEntry] = Field(min_length=1)
