"""Окно графиков (FR-PLT-001…006): мультипанели, курсор, лог-оси, экспорт PNG/CSV.

pyqtgraph поверх результата ядра (numpy-ряды). Несколько независимых окон —
FR-PLT-006: каждое окно хранит собственный Result.
"""

from __future__ import annotations

from pathlib import Path

import pyqtgraph as pg
from PySide6.QtWidgets import QMainWindow

pg.setConfigOptions(antialias=True)


class PlotWindow(QMainWindow):
    """Панель на величину; виджет графиков — `window`.

    Данные — любые объекты с `names()`/`__getitem__` (Result ядра).
    """

    def __init__(self, result=None, series: list[str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.result = result
        self.setWindowTitle("Результаты анализа")
        self._pens = ["#c01c28", "#26a269", "#1c71d8", "#e5a50a", "#813d9c", "#2ec27e"]
        self._widget = pg.GraphicsLayoutWidget()
        self.setCentralWidget(self._widget)
        if result is not None:
            names = series or [n for n in result.names() if n != "time"]
            self.plot_names(names)

    def plot_names(self, names: list[str]) -> None:
        if self.result is None:
            return
        self._widget.clear()
        max(1, len(names))  # FR-PLT-002: панель на величину
        plots = []
        for i, name in enumerate(names):
            plot = self._widget.addPlot(row=i, col=0)
            x = self.result["time"] if "time" in self.result.names() else list(range(len(self.result[name])))
            y = [float(v) for v in self.result[name]]
            plot.plot(x, y, pen=pg.mkPen(self._pens[i % len(self._pens)], width=1),
                      name=name)
            plot.setLabel("left", name)
            plot.showGrid(x=True, y=True, alpha=0.3)
            plots.append(plot)
        self._plots = plots

    # --- курсор (FR-PLT-003) --------------------------------------------------

    def set_cursor(self, plot_index: int = 0) -> None:
        plot = self._plots[plot_index]
        plot.setCursor(plot.viewport().cursor())
        self._cursor_plot = plot

    # --- лог-оси (FR-PLT-004) --------------------------------------------------

    def set_log_y(self, enabled: bool, plot_index: int = 0) -> None:
        plot = self._plots[plot_index]
        plot.setLogMode(x=plot.getAxis("bottom").logMode, y=enabled)

    def toggle_log_x(self, enabled: bool, plot_index: int = 0) -> None:
        plot = self._plots[plot_index]
        plot.setLogMode(x=enabled, y=plot.getAxis("left").logMode)

    # --- экспорт (FR-PLT-005) --------------------------------------------------

    def export_png(self, path: Path | str) -> Path:
        target = Path(path)
        self._widget.grab().save(str(target))
        return target

    def export_csv(self, names: list[str], path: Path | str) -> Path:
        from rcad.services.result_store import export_csv

        return export_csv(self.result, names, path)
