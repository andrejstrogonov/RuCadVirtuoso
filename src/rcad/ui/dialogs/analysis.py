"""Диалог запуска анализа (FR-SIM-001…003): тип, развёртка, выбор величин.

Собирает `AnalysisSpec` (rcad.schemas.analysis), валидирует до старта, запуск —
через SimulatorService. Ошибки ядра — в MessageLog (FR-SIM-005).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QListWidget,
    QVBoxLayout,
)

from rcad.schemas.analysis import (
    AcSpec,
    AnalysisSpec,
    DcSpec,
    OpSpec,
    TranSpec,
)
from rcad.services.project_service import ProjectDoc


class AnalysisDialog(QDialog):
    """Вкладки OP/DC/TRAN/AC + список величин (узлы/токи/SV)."""

    def __init__(self, project: ProjectDoc, cell: str, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.cell = cell
        self.setWindowTitle(f"Анализ — {cell}")
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._kind = QComboBox()
        self._kind.addItems(["OP", "DC", "TRAN", "AC"])
        form.addRow("Тип анализа", self._kind)

        self._dc_src = QLineEdit("V1")
        form.addRow("DC источник", self._dc_src)
        self._dc_start = QDoubleSpinBox()
        self._dc_start.setRange(-1e12, 1e12)
        form.addRow("DC start", self._dc_start)
        self._dc_stop = QDoubleSpinBox()
        self._dc_stop.setRange(-1e12, 1e12)
        self._dc_stop.setValue(1.0)
        form.addRow("DC stop", self._dc_stop)
        self._dc_step = QDoubleSpinBox()
        self._dc_step.setRange(1e-15, 1e12)
        self._dc_step.setValue(0.01)
        form.addRow("DC step", self._dc_step)

        self._tstep = QDoubleSpinBox()
        self._tstep.setRange(1e-15, 1e9)
        self._tstep.setValue(1e-3)
        self._tstop = QDoubleSpinBox()
        self._tstop.setRange(0.0, 1e12)
        self._tstop.setValue(1e-3)
        self._tstart = QDoubleSpinBox()
        self._tstart.setRange(0.0, 1e12)
        form.addRow("TRAN tstep", self._tstep)
        form.addRow("TRAN tstop", self._tstop)
        form.addRow("TRAN tstart", self._tstart)

        self._ac_sweep = QComboBox()
        self._ac_sweep.addItems(["dec", "lin", "oct"])
        self._ac_points = QDoubleSpinBox()
        self._ac_points.setRange(1, 10000)
        self._ac_points.setValue(10)
        self._ac_fstart = QDoubleSpinBox()
        self._ac_fstart.setRange(1e-6, 1e12)
        self._ac_fstart.setValue(1e3)
        self._ac_fstop = QDoubleSpinBox()
        self._ac_fstop.setRange(1e-6, 1e12)
        self._ac_fstop.setValue(1e6)
        form.addRow("AC sweep", self._ac_sweep)
        form.addRow("AC points", self._ac_points)
        form.addRow("AC fstart", self._ac_fstart)
        form.addRow("AC fstop", self._ac_fstop)
        layout.addLayout(form)

        group = QGroupBox("Величины")
        vbox = QVBoxLayout(group)
        self._series = QListWidget()
        self._series.setSelectionMode(QListWidget.MultiSelection)
        self._populate_series()
        vbox.addWidget(self._series)
        layout.addWidget(group)

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def _populate_series(self) -> None:
        cell = self.project.cell(self.cell)
        nets = sorted(cell.net_names())
        for net in nets:
            if net != "0":
                self._series.addItem(f"V({net})")
        for inst in cell.instances:
            self._series.addItem(f"I({inst.name})")
            entry = self.project.model_manager.entry(inst.master_cell)
            if entry is not None and entry.pins:
                self._series.addItem(f"@{inst.name}.x")

    def build_spec(self) -> AnalysisSpec:
        kind = self._kind.currentIndex()
        if kind == 0:
            return OpSpec()
        if kind == 1:
            return DcSpec(
                src=self._dc_src.text(),
                start=self._dc_start.value(),
                stop=self._dc_stop.value(),
                step=self._dc_step.value(),
            )
        if kind == 2:
            return TranSpec(
                tstep=self._tstep.value(),
                tstop=self._tstop.value(),
                tstart=self._tstart.value(),
            )
        return AcSpec(
            sweep=self._ac_sweep.currentText(),
            points=int(self._ac_points.value()),
            fstart=self._ac_fstart.value(),
            fstop=self._ac_fstop.value(),
        )

    def selected_series(self) -> list[str]:
        return [self._series.item(i).text() for i in range(self._series.count())
                if self._series.item(i).isSelected()]

    def validate(self) -> str | None:
        """Валидация до запуска (FR-SIM-003): нечисловые/недопустимые → сообщение."""
        if self._kind.currentIndex() == 1:
            spec = DcSpec(src=self._dc_src.text(), start=self._dc_start.value(),
                          stop=self._dc_stop.value(), step=self._dc_step.value())
            if spec.step <= 0:
                return "DC step должен быть > 0"
        if self._kind.currentIndex() == 2:
            if self._tstop.value() <= 0 or self._tstep.value() <= 0:
                return "TRAN tstep/tstop должны быть > 0"
        if self._kind.currentIndex() == 3:
            if self._ac_points.value() < 1 or self._ac_fstop.value() <= self._ac_fstart.value():
                return "AC: points ≥ 1, fstop > fstart"
        return None
