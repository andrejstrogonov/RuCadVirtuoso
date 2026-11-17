"""Circuit and CrossbarArray classes for simulating multi-device configurations.

ТЗ п. 9.5–9.7: Circuit для комбинации устройств; CrossbarArray для
симуляции матриц кроссбарных массивов с моделями устройств.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .device import Device


@runtime_checkable
class VoltageSource(Protocol):
    """Протокол для источника напряжения."""

    def voltage(self, t: float) -> float:
        """Return voltage at time t."""
        ...


@runtime_checkable
class CurrentSink(Protocol):
    """Протокол для токового стока."""

    def current(self, t: float) -> float:
        """Return current at time t."""
        ...


@dataclass
class CircuitElement:
    """Элемент схемы с подключением к узлам."""

    device: Device
    node_a: str
    node_b: str


@dataclass
class Circuit:
    """Базовый класс для моделирования электрических схем.

    Поддерживает:
    - Добавление элементов (устройств) к узлам
    - Кирхгофовские уравнения для узлов
    - Итерационное решение методом Ньютона
    - Симуляцию временных импульсных воздействий
    """

    nodes: dict[str, float] = field(default_factory=dict)
    elements: list[CircuitElement] = field(default_factory=list)
    sources: list[tuple[str, str, float]] = field(default_factory=list)
    sinks: list[str] = field(default_factory=list)
    _voltage_sources: list[VoltageSource] = field(default_factory=list)

    def add_node(self, name: str, voltage: float = 0.0) -> None:
        """Добавить узел в схему."""
        self.nodes[name] = voltage

    def add_element(self, element: CircuitElement) -> None:
        """Добавить элемент (устройство) к узлам."""
        self.elements.append(element)
        if element.node_a not in self.nodes:
            self.add_node(element.node_a)
        if element.node_b not in self.nodes:
            self.add_node(element.node_b)

    def add_voltage_source(self, node_a: str, node_b: str, voltage: float) -> None:
        """Добавить источник напряжения между узлами."""
        self.sources.append((node_a, node_b, voltage))

    def add_voltage_source_dynamic(
        self,
        node_a: str,
        node_b: str,
        source: VoltageSource,
    ) -> None:
        """Добавить динамический источник напряжения."""
        self.add_voltage_source(node_a, node_b, 0.0)
        self._voltage_sources.append(source)

    def add_current_sink(self, node: str) -> None:
        """Добавить токовый сток на узел."""
        self.sinks.append(node)

    def solve_kirchhoff(self) -> None:
        """Решить уравнения Кирхгофа для схемы (Newton-Raphson)."""
        max_iter = 100
        tolerance = 1e-9
        for _ in range(max_iter):
            residuals = self._compute_residuals()
            if max(abs(r) for r in residuals) < tolerance:
                break
            # Simplified: update node voltages
            for node in self.nodes:
                idx = list(self.nodes.keys()).index(node)
                self.nodes[node] -= residuals[idx] * 0.1

    def _compute_residuals(self) -> list[float]:
        """Вычислить остаточные токи на каждом узле."""
        residuals = {node: 0.0 for node in self.nodes}
        for elem in self.elements:
            v_diff = self.nodes[elem.node_a] - self.nodes[elem.node_b]
            current = elem.device.iv_curve(v_diff)
            residuals[elem.node_a] -= current
            residuals[elem.node_b] += current
        return list(residuals.values())

    def simulate(
        self,
        t_start: float,
        t_end: float,
        dt: float,
    ) -> dict[str, list[float]]:
        """Выполнить временную симуляцию схемы.

        Args:
            t_start: Время начала.
            t_end: Время окончания.
            dt: Шаг времени.

        Returns:
            Словарь {node: [voltage_values]}.
        """
        voltages: dict[str, list[float]] = {n: [] for n in self.nodes}
        t = t_start
        while t <= t_end:
            for i, src in enumerate(self._voltage_sources):
                v = src.voltage(t)
                if i < len(self.sources):
                    na, nb, _ = self.sources[i]
                    self.sources[i] = (na, nb, v)
            self.solve_kirchhoff()
            for node in self.nodes:
                voltages[node].append(self.nodes[node])
            t += dt
        return voltages

    def reset(self) -> None:
        """Сбросить состояние схемы."""
        for elem in self.elements:
            elem.device.reset_state()
        self.nodes.clear()


@dataclass
class CrossbarArray:
    """Моделирование кроссбарного массива устройств.

    Поддерживает:
    - Матрицы размеров MxN
    - Симуляцию записи/считывания/стирания
    - Моделирование эффектов межсоединений (паразитов)
    - Визуализацию распределения состояний
    """

    rows: int
    cols: int
    devices: list[list[Device]] = field(default_factory=list)
    word_line_resistance: float = 0.0
    bit_line_resistance: float = 0.0
    parasitic_capacitance: float = 0.0
    parasitic_resistance: float = 0.0

    def __post_init__(self) -> None:
        """Инициализировать массив устройствами."""
        self.devices = [
            [None for _ in range(self.cols)] for _ in range(self.rows)
        ]

    def populate(self, device_class: type[Device], params: dict | None = None) -> None:
        """Заполнить массив устройствами одного типа."""
        for i in range(self.rows):
            for j in range(self.cols):
                self.devices[i][j] = device_class(params)

    def write(self, row: int, col: int, value: float) -> None:
        """Записать значение в ячейку (установить состояние)."""
        if 0 <= row < self.rows and 0 <= col < self.cols:
            device = self.devices[row][col]
            if device is not None:
                device._state.value = max(0.0, min(1.0, value))

    def read(self, row: int, col: int) -> float:
        """Считать состояние ячейки."""
        if 0 <= row < self.rows and 0 <= col < self.cols:
            device = self.devices[row][col]
            if device is not None:
                return device.state
        return 0.0

    def erase(self, row: int, col: int) -> None:
        """Стереть ячейку (сбросить состояние)."""
        if 0 <= row < self.rows and 0 <= col < self.cols:
            device = self.devices[row][col]
            if device is not None:
                device.reset_state()

    def simulate_read_row(self, row: int, voltages: list[float]) -> list[float]:
        """Симулировать считывание строки с заданными напряжениями."""
        if row < 0 or row >= self.rows:
            return []
        results = []
        for col, v in enumerate(voltages):
            device = self.devices[row][col]
            if device is not None:
                current = device.iv_curve(v)
                r_total = (
                    self.bit_line_resistance
                    + self.word_line_resistance
                    + self.parasitic_resistance
                )
                v_drop = current * r_total
                results.append(v - v_drop)
            else:
                results.append(0.0)
        return results

    def simulate_write_row(self, row: int, pulses: list[tuple[float, float, float]]) -> None:
        """Симулировать запись строки с импульсами."""
        if row < 0 or row >= self.rows:
            return
        for col in range(self.cols):
            device = self.devices[row][col]
            if device is not None:
                device.evaluate_pulses(pulses)

    def get_state_matrix(self) -> list[list[float]]:
        """Получить матрицу состояний массива."""
        return [
            [self.devices[i][j].state for j in range(self.cols)]
            for i in range(self.rows)
        ]

    def reset(self) -> None:
        """Сбросить все устройства массива."""
        for i in range(self.rows):
            for j in range(self.cols):
                device = self.devices[i][j]
                if device is not None:
                    device.reset_state()