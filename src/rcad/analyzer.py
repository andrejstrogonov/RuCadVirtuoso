"""Analysis utilities for Circuit and CrossbarArray simulations.

ТЗ п. 9.8: Analyzer для анализа результатов моделирования.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .circuit import Circuit, CrossbarArray
from .device import Device


@dataclass
class AnalysisSpec:
    """Спецификация анализа."""

    type: str  # "dc", "tran", "ac", "op"
    sweep_start: float = 0.0
    sweep_end: float = 10.0
    sweep_points: int = 100
    time_stop: float = 1.0
    time_step: float = 1e-9
    sources: dict[str, float] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Результат анализа."""

    analysis_type: str
    data: dict[str, list[float]] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)

    def get(self, key: str) -> list[float]:
        """Получить данные по ключу."""
        return self.data.get(key, [])

    def __getitem__(self, key: str) -> list[float]:
        return self.data.get(key, [])

    def __setitem__(self, key: str, value: list[float]) -> None:
        self.data[key] = value


@dataclass
class DeviceStatistics:
    """Статистика по устройствам."""

    count: int
    state_min: float = 0.0
    state_max: float = 1.0
    state_mean: float = 0.5
    state_std: float = 0.0
    write_errors: int = 0
    read_errors: int = 0


def dc_analysis(circuit: Circuit, spec: AnalysisSpec) -> AnalysisResult:
    """Выполнить DC-анализ схемы.

    Развёртка одного или нескольких источников напряжения/тока.
    """
    result = AnalysisResult(analysis_type="dc")
    sources = list(spec.sources.keys())

    if not sources:
        result.diagnostics.append("No sweep sources specified")
        return result

    source_name = sources[0]
    voltages = []
    results = []

    for i in range(spec.sweep_points):
        v = spec.sweep_start + i * (spec.sweep_end - spec.sweep_start) / max(
            spec.sweep_points - 1, 1
        )
        circuit.nodes[source_name] = v
        voltage = v
        for node in circuit.nodes:
            circuit.nodes[node] = v if node == source_name else 0.0
        circuit.solve_kirchhoff()
        voltages.append(voltage)
        node_results = {node: circuit.nodes[node] for node in circuit.nodes}
        results.append(node_results)

    result["sweep"] = voltages
    for node in results[0]:
        result[f"V({node})"] = [r[node] for r in results]

    result.metadata = {"type": "dc", "sweep_source": source_name}
    return result


def transient_analysis(circuit: Circuit, spec: AnalysisSpec) -> AnalysisResult:
    """Выполнить transient-анализ схемы."""
    result = AnalysisResult(analysis_type="tran")
    steps = int(spec.time_stop / spec.time_step)

    time_stamps = []
    node_values: dict[str, list[float]] = {}
    for node in circuit.nodes:
        node_values[node] = []

    for step in range(steps):
        t = step * spec.time_step
        time_stamps.append(t)
        for node in circuit.nodes:
            v = circuit.nodes[node]
            node_values[node].append(v)

    result["time"] = time_stamps
    for node in node_values:
        result[f"V({node})"] = node_values[node]

    result.metadata = {
        "type": "tran",
        "time_stop": spec.time_stop,
        "time_step": spec.time_step,
    }
    return result


def op_analysis(circuit: Circuit) -> AnalysisResult:
    """Выполнить анализ рабочей точки (OP)."""
    result = AnalysisResult(analysis_type="op")
    circuit.solve_kirchhoff()
    result["voltage"] = list(circuit.nodes.values())
    result.metadata = {"type": "op", "nodes": list(circuit.nodes.keys())}
    return result


def analyze_crossbar(array: CrossbarArray) -> AnalysisResult:
    """Анализировать кроссбарный массив."""
    result = AnalysisResult(analysis_type="crossbar")
    matrix = array.get_state_matrix()

    # Compute statistics
    all_states = [state for row in matrix for state in row]
    if all_states:
        count = len(all_states)
        state_min = min(all_states)
        state_max = max(all_states)
        state_mean = sum(all_states) / count
        state_var = sum((s - state_mean) ** 2 for s in all_states) / count
        state_std = state_var**0.5

        stats = DeviceStatistics(
            count=count,
            state_min=state_min,
            state_max=state_max,
            state_mean=state_mean,
            state_std=state_std,
        )
        result.metadata["statistics"] = stats
    else:
        result.metadata["statistics"] = DeviceStatistics(count=0)

    # Convert to list of lists for JSON serialization
    result["state_matrix"] = matrix
    result.metadata["rows"] = array.rows
    result.metadata["cols"] = array.cols
    result.metadata["parasitic_resistance"] = array.parasitic_resistance

    return result


def run_analysis(
    target: Circuit | CrossbarArray, spec: AnalysisSpec | None = None
) -> AnalysisResult:
    """Запустить анализ.

    Args:
        target: Circuit или CrossbarArray
        spec: Спецификация анализа

    Returns:
        AnalysisResult с результатами
    """
    if isinstance(target, CrossbarArray):
        return analyze_crossbar(target)

    if spec is None:
        spec = AnalysisSpec(type="dc")

    if spec.type == "dc":
        return dc_analysis(target, spec)
    elif spec.type == "tran":
        return transient_analysis(target, spec)
    elif spec.type == "op":
        return op_analysis(target)
    else:
        raise ValueError(f"Unknown analysis type: {spec.type}")