"""Хранение проекта `<project>.rcad/` (ТЗ п. 6.1, FR-PRJ-001…012, FR-PRS-001…004).

Сервис — единственный владелец каталога проекта:
- `create` — новый каталог с `project.json` (format_version=1) и библиотеками;
- `add_cell` — валидация CellSchema и запись `cells/<cell>.json`;
- `save` — атомарная запись (`.tmp` → `os.replace`), каноничный JSON
  (NFR-TST-002: повторный save неизменённого проекта даёт идентичные файлы);
- `open` — валидация project.json + миграции по format_version (FR-PRJ-004/005),
  частично читаемый проект открывается с диагностиками (FR-PRJ-009/012);
- `autosave`/восстановление через `recovery.json` (FR-PRS-001…004).

Проект в памяти — `ProjectDoc`; все методы принимают его явно, никакого
скрытого глобального состояния (headless).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rcad.diagnostics import Diagnostic, DiagnosticCode, ProjectError, Severity
from rcad.schemas.cell import CellSchema
from rcad.schemas.project import FORMAT_VERSION, ProjectSchema
from rcad.services.model_manager import ModelManager

PROJECT_JSON = "project.json"
CELLS_DIR = "cells"
RECOVERY_JSON = "recovery.json"


@dataclass
class ProjectDoc:
    """Проект в памяти: схема + загруженные ячейки + сервисная библиотека."""

    schema: ProjectSchema
    root: Path
    cells: dict[str, CellSchema] = field(default_factory=dict)
    model_manager: ModelManager = field(default_factory=ModelManager)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.schema.name

    @property
    def format_version(self) -> int:
        return self.schema.format_version

    @property
    def libraries(self) -> list[str]:
        return list(self.schema.libraries)

    @property
    def cell_names(self) -> list[str]:
        return sorted(self.cells)

    def cell(self, name: str) -> CellSchema:
        return self.cells[name]

    def has_cell(self, name: str) -> bool:
        return name in self.cells


def _canonical_json(model: Any) -> str:
    """Канонический JSON: поля pydantic в порядке объявления, без пробелов."""
    return model.model_dump_json(exclude_none=True)


def _atomic_write(path: Path, content: str) -> None:
    """Атомарная запись: `.tmp` в том же каталоге → os.replace (FR-CEL-007)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


