"""ERC-lite утилиты для precheck (rcad.core.diagnostics_utils).

Проверка нетлиста на структурные ошибки до запуска решателя.
"""

from __future__ import annotations

import re
from collections import defaultdict

from rcad.core.netlist import parse
from rcad.diagnostics import AnalysisError, DiagnosticCode


def precheck_erc(netlist_text: str) -> None:
    """Проверить нетлист на явные ошибки.

    Выбрасывает AnalysisError с диагностикой при проблемах.
    """
    parsed = parse(netlist_text)

    # Собрать все подключения узлов
    node_connections: dict[str, list[str]] = defaultdict(list)
    has_ground = False

    for el in parsed.top_elements:
        for node in el.nodes:
            node_connections[node].append(el.name)
            if node == "0":
                has_ground = True

    # Также проверить узлы внутри subcктов (плоская версия)
    from rcad.core.circuit.flatten import flatten_netlist

    circuit = flatten_netlist(netlist_text)
    flat_connections: dict[str, list[str]] = defaultdict(list)
    for el in circuit.elements:
        for node in el.nodes:
            flat_connections[node].append(el.name)
            if node == "0":
                has_ground = True

    # Висячие узлы: только одно подключение (и не земля)
    for node, conns in flat_connections.items():
        if node == "0":
            continue
        if len(conns) < 2:
            raise AnalysisError(
                f"висящий узел {node!r} имеет только одно подключение",
                _make_diag(DiagnosticCode.E_FLOATING, f"длингищий узел {node}", node),
            )

    # Проверка пути к земле
    if not has_ground:
        raise AnalysisError(
            "нет узла земли (0) в нетлисте",
            _make_diag(DiagnosticCode.E_NO_GROUND, "нет узла земли"),
        )


def _make_diag(code, message, object_name="") -> object:
    from dataclasses import dataclass

    @dataclass
    class _Diag:
        code: str
        message: str
        object_name: str

    return _Diag(code=code.value if hasattr(code, "value") else str(code), message=message, object_name=object_name)
