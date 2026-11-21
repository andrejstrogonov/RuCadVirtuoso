"""Ядро моделирования RuCadVirtuoso (ARCh §5, Этап E0).

Предоставляет run_analysis(), precheck(), Result иdevice-модели для
анализов OP / DC / TRAN / AC. Слой ядра полностью headless — без PySide6.
"""

from rcad.core.analyses import AnalysisError, Result, precheck, run_analysis
from rcad.diagnostics import NetlistError

__all__ = ["run_analysis", "precheck", "Result", "AnalysisError", "NetlistError"]
