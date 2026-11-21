"""SimulatorService (Qt): расчёт в QThread c сигналами progress/finished/failed.

Отмена на уровне ядра отсутствует (см. план, Риски) — в фазе реализован discard
результата воркера без остановки ядра; UI остаётся отзывчивым (FR-SIM-004).
Ошибки — через сигнал `failed`, UI не падает (FR-SIM-005, NFR-ROB-001).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from rcad.diagnostics import RcadError


class _Worker(QThread):
    progress = Signal(int)
    finished_ok = Signal(object)  # Result (dict-like от ядра)
    failed = Signal(str)

    def __init__(self, runner, parent=None) -> None:
        super().__init__(parent)
        self._runner = runner

    def run(self) -> None:
        try:
            self.progress.emit(10)
            result = self._runner()
            self.progress.emit(100)
            self.finished_ok.emit(result)
        except RcadError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # граница: непредвиденное исключение не роняет UI
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class SimulatorService(QObject):
    """Запуск анализа в отдельном потоке; сигналы — единственный канал связи."""

    progress = Signal(int)
    finished = Signal(object)  # Result
    failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker: _Worker | None = None

    @property
    def busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def cancel(self) -> None:
        """Отмена: отключить обработку результата (ядро не останавливается)."""
        if self._worker is not None:
            try:
                self._worker.finished_ok.disconnect(self.finished)
            except (RuntimeError, TypeError):
                pass
            self._worker.terminate()
            self._worker.wait(500)

    def run(self, runner) -> None:
        if self.busy:
            raise RcadError("анализ уже выполняется в фоне")
        self._worker = _Worker(runner, self)
        self._worker.progress.connect(self.progress)
        self._worker.finished_ok.connect(self.finished)
        self._worker.failed.connect(self.failed)
        self._worker.start()
