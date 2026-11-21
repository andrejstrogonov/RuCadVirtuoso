"""Единая система диагностики (ARCh §10.1, FR-LOG-*, НБР-ЛОГ-*).

Коды диагностик — контракт (NFR-LOC-003): стабильные идентификаторы, на которые
опираются и ядро, и сервисы, и UI. Модуль не зависит от PySide6 и может
импортироваться любым слоем выше ядра.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticCode(StrEnum):
    """Стабильные коды диагностик (контракт, NFR-LOC-003).

    `E_*` — ошибки, `W_*` — предупреждения.
    """

    E_FLOATING = "E_FLOATING"
    E_NO_DC_PATH = "E_NO_DC_PATH"
    E_NO_GROUND = "E_NO_GROUND"
    E_DUP_NAME = "E_DUP_NAME"
    E_MISSING_MASTER = "E_MISSING_MASTER"
    E_PROJECT_CORRUPT = "E_PROJECT_CORRUPT"
    E_PROJECT_VERSION = "E_PROJECT_VERSION"
    E_NETLIST = "E_NETLIST"
    E_PARAM_RANGE = "E_PARAM_RANGE"
    E_PARAM_TYPE = "E_PARAM_TYPE"
    E_CONVERGENCE = "E_CONVERGENCE"
    E_ANALYSIS = "E_ANALYSIS"
    E_MODEL = "E_MODEL"
    W_PROJECT_VERSION_OLD = "W_PROJECT_VERSION_OLD"
    W_STATE_CLIP = "W_STATE_CLIP"
    W_DC_DISCONTINUITY = "W_DC_DISCONTINUITY"
    W_UNUSED_PARAM = "W_UNUSED_PARAM"
    W_SINGLE_PIN = "W_SINGLE_PIN"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """Одна диагностическая запись.

    Поля повторяют контракт ядра (§10.1): код, уровень, сообщение на английском,
    подсказка на русском, источник (файл/строка/колонка) и имя объекта схемы.
    """

    code: DiagnosticCode | str
    severity: Severity = Severity.ERROR
    message: str = ""
    hint_ru: str = ""
    file: str = ""
    line: int | None = None
    column: int | None = None
    object_name: str = ""

    @property
    def is_error(self) -> bool:
        return self.severity == Severity.ERROR

    @property
    def location(self) -> str:
        """Компактное "file:line:col" для панели логов (FR-NLV-005)."""
        out = self.file
        if self.line is not None:
            out += f":{self.line}"
            if self.column is not None:
                out += f":{self.column}"
        return out


@dataclass(slots=True)
class DiagnosticBag:
    """Накопитель диагностик + быстрые предикаты (ошибка среди записей)."""

    items: list[Diagnostic] = field(default_factory=list)

    def add(self, diagnostic: Diagnostic) -> None:
        self.items.append(diagnostic)

    def extend(self, diagnostics: Iterable[Diagnostic]) -> None:
        self.items.extend(diagnostics)

    @property
    def has_errors(self) -> bool:
        return any(item.is_error for item in self.items)

    @property
    def errors(self) -> list[Diagnostic]:
        return [item for item in self.items if item.is_error]

    def __bool__(self) -> bool:
        return bool(self.items)

    def __len__(self) -> int:
        return len(self.items)


class RcadError(Exception):
    """Базовое исключение приложения; несёт диагностику.

    Все ошибки слоя сервисов/UI наследуют его, чтобы граница в UI могла перехватить
    одно семейство и показать запись в MessageLog (FR-SIM-005, NFR-ROB-001).
    """

    def __init__(self, message: str = "", diagnostic: Diagnostic | None = None) -> None:
        self.message = message or self.__class__.__name__
        self.diagnostic = diagnostic
        super().__init__(self.message)


class NetlistError(RcadError):
    """Ошибка разбора/генерации netlist (FR-NLV-005): место ошибки — file:line.

    Проект при этом не изменяется — контракт импорта (FR-MER-.../FR-NLV-004).
    """

    def __init__(
        self,
        message: str = "",
        *,
        line: int | None = None,
        column: int | None = None,
        file: str = "",
    ) -> None:
        self.line = line
        self.column = column
        self.file = file
        diagnostic = Diagnostic(
            code=DiagnosticCode.E_NETLIST,
            message=message or "netlist error",
            file=file,
            line=line,
            column=column,
        )
        super().__init__(message, diagnostic)

    @property
    def location(self) -> str:
        out = self.file or "netlist"
        if self.line is not None:
            out += f":{self.line}"
            if self.column is not None:
                out += f":{self.column}"
        return out


class ParameterRangeError(RcadError):
    """Значение параметра вне объявленного диапазона ParamSpec (FR-PRP-003)."""

    def __init__(
        self,
        message: str = "",
        *,
        param: str = "",
        value: object = None,
        bounds: tuple[float, float] | None = None,
        instance: str = "",
    ) -> None:
        self.param = param
        self.value = value
        self.bounds = bounds
        diagnostic = Diagnostic(
            code=DiagnosticCode.E_PARAM_RANGE,
            message=message or f"parameter {param} out of range",
            hint_ru=(
                f"Параметр {param} вне допустимого диапазона {bounds}"
                if bounds
                else f"Параметр {param} вне допустимого диапазона"
            ),
            object_name=instance,
        )
        super().__init__(message or str(message), diagnostic)


class ParameterTypeError(RcadError):
    """Значение параметра не соответствует типу (FR-PRP-002)."""

    def __init__(self, message: str = "", *, param: str = "", value: object = None) -> None:
        self.param = param
        self.value = value
        super().__init__(
            message or f"parameter {param}: invalid value {value!r}",
            Diagnostic(
                code=DiagnosticCode.E_PARAM_TYPE,
                message=message or f"parameter {param}: invalid value",
                hint_ru=f"Параметр {param}: недопустимое значение {value!r}",
            ),
        )


class ProjectError(RcadError):
    """Ошибка проекта (статус/повреждение/версия): FR-PRJ-004/009/011/012."""


class AnalysisError(RcadError):
    """Ошибка анализа (ядро); сохранена для единого импорта из сервисов.

    Реальная реализация появится вместе с `rcad.core.analyses`; сервисы
    перехватывают RcadError-семейство, поэтому дубликат не нужен.
    """


class ConvergenceError(AnalysisError):
    """Не сходится Ньютон в точке анализа (FR-SIM-005)."""
