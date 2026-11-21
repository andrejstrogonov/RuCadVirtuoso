"""Qt-free UI-фасад `CanvasApi` (NFR-TST-001, FR-SCN-S1…S4).

Единая точка программного доступа к холсту и проекту для headless-сценариев
(уровень «UI smoke» ТЗ п. 12.1) и для виджетов. Модуль **не импортирует
PySide6/pyqtgraph** — проверяется тестом слоёв (§F6); виджеты опираются на этот
контракт, а не наоборот.
"""

from __future__ import annotations

from typing import Any, Literal

from rcad.schemas.cell import CellSchema, InstanceSchema
from rcad.services.netlister import netlist_for
from rcad.services.project_service import ProjectDoc


class CanvasApi:
    """Фасад над проектом: состояние холста, размещение, параметры, netlist."""

    def __init__(self, project: ProjectDoc, *, active_cell: str | None = None) -> None:
        self.project = project
        self._active_cell = active_cell or project.name

    # --- состояние холста ----------------------------------------------------

    def canvas_state(self, cell: str) -> dict[str, Any]:
        """Состояние схемы в SCHEMATIC-форме (NFR-TST-003, FR-CEL-001…007)."""
        return self._require_cell(cell).model_dump(exclude_none=True)

    def _require_cell(self, cell: str) -> CellSchema:
        try:
            return self.project.cell(cell)
        except KeyError as exc:
            raise ValueError(f"ячейка {cell!r} отсутствует в проекте") from exc

    # --- размещение (S2: place без cell — активная ячейка проекта) -----------

    def place(
        self,
        instance_name: str,
        master: str,
        *,
        x: float,
        y: float,
        cell: str | None = None,
        rotation: Literal[0, 90, 180, 270] = 0,
        mirror: Literal["none", "x", "y"] = "none",
    ) -> None:
        """Разместить инстанс в ячейке `cell` (или в активной ячейке проекта).

        Уникальность имени — FR-PRP-005; координаты кратны сетке — FR-GRD-001
        (приведение к 10 px здесь и в LayerManager виджетов).
        """
        target = self._cell_for_place(cell)
        existing = {inst.name for inst in target.instances}
        if instance_name in existing:
            raise ValueError(f"имя инстанса {instance_name!r} уже занято в ячейке {target.name}")
        instance = InstanceSchema(
            name=instance_name,
            master_cell=master,
            x=(int(x) // 10) * 10,
            y=(int(y) // 10) * 10,
            rotation=rotation,
            mirror=mirror,
            params=self._default_params(master),
        )
        cells = dict(self.project.cells)
        new_cell = target.model_copy(
            update={"instances": [*target.instances, instance]}
        )
        cells[target.name] = new_cell
        self.project.cells = cells

    def _cell_for_place(self, cell: str | None) -> CellSchema:
        name = cell or self._active_cell
        if name not in self.project.cells:
            # автокопия мастера ячейки проекта (FR-PLC-004): пустая ячейка
            self.project.cells[name] = CellSchema(name=name)
        return self.project.cell(name)

    def _default_params(self, master: str) -> dict[str, float | int | str]:
        entry = self.project.model_manager.entry(master)
        return dict(entry.params) if entry is not None else {}

    # --- параметры (FR-PRP-001…005) ------------------------------------------

    def set_params(
        self,
        cell: str,
        instance: str,
        params: dict[str, Any],
    ) -> None:
        """Установить параметры инстанса с валидацией типа и диапазона.

        Некорректный диапазон → `ParameterRangeError` (FR-PRP-003); проект при
        этом не изменяется. Значения-строки (PULSE и т.п.) не нормализуются.
        """
        target = self._require_cell(cell)
        target_inst = next((i for i in target.instances if i.name == instance), None)
        if target_inst is None:
            raise KeyError(f"инстанс {instance!r} не найден в ячейке {cell}")
        specs = {
            spec.name: spec
            for spec in self.project.model_manager.params_for(target_inst.master_cell)
        }
        merged = dict(target_inst.params)
        for name, value in params.items():
            spec = specs.get(name)
            if spec is not None and isinstance(value, (int, float)):
                spec.validate_value(value)
            merged[name] = value
        updated = target_inst.model_copy(update={"params": merged})
        new_cell = target.model_copy(
            update={"instances": [
                updated if inst is target_inst else inst for inst in target.instances
            ]}
        )
        self.project.cells[cell] = new_cell

    def instance_params(
        self,
        cell: str,
        instance: str,
    ) -> dict[str, float | int | str]:
        """Реально записанные параметры инстанса (S3: PULSE как строка)."""
        target = self._require_cell(cell)
        target_inst = next((i for i in target.instances if i.name == instance), None)
        if target_inst is None:
            raise KeyError(f"инстанс {instance!r} не найден в ячейке {cell}")
        return dict(target_inst.params)

    # --- netlist ---------------------------------------------------------------

    def build_netlist(
        self,
        cell: str,
        *,
        dc: str | None = None,
        tran: str | None = None,
        ac: str | None = None,
    ) -> str:
        """Netlist ячейки с директивой анализа (через services.netlister)."""
        return netlist_for(self.project, cell, dc=dc, tran=tran, ac=ac)
