"""Схема проекта (`project.json`, ТЗ п. 6.1, FR-PRJ-001…005).

Каталог `<project>.rcad/` — единственная точка сохранения; `ProjectSchema` — его
`project.json`. `format_version` участвует в миграциях (FR-PRJ-004/005).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

FORMAT_VERSION = 1

_LIBRARY_NAME = r"^[A-Za-z_][A-Za-z0-9_]*$"


class ProjectSchema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9_\-\. ]+$")]
    format_version: int = FORMAT_VERSION
    libraries: list[Annotated[str, Field(pattern=_LIBRARY_NAME)]] = Field(default_factory=list)
