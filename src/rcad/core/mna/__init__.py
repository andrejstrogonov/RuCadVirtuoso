"""MNA-матрица и штампы приборов (rcad.core.mna).

Собирает Modified Nodal Analysis систему для линейных и нелинейных приборов.
Поддерживает OP, DC, TRAN, AC анализы. Слой полностью headless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from rcad.core.circuit.flatten import FlatCircuit
from rcad.core.devices.mna_devices import device_for, DeviceModel
from rcad.core.suffix import suffix_float


def lookup_model_params(circuit, model_name: str | None) -> dict:
    """Найти параметры модели по имени, а при неудаче — по типу."""
    if not model_name:
        return {}
    if model_name in circuit.models:
        return dict(circuit.models[model_name].params)
    # Фоллбек: искать по типу модели
    for m in circuit.models.values():
        if m.type == model_name:
            return dict(m.params)
    return {}


@dataclass
class MNASystem:
    """Собранная MNA система.

    Неизвестные: [напряжения узлов (кроме земли), токи источников напряжения].
    Полная матрица системы: [G  B; -B^T  0].
    """

    n_nodes: int
    node_index: dict[str, int]
    vsource_index: dict[str, int]
    node_list: list[str]
    vsource_list: list[str]
    G: np.ndarray
    B: np.ndarray
    C: np.ndarray
    b: np.ndarray

    @property
    def size(self) -> int:
        return self.n_nodes + len(self.vsource_list)

    def full_matrix(self) -> np.ndarray:
        """Полная матрица [G  B; -B^T  0]."""
        n = self.n_nodes
        m = len(self.vsource_list)
        A = np.zeros((n + m, n + m), dtype=float)
        A[:n, :n] = self.G
        A[:n, n:] = self.B
        A[n:, :n] = -self.B.T
        return A

    def full_rhs(self) -> np.ndarray:
        n = self.n_nodes
        m = len(self.vsource_list)
        rhs = np.zeros(n + m, dtype=float)
        rhs[:n] = self.b
        rhs[n:] = 0.0  # KVL RHS set by add_vsource
        return rhs


class MNAAssembler:
    """Собирает MNA систему из плоского нетлиста."""

    def __init__(self, circuit: FlatCircuit, tstep: float = 1e-6) -> None:
        self.circuit = circuit
        self.tstep = tstep
        self.node_index: dict[str, int] = {}
        self.node_list: list[str] = []
        self.vsource_index: dict[str, int] = {}
        self.vsource_list: list[str] = []
        self._build_node_map()

    def _build_node_map(self) -> None:
        idx = 0
        for name in self.circuit.node_names:
            if name == "0":
                continue
            self.node_index[name] = idx
            self.node_list.append(name)
            idx += 1
        self.n_nodes = len(self.node_list)

    def _nidx(self, name: str) -> int | None:
        if name == "0":
            return None
        return self.node_index.get(name)

    def _collect_vsources(self) -> None:
        self.vsource_index = {}
        self.vsource_list = []
        for el in self.circuit.elements:
            if el.card == "V":
                self.vsource_index[el.name] = len(self.vsource_list)
                self.vsource_list.append(el.name)

    def assemble(self, tstep: float | None = None, prev_states: dict | None = None, solution: np.ndarray | None = None, first_step: bool = False, devices: list | None = None) -> MNASystem:
        """Собрать MNA систему. tstep задан → трапецеидовая модель для TRAN."""
        if tstep is not None:
            self.tstep = tstep
        self._collect_vsources()

        n = self.n_nodes = len(self.node_list)
        m = len(self.vsource_list)
        G = np.zeros((n, n))
        B = np.zeros((n, m))
        C = np.zeros((n, n))
        b = np.zeros(n)

        # KVL RHS для источников напряжения (будет размещено в lower part при решении)
        vs_rhs = np.zeros(m)

        ctx = _MNAContext(
            G=G, B=B, b=b, C=C, vs_rhs=vs_rhs,
            assembler=self, tstep=self.tstep, prev_states=prev_states or {},
            solution=solution, first_step=first_step,
        )

        dev_map = {el.name: dev for el, dev in devices} if devices else {}
        for el in self.circuit.elements:
            dev = dev_map.get(el.name)
            if dev is None:
                model_params = lookup_model_params(self.circuit, el.model)
                dev = device_for(el.card, el.model, el.params, self.tstep, model_params)
            dev.stamp(ctx, el.name, el.nodes, self.circuit.initial_conditions, solution=solution)

        # Построить полную матрицу и правую часть
        size = n + m
        A = np.zeros((size, size))
        A[:n, :n] = G
        A[:n, n:] = B
        A[n:, :n] = -B.T
        A[n:, n:] = 0.0
        rhs = np.zeros(size)
        rhs[:n] = b
        rhs[n:] = vs_rhs

        return MNASystem(
            n_nodes=n,
            node_index=dict(self.node_index),
            vsource_index=dict(self.vsource_index),
            node_list=list(self.node_list),
            vsource_list=list(self.vsource_list),
            G=G,
            B=B,
            C=C,
            b=b,
        ), A, rhs


class _MNAContext:
    """Контекст сборки MNA."""

    def __init__(
        self,
        G: np.ndarray,
        B: np.ndarray,
        b: np.ndarray,
        C: np.ndarray,
        vs_rhs: np.ndarray,
        assembler: MNAAssembler,
        tstep: float,
        prev_states: dict,
        solution: np.ndarray | None = None,
        first_step: bool = False,
    ) -> None:
        self.G = G
        self.B = B
        self.b = b
        self.C = C
        self.vs_rhs = vs_rhs
        self.assembler = assembler
        self.tstep = tstep
        self.prev_states = prev_states
        self.solution = solution
        self.first_step = first_step

    def node_index(self, name: str) -> int | None:
        return self.assembler._nidx(name)

    def vsource_col(self, name: str) -> int | None:
        idx = self.assembler.vsource_index.get(name)
        if idx is None:
            return None
        return self.assembler.n_nodes + idx

    def add_conductance(self, n1: str, n2: str, g: float) -> None:
        i1 = self.node_index(n1)
        i2 = self.node_index(n2)
        if i1 is not None:
            self.G[i1, i1] += g
        if i2 is not None:
            self.G[i2, i2] += g
        if i1 is not None and i2 is not None:
            self.G[i1, i2] -= g
            self.G[i2, i1] -= g

    def add_current(self, node: str, value: float) -> None:
        i = self.node_index(node)
        if i is not None:
            self.b[i] += value

    def add_vsource(self, name: str, p_node: str, n_node: str, value: float) -> None:
        vs_idx = self.assembler.vsource_index.get(name)
        if vs_idx is None:
            return
        vs_col = self.vsource_col(name)
        ip = self.node_index(p_node)
        inn = self.node_index(n_node)
        # KCL: ток через источник в узлы
        if ip is not None:
            self.B[ip, vs_idx] = -1.0
        if inn is not None:
            self.B[inn, vs_idx] = 1.0
        # KVL: vp - vn = value
        self.vs_rhs[vs_idx] = value

    def add_capacitor_companion(self, n1: str, n2: str, c: float, v_prev: float, i_prev: float) -> None:
        if self.first_step:
            # Обратная Эйлер для первого шага (не нужен i_prev)
            g_eq = c / self.tstep
            i_hist = g_eq * v_prev
        else:
            g_eq = 2.0 * c / self.tstep
            i_hist = g_eq * v_prev + i_prev
        self.add_conductance(n1, n2, g_eq)
        i1 = self.node_index(n1)
        i2 = self.node_index(n2)
        if i1 is not None:
            self.b[i1] += i_hist
        if i2 is not None:
            self.b[i2] -= i_hist

    def add_inductor_companion(self, n1: str, n2: str, l: float, i_prev: float, v_prev: float) -> None:
        # Катушка: V = L*dI/dt → трапецеидальная спутник-модель
        # I_n - I_prev = (dt/2L)*(V_n + V_prev)
        # V_n = (2L/dt)*(I_n - I_prev) - V_prev
        # Моделируем через добавочный источник напряжения (требует vsource unknown)
        r_eq = self.tstep / (2.0 * l)
        g_eq = 1.0 / r_eq
        v_hist = (2.0 * l / self.tstep) * i_prev + v_prev
        self.add_conductance(n1, n2, g_eq)
        # Источник напряжения v_hist последовательно с катушкой:
        # эквивалентный ток в узел n1: v_hist / r_eq (выходящий)
        if self.node_index(n1) is not None:
            self.b[self.node_index(n1)] -= v_hist * g_eq
        if self.node_index(n2) is not None:
            self.b[self.node_index(n2)] += v_hist * g_eq
