"""T14: точка разрыва источника PULSE — интегратор попадает точно во фронт.

Критерий ТЗ п. 12.2: шаг ≤ 1e-12 с от точки фронта; в ряду результатов есть точка,
равная моменту фронта (FR-TRAN-004).
"""

from __future__ import annotations

import pytest

from conftest import requires_core

pytestmark = [pytest.mark.tcase("T14"), requires_core]

NETLIST = """\
* T14: фронт PULSE внутри крупного шага
V1 in 0 PULSE(0 1 1m 1n 1n 1m 2m)
R1 in out 1k
C1 out 0 1n
.tran 100u 5m
.end
"""

RISE = 1e-3
FALL = 2e-3


@pytest.fixture(scope="module")
def tran():
    from rcad.core.analyses import run_analysis

    return run_analysis(NETLIST, ".tran")


@pytest.mark.parametrize("breakpoint", [RISE, FALL])
def test_breakpoint_is_in_result_grid(tran, breakpoint: float) -> None:
    assert any(abs(t - breakpoint) <= 1e-12 for t in tran["time"])


@pytest.mark.parametrize("breakpoint", [RISE, FALL])
def test_step_does_not_jump_over_breakpoint(tran, breakpoint: float) -> None:
    times = list(tran["time"])
    for a, b in zip(times, times[1:]):
        assert not (a < breakpoint - 1e-12 and b > breakpoint + 1e-12), (
            f"шаг [{a}, {b}] перепрыгнул фронт {breakpoint}"
        )


def test_rise_front_is_reproduced(tran) -> None:
    times, v = tran["time"], tran["V(in)"]
    rising = [(t, x) for t, x in zip(times, v) if RISE <= t <= RISE + 1e-9]
    assert rising
    assert rising[0][1] <= 1e-3
    assert rising[-1][1] >= 0.99
