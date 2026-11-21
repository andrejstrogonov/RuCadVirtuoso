"""Спека анализа (OP/DC/TRAN/AC) и её сериализация в директиву netlist.

Дискриминатор `type` (ARCH §5.5). `directive` — канонический текст директивы
(например `.tran 1m 2 0 1m`), который вставляется в netlist нетлистером.
`infer` собирает спецификацию из строки директивы вида `.tran ...` и обратно
выдаёт `.tran ...` без корневых точек, чтобы анализ мог маршрутизоваться.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

AnalysisKind = Literal["op", "dc", "tran", "ac"]


class OpSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["op"] = "op"

    def to_directive(self) -> str:
        return ".op"


class DcSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["dc"] = "dc"
    src: Annotated[str, Field(min_length=1)]
    start: float
    stop: float
    step: float

    def to_directive(self) -> str:
        return f".dc {self.src} {self.start:g} {self.stop:g} {self.step:g}"


class TranSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["tran"] = "tran"
    tstep: float
    tstop: float
    tstart: float = 0.0
    tmax: float | None = None

    def to_directive(self) -> str:
        if self.tmax is not None:
            return f".tran {self.tstep:g} {self.tstop:g} {self.tstart:g} {self.tmax:g}"
        if self.tstart:
            return f".tran {self.tstep:g} {self.tstop:g} {self.tstart:g}"
        return f".tran {self.tstep:g} {self.tstop:g}"


class AcSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["ac"] = "ac"
    sweep: Literal["dec", "lin", "oct"] = "dec"
    points: int
    fstart: float
    fstop: float

    def to_directive(self) -> str:
        return f".ac {self.sweep} {self.points} {self.fstart:g} {self.fstop:g}"


AnalysisSpec = Annotated[OpSpec | DcSpec | TranSpec | AcSpec, Field(discriminator="type")]

_SUFFIX = {
    "T": 1e12, "G": 1e9, "MEG": 1e6, "K": 1e3, "M": 1e-3,
    "U": 1e-6, "N": 1e-9, "P": 1e-12, "F": 1e-15,
}


def _suffix_float(text: str) -> float:
    """Число с SPICE-суффиксом (1m/2u/0.1k/1meg) в float."""
    import re

    match = re.fullmatch(r"([+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?)([a-zA-Z]*)", text.strip())
    if not match:
        raise ValueError(f"нечисловое значение {text!r}")
    value = float(match.group(1))
    suffix = match.group(4)
    if suffix and suffix.upper() in _SUFFIX:
        return value * _SUFFIX[suffix.upper()]
    if suffix:
        raise ValueError(f"неизвестный суффикс {suffix!r} в {text!r}")
    return value


def spec_from_directive(directive: str) -> OpSpec | DcSpec | TranSpec | AcSpec:
    """Разобрать строку директивы (с/без ведущей точки) в спецификацию.

    Используется CLI-командой `run` и SimulatorService для маршрутизации.
    Для .tran/.dc/.ac значения суффиксов 1k/1u/1m интерпретируются ядром
    при парсинге netlist — здесь сохраняется сырая строка операндов.
    """
    text = directive.strip().lstrip(".")
    kind, _, rest = text.partition(" ")
    kind = kind.lower()
    if kind == "op":
        return OpSpec()
    parts = rest.split()
    if kind == "tran":
        numbers = [_suffix_float(p) for p in parts]
        spec: dict = {"type": "tran"}
        if len(numbers) >= 2:
            spec["tstep"], spec["tstop"] = numbers[0], numbers[1]
        if len(numbers) >= 3:
            spec["tstart"] = numbers[2]
        if len(numbers) >= 4:
            spec["tmax"] = numbers[3]
        return TranSpec(**spec)
    if kind == "dc":
        return DcSpec(src=parts[0], start=_suffix_float(parts[1]), stop=_suffix_float(parts[2]), step=_suffix_float(parts[3]))
    if kind == "ac":
        return AcSpec(
            sweep=parts[0],  # type: ignore[arg-type]  # строка валидируется Literal
            points=int(parts[1]),
            fstart=_suffix_float(parts[2]),
            fstop=_suffix_float(parts[3]),
        )
    raise ValueError(f"неизвестный тип анализа: {kind!r}")
