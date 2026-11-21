"""Хранилище результатов анализа и экспорт CSV (ARCH §5.5, AD-08, FR-PLT-005).

`Result` живёт в ядре (`rcad.core.analyses`); сервис не зависит от его типа —
используются только протоколы `names()` и `__getitem__`. `export_csv` пишет
`time,<имена>` + N строк (S1: 2002 строки с заголовком).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from rcad.schemas.analysis import AnalysisKind
from rcad.schemas.result import ResultMeta


@runtime_checkable
class ResultLike(Protocol):
    def names(self) -> list[str]: ...

    def names_minus_time(self) -> list[str]: ...

    def __getitem__(self, name: str): ...


@dataclass
class StoredResult:
    meta: ResultMeta
    series: dict[str, object] = field(default_factory=dict)


class ResultStore:
    """В памяти (сессия); персистентность — экспорт CSV по запросу."""

    def __init__(self) -> None:
        self._results: dict[str, StoredResult] = {}
        self._seq = 0

    def put(self, result: ResultLike, provenance: str = "") -> str:
        meta = ResultMeta(
            analysis_type=_detect_type(result),
            rows=len(result["time"]) if "time" in result.names() else 0,
            provenance=provenance,
        )
        series = {name: result[name] for name in result.names()}
        self._seq += 1
        key = f"r{self._seq}"
        self._results[key] = StoredResult(meta=meta, series=series)
        return key

    def get(self, key: str) -> StoredResult | None:
        return self._results.get(key)

    def keys(self) -> list[str]:
        return list(self._results)


def _detect_type(result: ResultLike) -> AnalysisKind:
    if "time" in result.names():
        return "tran"
    if "freq" in result.names():
        return "ac"
    return "dc"


def export_csv(
    result: ResultLike,
    names: list[str],
    path: Path | str,
) -> Path:
    """Экспорт выбранных рядов: заголовок `time,<names>` + N+1 строк.

    Для sweeps без `time` (DC/AC) осью становится первый доступный ряд
    (например `V(in)`); контракт для TRAN сохраняется: `time,I(Xmem),@Xmem.x`.
    Возвращает путь к записанному файлу (S1).
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    available = result.names()
    if "time" in available:
        axis = "time"
    elif "freq" in available:
        axis = "freq"
    else:
        axis = available[0] if available else ""
    assert axis, "результат не содержит рядов для экспорта"
    header = [axis, *[n for n in names if n != axis]]
    axis_series = result[axis]
    n = len(axis_series)
    with target.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        for row in range(n):
            writer.writerow([axis_series[row], *[result[name][row] for name in names if name != axis]])
    return target
