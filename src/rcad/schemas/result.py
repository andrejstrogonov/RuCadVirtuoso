"""Метаданные результата анализа (ARCH §5.5, AD-08).

Сам `Result` (массивы NumPy, ряды) живёт в `rcad.core.analyses`; сервисный слой
описывает его метаданными `ResultMeta` и хранит пары «метаданные + ряд» через
ResultStore. Ряды изменяемы в памяти только владельцем (ядром); здесь метаданные
неизменяемы.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from rcad.schemas.analysis import AnalysisKind


class ResultMeta(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    analysis_type: AnalysisKind
    rows: int
    units: dict[str, str | None] = Field(default_factory=dict)
    version: str = "1.0"
    provenance: str = ""
