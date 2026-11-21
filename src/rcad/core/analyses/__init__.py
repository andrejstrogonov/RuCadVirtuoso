"""Анализы OP / DC / TRAN / AC (rcad.core.analyses).

Точка входа для ядра моделирования.
"""

from rcad.core.analyses.run import AnalysisError, Result, precheck, run_analysis

__all__ = ["run_analysis", "precheck", "Result", "AnalysisError"]
