"""T12: иерархия subckt в 3 уровня — результат идентичен плоской схеме."""

from __future__ import annotations

import pytest

from conftest import requires_core

pytestmark = [pytest.mark.tcase("T12"), requires_core]

HIERARCHICAL = """\
* T12: три уровня .subckt
.subckt level3 a b
R3 a b 1k
.ends
.subckt level2 a b
X3 a b level3
.ends
.subckt level1 a b
R1 a mid 1k
X2 mid b level2
.ends
V1 in 0 DC 3
X1 in 0 level1
.op
.end
"""

FLAT = """\
* T12: эквивалентная плоская схема
V1 in 0 DC 3
R1 in mid 1k
R3 mid 0 1k
.op
.end
"""


def test_hierarchy_matches_flat_circuit() -> None:
    from rcad.core.analyses import run_analysis

    hierarchical = run_analysis(HIERARCHICAL, ".op")
    flat = run_analysis(FLAT, ".op")
    assert abs(hierarchical["V(mid)"] - flat["V(mid)"]) <= 1e-12
    assert abs(hierarchical["V(X1.X2.X3.a)"] - flat["V(mid)"]) <= 1e-12


def test_node_paths_are_preserved() -> None:
    from rcad.core.circuit import flatten

    circuit = flatten(HIERARCHICAL)
    assert "X1.X2.mid" in circuit.node_names
    assert "X1.X2.X3.a" in circuit.node_names


def test_cyclic_subckt_is_rejected() -> None:
    """FR-NL-010: циклические ссылки — структурная ошибка, а не зависание."""
    from rcad.core.netlist import parse
    from rcad.diagnostics import NetlistError

    cyclic = """\
.subckt a x y
X1 x y b
.ends
.subckt b x y
X1 x y a
.ends
X0 1 0 a
.end
"""
    with pytest.raises(NetlistError):
        parse(cyclic)
