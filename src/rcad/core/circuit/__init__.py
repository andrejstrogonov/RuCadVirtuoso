"""Развертывание иерархии .subckt в плоский список элементов (rcad.core.circuit).

`flatten()` возвращает FlatCircuit с иерархическими именами узлов
(например X1.X2.mid). Узел "0" остаётся глобальной землёй.
"""

from __future__ import annotations

from rcad.core.circuit.flatten import FlatCircuit, flatten_netlist

flatten = flatten_netlist

__all__ = ["flatten", "FlatCircuit"]