class ProjectService:
    def __init__(self, model_manager: ModelManager | None = None) -> None:
        self.model_manager = model_manager or ModelManager()

    # --- создание -----------------------------------------------------------

    def create(self, path: Path | str, name: str | None = None) -> ProjectDoc:
        """Создать каталог `<name>.rcad` с `project.json` и библиотеками по умолчанию.

        Если `path` уже заканчивается на `.rcad` — используется как есть, иначе
        создаётся `<path>/<name>.rcad`.
        """
        root = self._resolve_root(path, name)
        root.mkdir(parents=True, exist_ok=False)
        schema = ProjectSchema(
            name=root.stem if name is None else name,
            format_version=FORMAT_VERSION,
            libraries=list(self.model_manager.library_names),
        )
        _atomic_write(root / PROJECT_JSON, _canonical_json(schema))
        (root / CELLS_DIR).mkdir(exist_ok=True)
        return ProjectDoc(schema=schema, root=root, model_manager=self.model_manager)

    @staticmethod
    def _resolve_root(path: Path | str, name: str | None) -> Path:
        path = Path(path)
        if path.suffix == ".rcad":
            return path
        if name is None:
            raise ValueError("имя проекта обязательно, если путь не заканчивается на .rcad")
        return path / f"{name}.rcad"

    def path(self, project: ProjectDoc) -> Path:
        return project.root

    # --- ячейки -------------------------------------------------------------

    def add_cell(self, project: ProjectDoc, schematic: dict[str, Any]) -> CellSchema:
        """Валидация дикте-схемы и сохранение `cells/<cell>.json` (FR-CEL-001…007)."""
        cell = CellSchema.model_validate(schematic)
        if cell.name in project.cells and project.cells[cell.name] is not cell:
            pass  # перезапись ячейки с тем же именем — допустима (повторный импорт)
        project.cells[cell.name] = cell
        project.cell_names  # noqa: B018 — гарантия упорядоченности cache не нужен
        self._write_cell(project, cell)
        return cell

    def _write_cell(self, project: ProjectDoc, cell: CellSchema) -> None:
        target = project.root / CELLS_DIR / f"{cell.name}.json"
        _atomic_write(target, _canonical_json(cell))

    def remove_cell(self, project: ProjectDoc, name: str) -> None:
        if name in project.cells:
            del project.cells[name]
            target = project.root / CELLS_DIR / f"{name}.json"
            if target.exists():
                target.unlink()

    # --- сохранение ---------------------------------------------------------

    def save(self, project: ProjectDoc) -> None:
        """Атомарная запись всех файлов проекта; recovery.json удаляется (FR-PRS-004)."""
        if project.schema.format_version != FORMAT_VERSION:
            project.schema = project.schema.model_copy(update={"format_version": FORMAT_VERSION})
        _atomic_write(project.root / PROJECT_JSON, _canonical_json(project.schema))
        (project.root / CELLS_DIR).mkdir(exist_ok=True)
        for cell in project.cells.values():
            self._write_cell(project, cell)
        stale = set()
        for path in (project.root / CELLS_DIR).glob("*.json"):
            if path.stem not in project.cells:
                stale.add(path)
        for path in stale:
            path.unlink()
        recovery = project.root / RECOVERY_JSON
        if recovery.exists():
            recovery.unlink()

    def autosave(self, project: ProjectDoc, *, changed_cells: set[str] | None = None) -> None:
        """Автосохранение изменённых ячеек + `recovery.json` (FR-PRS-001/002).

        Сам таймер 5 минут живёт в UI (F8); сервис выполняет запись. Изменённые
        ячейки определяет вызывающий (сравнением с каноническим rescue-образом).
        """
        names = changed_cells if changed_cells is not None else set(project.cells)
        for name in names:
            cell = project.cells.get(name)
            if cell is not None:
                self._write_cell(project, cell)
        recovery = {
            "project": project.schema.name,
            "format_version": project.schema.format_version,
            "cells": list(names),
            "timestamp": None,  # время не пишем — детерминированность файлов (NFR-TST-002)
        }
        _atomic_write(project.root / RECOVERY_JSON, json.dumps(recovery, ensure_ascii=False))

    def recovery_state(self, project: ProjectDoc) -> list[Diagnostic]:
        """Диагностики восстановления из `recovery.json`, если есть."""
        recovery = project.root / RECOVERY_JSON
        if not recovery.exists():
            return []
        try:
            data = json.loads(recovery.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return []
        dirty = data.get("cells", [])
        return [
            Diagnostic(
                code=DiagnosticCode.W_STATE_CLIP,
                severity=Severity.WARNING,
                message=f"recovery data found for cells: {', '.join(dirty)}",
                hint_ru="Найдены несохранённые изменения прошлого сеанса (FR-PRS-003).",
                file=RECOVERY_JSON,
            )
        ]

    # --- открытие -----------------------------------------------------------

    def open(self, path: Path | str, *, confirm_upgrade: bool = True) -> ProjectDoc:
        """Открыть каталог проекта с валидацией и миграцией format_version.

        Битый `project.json` → ProjectError с диагностикой (FR-PRJ-009); неверная
        версия формата → отказ без записи (FR-PRJ-004) или warning для старой
        (FR-PRJ-005). Повреждённый файл ячейки не теряет проект целиком
        (FR-PRJ-012): ячейка помечается ошибочной, остальные открываются.
        """
        root = Path(path)
        if not root.is_dir():
            raise ProjectError(f"каталог проекта не существует: {root}")
        schema, diags = self._load_project_schema(root)
        cells: dict[str, CellSchema] = {}
        cells_dir = root / CELLS_DIR
        if cells_dir.is_dir():
            for cell_path in sorted(cells_dir.glob("*.json")):
                try:
                    cells[cell_path.stem] = CellSchema.model_validate(
                        json.loads(cell_path.read_text(encoding="utf-8"))
                    )
                except (ValueError, json.JSONDecodeError) as exc:
                    diags.append(
                        Diagnostic(
                            code=DiagnosticCode.E_PROJECT_CORRUPT,
                            message=f"invalid JSON in {cell_path.name}: {exc}",
                            hint_ru=f"Не удалось прочитать ячейку {cell_path.stem} "
                            f"(FR-PRJ-012). Остальные ячейки открыты.",
                            file=str(cell_path.relative_to(root)),
                        )
                    )
        doc = ProjectDoc(
            schema=schema,
            root=root,
            cells=cells,
            model_manager=self.model_manager,
            diagnostics=diags,
        )
        doc.diagnostics.extend(self.recovery_state(doc))
        return doc

    def _load_project_schema(self, root: Path) -> tuple[ProjectSchema, list[Diagnostic]]:
        project_path = root / PROJECT_JSON
        diags: list[Diagnostic] = []
        if not project_path.exists():
            raise ProjectError(
                f"нет {PROJECT_JSON} в {root}",
                Diagnostic(
                    code=DiagnosticCode.E_PROJECT_CORRUPT,
                    message=f"project.json missing in {root}",
                    hint_ru=f"В каталоге {root} отсутствует {PROJECT_JSON}.",
                    file=str(root),
                ),
            )
        try:
            raw = json.loads(project_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProjectError(
                f"повреждён {PROJECT_JSON}: {exc}",
                Diagnostic(
                    code=DiagnosticCode.E_PROJECT_CORRUPT,
                    message=f"invalid JSON in project.json: {exc}",
                    hint_ru=f"Файл {PROJECT_JSON} не является корректным JSON (FR-PRJ-009).",
                    file=PROJECT_JSON,
                ),
            ) from exc
        version = raw.get("format_version", 1)
        if not isinstance(version, int) or version > FORMAT_VERSION:
            raise ProjectError(
                f"неподдерживаемая версия формата проекта: {version} "
                f"(поддерживается {FORMAT_VERSION})",
                Diagnostic(
                    code=DiagnosticCode.E_PROJECT_VERSION,
                    message=f"unsupported project format version {version}, "
                    f"supported {FORMAT_VERSION}",
                    hint_ru=(
                        f"Версия формата проекта {version} новее поддерживаемой "
                        f"({FORMAT_VERSION}); открытие отклонено без записи (FR-PRJ-004)."
                    ),
                    file=PROJECT_JSON,
                ),
            )
        if version < FORMAT_VERSION:
            diags.append(
                Diagnostic(
                    code=DiagnosticCode.W_PROJECT_VERSION_OLD,
                    severity=Severity.WARNING,
                    message=f"project format version {version} is older than {FORMAT_VERSION}",
                    hint_ru=(
                        f"Версия формата {version} старше текущей ({FORMAT_VERSION}). "
                        f"Запись выполнится в текущей версии после подтверждения (FR-PRJ-005)."
                    ),
                    file=PROJECT_JSON,
                )
            )
        try:
            schema = ProjectSchema.model_validate(raw)
        except ValueError as exc:
            raise ProjectError(
                f"невалидные поля project.json: {exc}",
                Diagnostic(
                    code=DiagnosticCode.E_PROJECT_CORRUPT,
                    message=f"invalid project.json fields: {exc}",
                    hint_ru="Поля project.json не соответствуют схеме (FR-PRJ-009/003).",
                    file=PROJECT_JSON,
                ),
            ) from exc
        return schema, diags
