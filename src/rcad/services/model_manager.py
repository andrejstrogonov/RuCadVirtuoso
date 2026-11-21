"""Библиотека моделей и символов (FR-LIB-001/002, FR-DEV-001).

Загружает `data/Libraries/*.json` и `data/Symbols/*.json` один раз и отдаёт:
- записи ячеек (`ModelEntry`) для нетлистера (карты R/C/V/I/X/M, include, subckt);
- спецификации параметров (`ParamSpec`) для панели свойств и CanvasApi;
- символы (`SymbolSchema`) для панели библиотеки и сцены.

Nикаких PySide6-импортов; слой сервисов headless (ARCh §3, AD-01).
"""

from __future__ import annotations

import json
from pathlib import Path

from rcad.schemas.model import LibrarySchema, ModelEntry, ParamSpec
from rcad.schemas.symbol import SymbolSchema

SYMBOLS_DIR = "Symbols"
LIBRARIES_DIR = "Libraries"


def _data_root() -> Path:
    """Каталог `data/` в корне репозитория (cwd при прогоне тестов — корень)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data"
        if (candidate / LIBRARIES_DIR).is_dir():
            return candidate
    return Path.cwd() / "data"


class ModelManager:
    """Единый реестр ячеек библиотеки и их параметров.

    Контейнер со свежим состоянием: `reload()` перечитывает JSON (FR-LIB-002 —
    после импорта VA-модели библиотека обновляется без перезапуска).
    """

    def __init__(
        self,
        libraries_dir: Path | None = None,
        symbols_dir: Path | None = None,
    ) -> None:
        root = _data_root()
        self._libraries_dir = libraries_dir or root / LIBRARIES_DIR
        self._symbols_dir = symbols_dir or root / SYMBOLS_DIR
        self._libraries: dict[str, LibrarySchema] = {}
        self._entries: dict[str, ModelEntry] = {}
        self._symbols: dict[str, SymbolSchema] = {}
        self.reload()

    # --- загрузка -----------------------------------------------------------

    def reload(self) -> None:
        self._libraries = {}
        self._entries = {}
        for path in sorted(self._libraries_dir.glob("*.json")):
            try:
                library = LibrarySchema.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, json.JSONDecodeError) as exc:  # повреждённый файл библиотеки
                raise ValueError(f"повреждённый файл библиотеки {path}: {exc}") from exc
            self._libraries[library.name] = library
            for entry in library.cells:
                self._entries[entry.cell] = entry
        self._symbols = {}
        for path in sorted(self._symbols_dir.glob("*.json")):
            symbol = SymbolSchema.model_validate(json.loads(path.read_text(encoding="utf-8")))
            self._symbols[symbol.cell] = symbol
            model_entry = self._entries.get(symbol.cell)
            if model_entry is not None and not model_entry.pins:
                model_entry = model_entry.model_copy(
                    update={"pins": [pin.name for pin in symbol.pins]}
                )
                self._entries[symbol.cell] = model_entry

    # --- запросы ------------------------------------------------------------

    @property
    def library_names(self) -> list[str]:
        return sorted(self._libraries)

    def library(self, name: str) -> LibrarySchema | None:
        return self._libraries.get(name)

    def entry(self, cell: str) -> ModelEntry | None:
        return self._entries.get(cell)

    def entry_by_subckt(self, subckt: str) -> ModelEntry | None:
        """Найти запись библиотеки по имени `subckt` (импорт X-карты, S4)."""
        for entry in self._entries.values():
            if entry.subckt == subckt:
                return entry
        return None

    def symbol(self, cell: str) -> SymbolSchema | None:
        return self._symbols.get(cell)

    def symbol_for(self, name: str) -> SymbolSchema | None:
        """Псевдоним для контракта `registry.symbol_for(name)` (X-карты, S2)."""
        symbol = self._symbols.get(name)
        if symbol is not None:
            return symbol
        # VA-модели имеют символ, созданный при импорте; для библиотечных ячеек —
        # символ из data/Symbols по имени мастера.
        return None

    def cell_names(self) -> list[str]:
        return sorted(self._entries)

    def panel_cells(self) -> list[ModelEntry]:
        """Ячейки панели библиотеки: примитивы и приборы (FR-LIB-001)."""
        return sorted(self._entries.values(), key=lambda entry: entry.cell)

    def params_for(self, master_cell: str) -> list[ParamSpec]:
        """Спецификации параметров мастера для панели свойств (FR-PRP-001).

        Параметры по умолчанию берутся из `data/Libraries/*.json`; границы — из
        метаданных модели, если модель зарегистрирована в `rcad.devices.registry`.
        """
        entry = self._entries.get(master_cell)
        if entry is None:
            return []
        pairs: list[tuple[str, float | int | str]] = list(entry.params.items())
        if not pairs:
            return []
        return [ParamSpec(name=name, kind="real", default=value) for name, value in pairs]

    def model_pins(self, master_cell: str) -> list[str]:
        entry = self._entries.get(master_cell)
        if entry is not None and entry.pins:
            return list(entry.pins)
        symbol = self._symbols.get(master_cell)
        if symbol is not None:
            return [pin.name for pin in symbol.pins]
        return []

    # --- дополнительные записи (импорт netlist, S4) ---------------------------

    _extra_includes: dict[str, set[str]] = {}

    def register_include(self, include: str) -> None:
        """Регистрация `.include` внешнего файла (без проверки существования)."""
        self._extra_includes.setdefault(include, set()).add(include)

    def includes_for(self, cell: str) -> list[str]:
        """Все зарегистрированные include-файлы (глобально, для экспорта)."""
        return sorted(i for incs in self._extra_includes.values() for i in incs)
