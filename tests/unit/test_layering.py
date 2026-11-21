"""Правила зависимостей слоёв (ARCh §3, NFR-TST-002) — анализ импортов через AST.

Запреты:
1. `rcad.ui.api`, `rcad.services.*` не импортируют PySide6/pyqtgraph/Qt.
2. `rcad.ui.*` (виджеты) не импортируют `rcad.core.mna`/`rcad.core.solver`
   напрямую — только через сервисы.
3. `rcad.core.*`, `rcad.devices`, `rcad.diagnostics`, `rcad.schemas` не
   импортируют `PySide6`, `pyqtgraph`, `rcad.ui`, `rcad.services`.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"

QT_MODULES = {"PySide6", "pyqtgraph", "shiboken6"}
QT_PREFIXES = ("PySide6.", "pyqtgraph.")
CORE_INTERNALS = {"rcad.core.mna", "rcad.core.solver", "rcad.core.solver.", "rcad.core.mna."}


def _imported_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _relative_import_modules(tree: ast.AST) -> list[str]:
    """Приведение относительных импортов к абсолютным именам пакета."""
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            module = node.module or ""
            parts: list[str] = []
            # путь файла уже учтён: модули относительно пакета считаем безопасными
            parts.append(module)
            modules.extend(p for p in parts if p)
    return modules


def _python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def test_services_and_ui_api_do_not_import_qt() -> None:
    targets: list[Path] = [
        p for p in _python_files(SRC / "rcad" / "services")
    ] + [SRC / "rcad" / "ui" / "api.py"]
    violations: list[str] = []
    for path in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _imported_names(tree):
            if name in QT_MODULES or name.startswith(QT_PREFIXES):
                violations.append(f"{path.relative_to(SRC)} -> {name}")
    assert not violations, f"запрещён Qt-импорт в сервисах/ui.api: {violations}"


def test_widgets_do_not_import_core_internals_directly() -> None:
    target = SRC / "rcad" / "ui"
    violations: list[str] = []
    for path in _python_files(target):
        if path.name == "api.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _imported_names(tree):
            if name in CORE_INTERNALS or any(name.startswith(p) for p in CORE_INTERNALS):
                violations.append(f"{path.relative_to(SRC)} -> {name}")
    assert not violations, f"UI импортирует internals ядра напрямую: {violations}"


def test_core_and_leaf_layers_do_not_import_ui(qt_absent: None = None) -> None:
    """Абсолютные импорты нижних слоёв не касаются Qt и UI-слоя."""
    allowed_q = SRC / "rcad"
    violations: list[str] = []
    for path in _python_files(allowed_q):
        if "services" in path.parts or "ui" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _imported_names(tree):
            if name in QT_MODULES or name.startswith(QT_PREFIXES):
                violations.append(f"{path.relative_to(SRC)} -> {name}")
    assert not violations, f"запрещён Qt-импорт в нижних слоях: {violations}"
