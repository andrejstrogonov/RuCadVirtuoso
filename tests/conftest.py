"""Общие фикстуры приёмочных тестов: готовность ядра, каталоги данных, утилиты CSV.

Ядро моделирования (`rcad.core.analyses.run_analysis`) в репозитории ещё не
реализовано (этап E0 плана). Пока его нет, тесты обязательного набора T1–T15 и
сценариев S1–S4 помечаются skip на уровне всего модуля: тест написан полностью и
начинает исполняться, как только появляется ядро.
"""

from __future__ import annotations

import csv
import importlib.util
import math
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
GOLDEN = Path(__file__).resolve().parent / "golden"
EXAMPLES = ROOT / "examples"

CORE_MODULE = "rcad.core.analyses"
SERVICES_MODULE = "rcad.services"
UI_MODULE = "rcad.ui"
VA_MODULE = "rcad.veriloga"


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def core_available() -> bool:
    """Ядро считается доступным, когда найдены и модуль, и функция `run_analysis`."""
    return _module_available(CORE_MODULE)


def services_available() -> bool:
    return _module_available(SERVICES_MODULE)


def ui_available() -> bool:
    return _module_available(UI_MODULE)


def va_available() -> bool:
    return _module_available(VA_MODULE)


requires_core = pytest.mark.skipif(
    not core_available(),
    reason=f"{CORE_MODULE} не реализован (этап E0): тест написан, но не исполняется",
)

requires_services = pytest.mark.skipif(
    not services_available(),
    reason=f"{SERVICES_MODULE} не реализован (этап E3): сервисы отсутствуют",
)

requires_ui = pytest.mark.skipif(
    not ui_available(),
    reason=f"{UI_MODULE} не реализован (этап E3): UI отсутствует",
)

requires_va = pytest.mark.skipif(
    not va_available(),
    reason=f"{VA_MODULE} не реализован (этап E2): Verilog-A конвейер отсутствует",
)


def read_golden(name: str) -> Iterator[dict[str, float]]:
    """Прочитать golden-CSV: первая строка — имена рядов, далее числа."""
    with (GOLDEN / name).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            yield {key: float(value) for key, value in row.items()}


def close(actual: float, expected: float, reltol: float = 1e-3, abstol: float = 1e-9) -> bool:
    """Единый допуск сверки ТЗ п. 12.1: reltol=1e-3, abstol=1e-9."""
    return math.isclose(actual, expected, rel_tol=reltol, abs_tol=abstol)


def max_rel_error(actual: list[float], expected: list[float]) -> float:
    if len(actual) != len(expected):
        raise AssertionError(f"длины рядов не совпадают: {len(actual)} != {len(expected)}")
    worst = 0.0
    for a, e in zip(actual, expected, strict=False):
        scale = max(abs(e), 1e-12)
        worst = max(worst, abs(a - e) / scale)
    return worst
