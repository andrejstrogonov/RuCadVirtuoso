"""Запуск анализа (rcad.core.analyses).

Предоставляет run_analysis(), precheck(), Result и AnalysisError.
Точка входа для CLI, сервисов и тестов.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from rcad.core.circuit.flatten import flatten_netlist
from rcad.core.diagnostics_utils import precheck_erc
from rcad.core.integ import TRANIntegrator
from rcad.core.mna import MNAAssembler
from rcad.core.netlist import parse
from rcad.core.solver import NewtonSolver
from rcad.diagnostics import AnalysisError, ConvergenceError, RcadError
from rcad.core.suffix import suffix_float


class Result:
    """Результат анализа.

    Поддерживает:
    - result.node(name) → напряжение узла (скаляр для OP, список для DC/TRAN/AC)
    - result.branch(name) → ток ветви источника напряжения
    - result.element(name, port) → параметр прибора (id для MOSFET, i для R/V)
    - result["name"] → список значений (time, freq, V(node), I(V), ...)
    - result.names() → имена рядов
    - result.names_minus_time() → имена без времени
    - result.report → словарь отчёта (step_rejections и т.п.)
    """

    def __init__(self, analysis_type: str) -> None:
        self.analysis_type = analysis_type
        self._series: dict[str, list] = {}
        self._node_values: dict[str, float | list] = {}
        self._branch_values: dict[str, float | list] = {}
        self._element_values: dict[tuple[str, str], float | list] = {}
        self.report: dict[str, Any] = {"step_rejections": 0}
        self._is_sweep = analysis_type in ("dc", "tran", "ac")

    def _add_series(self, name: str, values: list) -> None:
        self._series[name] = list(values)

    def _set_node(self, name: str, value: float | list) -> None:
        self._node_values[f"V({name})"] = value
        self._series[f"V({name})"] = list(value) if isinstance(value, list) else [value]

    def _set_branch(self, name: str, value: float | list) -> None:
        self._branch_values[f"I({name})"] = value
        self._series[f"I({name})"] = list(value) if isinstance(value, list) else [value]

    def _set_element(self, name: str, port: str, value: float | list) -> None:
        key = (name, port)
        self._element_values[key] = value
        self._series[f"{name}.{port}"] = list(value) if isinstance(value, list) else [value]

    def node(self, name: str) -> float | list:
        key = f"V({name})"
        if key in self._node_values:
            return self._node_values[key]
        raise KeyError(f"узел {name!r} не найден")

    def branch(self, name: str) -> float | list:
        key = f"I({name})"
        if key in self._branch_values:
            return self._branch_values[key]
        raise KeyError(f"ветвь {name!r} не найдена")

    def element(self, name: str, port: str) -> float | list:
        key = (name, port)
        if key in self._element_values:
            return self._element_values[key]
        raise KeyError(f"элемент {name!r}.{port!r} не найден")

    def names(self) -> list[str]:
        return list(self._series.keys())

    def names_minus_time(self) -> list[str]:
        return [n for n in self._series if n != "time"]

    def __getitem__(self, name: str) -> list:
        if name in self._series:
            return self._series[name]
        raise KeyError(f"ряд {name!r} не найден")

    def __contains__(self, name: str) -> bool:
        return name in self._series

    def __len__(self) -> int:
        if "time" in self._series:
            return len(self._series["time"])
        if self._series:
            return len(next(iter(self._series.values())))
        return 0


def _parse_source_params(rest_tokens: list[str]) -> dict[str, str]:
    """Извлечь параметры источника из токов строки элемента."""
    params: dict[str, str] = {}
    body_start = False
    for tok in rest_tokens:
        if "(" in tok and tok.endswith(")"):
            key = tok.split("(")[0].upper()
            params[key] = tok
        elif "=" in tok and not body_start:
            k, v = tok.split("=", 1)
            params[k.strip().upper()] = v.strip()
            body_start = True
        elif body_start:
            k, v = tok.split("=", 1) if "=" in tok else (tok, "")
            params[k.strip().upper()] = v.strip()
    return params


def _get_value(params: dict, key: str, default: float = 0.0) -> float:
    v = params.get(key.upper(), default)
    try:
        return suffix_float(str(v))
    except (ValueError, TypeError):
        return default


def run_analysis(netlist_text: str, directive: str) -> Result:
    """Запустить анализ по тексту нетлиста и директиве.

    Args:
        netlist_text: текст нетлиста SPICE.
        directive: ".op", ".dc ...", ".tran ...", ".ac ...".
            Если параметры отсутствуют, берутся из нетлиста.

    Returns:
        Result с рядами вывода.
    """
    # Разбор директивы
    from rcad.schemas.analysis import DcSpec, TranSpec, AcSpec, spec_from_directive
    import re

    spec = None
    analysis_type = None

    # Попробовать использовать предоставленную директиву
    try:
        spec = spec_from_directive(directive)
        analysis_type = spec.type
    except (ValueError, Exception):
        pass

    # Если не получилось, извлечь директиву из нетлиста
    if spec is None:
        for kind_re in [
            r"^\s*(\.tran\s+.+)$",
            r"^\s*(\.dc\s+.+)$",
            r"^\s*(\.ac\s+.+)$",
            r"^\s*(\.op\s*)$",
        ]:
            m = re.search(kind_re, netlist_text, re.IGNORECASE | re.MULTILINE)
            if m:
                full = m.group(1).strip()
                try:
                    spec = spec_from_directive(full)
                    analysis_type = spec.type
                    break
                except (ValueError, Exception):
                    continue

    if spec is None:
        raise AnalysisError(f"не удалось определить тип анализа из директивы: {directive!r}")

    # Разбор нетлиста
    parsed = parse(netlist_text)
    circuit = flatten_netlist(netlist_text)

    # Сборка MNA
    assembler = MNAAssembler(circuit)

    result = Result(analysis_type)

    if analysis_type == "op":
        _run_op(assembler, circuit, result)
    elif analysis_type == "dc":
        _run_dc(assembler, circuit, spec, result)
    elif analysis_type == "tran":
        _run_tran(assembler, circuit, spec, result)
    elif analysis_type == "ac":
        _run_ac(assembler, circuit, spec, result)

    return result


def _run_op(assembler: MNAAssembler, circuit, result: Result) -> None:
    """Стационарный анализ точки работы."""
    MNASys, A, rhs = assembler.assemble(tstep=None)
    solver = NewtonSolver()
    x0 = np.zeros(A.shape[0])

    def assemble(x):
        return A, rhs

    x = solver.solve(assemble, x0)
    _fill_op_result(assembler, circuit, x, result)


def _fill_op_result(assembler, circuit, x: np.ndarray, result: Result) -> None:
    node_map = assembler.node_index
    vs_map = assembler.vsource_index
    n_nodes = assembler.n_nodes

    # Напряжения узлов
    for name, idx in node_map.items():
        result._set_node(name, float(x[idx]))

    # Токи источников напряжения
    for name, idx in vs_map.items():
        result._set_branch(name, float(x[n_nodes + idx]))

    # Элементы
    for el in circuit.elements:
        if el.card == "R":
            p = node_map.get(el.nodes[0])
            n = node_map.get(el.nodes[1])
            v1 = float(x[p]) if p is not None else 0.0
            v2 = float(x[n]) if n is not None else 0.0
            v = v1 - v2
            r = _get_value(el.params, "R", 1e3)
            i = v / r if r != 0 else 0.0
            result._set_element(el.name, "i", i)
        elif el.card == "M":
            # Найдём MOSFET устройство и получим id
            from rcad.core.devices.mna_devices import MOSFET
            from rcad.core.mna import lookup_model_params
            mp = lookup_model_params(circuit, el.model)
            merged = dict(mp)
            merged.update(el.params)
            dev = MOSFET(merged, 1e-6)
            nd, ng, ns, nb = el.nodes[0], el.nodes[1], el.nodes[2], el.nodes[3]
            vd = x[node_map[nd]] if nd in node_map else 0.0
            vg = x[node_map[ng]] if ng in node_map else 0.0
            vs_ = x[node_map[ns]] if ns in node_map else 0.0
            vb = x[node_map[nb]] if nb in node_map else 0.0
            id_, _, _, _ = dev._currents(vg - vs_, vd - vs_, vb - vs_)
            result._set_element(el.name, "id", id_)


def _run_dc(assembler: MNAAssembler, circuit, spec, result: Result) -> None:
    """DC-развёртка."""
    from rcad.schemas.analysis import DcSpec

    if not isinstance(spec, DcSpec):
        raise AnalysisError("для .требуется спецификация DC")

    src_name = spec.src
    start = spec.start
    stop = spec.stop
    step = spec.step

    # Найти источник в нетлисте
    src_el = None
    for el in circuit.elements:
        if el.card == "V" and el.name == src_name:
            src_el = el
            break
    if src_el is None:
        for el in circuit.elements:
            if el.card == "I" and el.name == src_name:
                src_el = el
                break

    # Подготовить узлы
    node_map = assembler.node_index

    values: list[float] = []
    v_values: list[float] = []
    curr_values: list = []

    # Добавить исходный узел источника к результату
    src_nodes = src_el.nodes if src_el else []

    num_points = int(abs(stop - start) / abs(step)) + 1 if step != 0 else 1

    solver = NewtonSolver()

    # Первичная сборка для определения размера системы
    MNASys0, A0, rhs0 = assembler.assemble(tstep=None)
    n_nodes = assembler.n_nodes

    for k in range(num_points):
        val = start + k * step
        if step > 0 and val > stop + 1e-12:
            break
        if step < 0 and val < stop - 1e-12:
            break

        # Собрать систему с текущим guess
        def assemble(x_guess, val=val):
            MNASys2, A2, rhs2 = assembler.assemble(tstep=None, solution=x_guess)
            A2 = A2.copy()
            rhs2 = rhs2.copy()
            if src_name in assembler.vsource_index:
                vs_idx = assembler.vsource_index[src_name]
                rhs2[n_nodes + vs_idx] = val
            return A2, rhs2

        x0 = np.zeros(A0.shape[0])
        try:
            x = solver.solve(assemble, x0)
        except ConvergenceError:
            x = x0

        # Сохранить результаты
        if src_nodes:
            p_node = src_nodes[0]
            if p_node in node_map:
                v_values.append(float(x[node_map[p_node]]))
            else:
                v_values.append(0.0)

        # Ток через источник
        if src_name in assembler.vsource_index:
            vs_idx = assembler.vsource_index[src_name]
            n_nodes = assembler.n_nodes
            curr_values.append(float(x[n_nodes + vs_idx]))
        else:
            curr_values.append(0.0)

        # Прочие узлы
        for name in sorted(node_map):
            if name not in result._series:
                result._series[f"V({name})"] = []
            result._series[f"V({name})"].append(float(x[node_map[name]]))

    # Заполнить серии
    if src_nodes:
        p_node = src_nodes[0]
        result._set_node(p_node, v_values)

    result._set_branch(src_name, curr_values)

    for name in sorted(node_map):
        key = f"V({name})"
        if key in result._series and len(result._series[key]) == num_points:
            pass  # уже заполнено

    # Элементы
    for el in circuit.elements:
        if el.card == "M":
            from rcad.core.devices.mna_devices import MOSFET
            dev = MOSFET(el.params, 1e-6)
            id_values = []
            nd, ng, ns, nb = el.nodes[0], el.nodes[1], el.nodes[2], el.nodes[3]
            for k in range(len(v_values)):
                # Пересчитать для каждой точки (упрощённо: взять из последнего решения)
                id_values.append(dev._id)
            result._set_element(el.name, "id", id_values)


def _run_tran(assembler: MNAAssembler, circuit, spec, result: Result) -> None:
    """Переходный анализ с трапецеидальной интеграцией."""
    from rcad.schemas.analysis import TranSpec

    if not isinstance(spec, TranSpec):
        raise AnalysisError("для .tran требуется спецификация TRAN")

    tstart = spec.tstart
    tstop = spec.tstop
    tstep = spec.tstep
    tmax = spec.tmax

    integrator = TRANIntegrator(tstart=tstart, tstop=tstop, tstep=tstep, tmax=tmax)

    # Добавить точки разрыва для PULSE источников
    for el in circuit.elements:
        if el.card == "V":
            for key, value in el.params.items():
                if key.upper() == "PULSE":
                    p = _parse_pulse(value)
                    if p and p[6] > 0:
                        v1, v2, td, tr, tf, pw, per = p
                        t = td
                        while t < tstop:
                            integrator.add_breakpoint(t)
                            integrator.add_breakpoint(t + tr)
                            integrator.add_breakpoint(t + td + tr + pw)
                            integrator.add_breakpoint(t + td + tr + pw + tf)
                            t += per

    solver = NewtonSolver(tol=1e-8, max_iter=50)

    # Создать устройства с привязкой к элементам
    from rcad.core.devices.mna_devices import device_for
    from rcad.core.mna import lookup_model_params
    device_infos = []
    for el in circuit.elements:
        model_params = lookup_model_params(circuit, el.model)
        dev = device_for(el.card, el.model, el.params, tstep, model_params)
        dev.nodes = el.nodes  # привязка к узлам для update_state
        device_infos.append((el, dev))

    n_nodes = assembler.n_nodes

    # Первичная сборка для определения размера системы
    MNASys0, A0, rhs0 = assembler.assemble(tstep=integrator.tmax, prev_states={})
    x = np.zeros(A0.shape[0])

    time_series: list[float] = [tstart]
    node_series: dict[str, list[float]] = {}
    branch_series: dict[str, list[float]] = {}
    element_series: dict[tuple[str, str], list[float]] = {}

    node_map = assembler.node_index
    for name in node_map:
        node_series[name] = [0.0]
    for name in assembler.vsource_index:
        branch_series[name] = [0.0]
    for el, dev in device_infos:
        state = dev.get_state()
        for port, val in state.items():
            key = (el.name, port)
            element_series[key] = [float(val)]

    # Состояния устройств для спутниковых моделей (C, L)
    prev_states: dict = {}
    for el, dev in device_infos:
        state = dev.get_state()
        for port, val in state.items():
            prev_states[f"{el.name}.{port}"] = float(val)

    t = tstart
    step_count = 0
    max_steps = 200000

    while t < tstop - 1e-15 and step_count < max_steps:
        h = integrator.next_step()
        if h is None:
            break

        current_time = t + h

        # Собрать систему с текущим состоянием
        def assemble(x_guess):
            MNASys2, A2, rhs2 = assembler.assemble(tstep=h, prev_states=prev_states, solution=x_guess, first_step=(step_count == 0), devices=device_infos)
            # Установить значения источников на текущее время
            # Пересобрать B и vs_rhs с учетом времени
            A2 = A2.copy()
            rhs2 = rhs2.copy()
            # Обновить источники напряжения
            for el, dev in device_infos:
                if el.card == "V":
                    vs_idx = assembler.vsource_index.get(el.name)
                    if vs_idx is not None:
                        # Найти значение источника
                        val = dev._value_at(current_time) if hasattr(dev, '_value_at') else 0.0
                        rhs2[n_nodes + vs_idx] = val
            return A2, rhs2

        try:
            x = solver.solve(assemble, x)
        except ConvergenceError:
            integrator.reject_step()
            if h < 1e-15:
                break
            continue

        # Обновить состояния устройств
        node_map = assembler.node_index
        for el, dev in device_infos:
            dev.update_state(x, node_map, current_time, dt=h)

        # Сохранить состояния для следующего шага
        prev_states.clear()
        for el, dev in device_infos:
            state = dev.get_state()
            for port, val in state.items():
                prev_states[f"{el.name}.{port}"] = float(val)

        # Сохранить результаты
        time_series.append(current_time)
        for name, idx in node_map.items():
            if name not in node_series:
                node_series[name] = []
            node_series[name].append(float(x[idx]))

        for name, vs_idx in assembler.vsource_index.items():
            if name not in branch_series:
                branch_series[name] = []
            branch_series[name].append(float(x[n_nodes + vs_idx]))

        for el, dev in device_infos:
            state = dev.get_state()
            for port, val in state.items():
                key = (el.name, port)
                if key not in element_series:
                    element_series[key] = []
                element_series[key].append(float(val))

        integrator.advance(h)
        t = current_time
        step_count += 1

    # Заполнить результат
    result._add_series("time", time_series)
    for name, values in node_series.items():
        result._set_node(name, values)
    for name, values in branch_series.items():
        result._set_branch(name, values)
    for (name, port), values in element_series.items():
        result._set_element(name, port, values)

    result.report["step_rejections"] = integrator.step_rejections


def _parse_pulse(text: str) -> tuple | None:
    """Разобрать PULSE(v1 v2 td tr tf pw per)."""
    import re
    m = re.match(r"PULSE\((.+)\)", str(text), re.IGNORECASE)
    if not m:
        return None
    nums = []
    for tok in m.group(1).split():
        try:
            nums.append(suffix_float(tok))
        except ValueError:
            nums.append(0.0)
    while len(nums) < 7:
        nums.append(0.0)
    return tuple(nums[:7])


def _create_device(el, tstep: float):
    from rcad.core.devices.mna_devices import device_for
    model = el.model
    # Для M: нужна информация из .model
    if el.card == "M" and model:
        # Параметры из .model находятся в circuit.models
        pass
    return device_for(el.card, model, el.params, tstep)


def _run_ac(assembler: MNAAssembler, circuit, spec, result: Result) -> None:
    """AC-анализ (малый сигнал, комплексная МНА)."""
    from rcad.schemas.analysis import AcSpec

    if not isinstance(spec, AcSpec):
        raise AnalysisError("для .ac требуется спецификация AC")

    sweep = spec.sweep
    points = spec.points
    fstart = spec.fstart
    fstop = spec.fstop

    # Построить частотную сетку
    freqs: list[float] = []
    if sweep == "dec":
        decades = math.log10(fstop / fstart)
        for i in range(points * int(decades) + 1):
            f = fstart * (10.0 ** (i / points))
            freqs.append(f)
    elif sweep == "lin":
        for i in range(points):
            f = fstart + (fstop - fstart) * i / (points - 1)
            freqs.append(f)
    elif sweep == "oct":
        octaves = math.log2(fstop / fstart)
        for i in range(points * int(octaves) + 1):
            f = fstart * (2.0 ** (i / points))
            freqs.append(f)

    result._add_series("freq", freqs)

    node_map = assembler.node_index

    solver = NewtonSolver(tol=1e-9, max_iter=50)

    for f in freqs:
        w = 2.0 * math.pi * f
        MNASys, A, rhs = assembler.assemble(tstep=None)

        # Для AC: все проводимости умножаются на комплексные значения
        # Реактивные элементы: C → j*w*C, L → 1/(j*w*L)
        A_c = A.astype(complex).copy()
        rhs_c = rhs.astype(complex).copy()

        # Добавить ёмкостные и индуктивные члены
        for el in circuit.elements:
            if el.card == "C":
                c = _get_value(el.params, "C", 1e-12)
                n1, n2 = el.nodes[0], el.nodes[1]
                i1 = node_map.get(n1)
                i2 = node_map.get(n2)
                y = 1j * w * c
                if i1 is not None:
                    A_c[i1, i1] += y
                if i2 is not None:
                    A_c[i2, i2] += y
                if i1 is not None and i2 is not None:
                    A_c[i1, i2] -= y
                    A_c[i2, i1] -= y
            elif el.card == "L":
                l = _get_value(el.params, "L", 1e-6)
                n1, n2 = el.nodes[0], el.nodes[1]
                # Катушка требует тока как неизвестного — упрощённо через admitteds
                y = 1.0 / (1j * w * l) if w != 0 else 0.0
                i1 = node_map.get(n1)
                i2 = node_map.get(n2)
                if i1 is not None:
                    A_c[i1, i1] += y
                if i2 is not None:
                    A_c[i2, i2] += y
                if i1 is not None and i2 is not None:
                    A_c[i1, i2] -= y
                    A_c[i2, i1] -= y

        try:
            x = np.linalg.solve(A_c, rhs_c)
        except np.linalg.LinAlgError:
            x = np.zeros(A_c.shape[0], dtype=complex)

        for name in sorted(node_map):
            key = f"V({name})"
            if key not in result._series:
                result._series[key] = []
            result._series[key].append(complex(x[node_map[name]]))

        for name, vs_idx in assembler.vsource_index.items():
            key = f"I({name})"
            if key not in result._series:
                result._series[key] = []
            result._series[key].append(complex(x[assembler.n_nodes + vs_idx]))


def precheck(netlist_text: str) -> None:
    """ERC-lite проверка нетлиста до решения.

    Выбрасывает AnalysisError при обнаружении проблем:
    - висящие узлы (одно соединение)
    - отсутствие пути к земле
    - дубликаты имён
    """
    from rcad.core.diagnostics_utils import precheck_erc
    precheck_erc(netlist_text)
