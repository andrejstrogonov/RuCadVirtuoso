"""T1: MNA — делитель R-R на DC. Критерий ТЗ п. 12.2 — точность 1e-12."""

from __future__ import annotations

import pytest

from conftest import requires_core

pytestmark = [pytest.mark.tcase("T1"), requires_core]

NETLIST = """\
* T1: делитель R1-R2 на DC
V1 in 0 DC 10
R1 in mid 1k
R2 mid 0 3k
.op
.end
"""

V_IN = 10.0
R1 = 1e3
R2 = 3e3


def test_divider_node_voltage():
    from rcad.core.analyses import run_analysis

    result = run_analysis(NETLIST, ".op")
    expected = V_IN * R2 / (R1 + R2)
    assert abs(result.node("mid") - expected) <= 1e-12


def test_divider_branch_currents():
    from rcad.core.analyses import run_analysis

    result = run_analysis(NETLIST, ".op")
    expected = V_IN / (R1 + R2)
    assert abs(result.branch("V1") - expected) <= 1e-12
    assert abs(result.element("R1", "i") - expected) <= 1e-12
    assert abs(result.element("R2", "i") - expected) <= 1e-12
