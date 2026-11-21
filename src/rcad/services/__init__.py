"""Сервисный слой (headless, без PySide6): проект, библиотека, netlist, результаты.

Зависимости направлены вниз: services → schemas, diagnostics, core. UI (виджеты)
строится поверх этих сервисов; `rcad.ui.api` — Qt-free-фасад (ARCh §3, AD-01).
"""

from rcad.services.model_manager import ModelManager
from rcad.services.project_service import ProjectDoc, ProjectService

__all__ = ["ModelManager", "ProjectDoc", "ProjectService"]
