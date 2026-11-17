"""T2: заряд RC через TRAN. Критерий ТЗ п. 12.2 — совпадение с аналитикой 1e-3."""

from __future__ import annotations

import math

import pytest

from conftest import requires_core

pytestmark = [pytest.mark.tcase("T2"), requires_core]

NETLIST = """\
* T2: заряд ёмкости через резистор
V1 in 0 DC 1
R1 in out 1k
C1 out 0 1n
.ic V(out)=0
.tran 1u 10u
.end
"""

V_IN = 1.0
RC = 1e3 * 1e-9


def analytic(t: float) -> float:
    return V_IN * (1.0 - math.exp(-t / RC))


def test_rc_charge_matches_analytic():
    from rcad.core.analyses import run_analysis

    result = run_analysis(NETLIST, ".tran")
    for t, v in zip(result["time"], result["V(out)"]):
        assert abs(v - analytic(t)) <= 1e-3 * max(abs(analytic(t)), 1e-3)


def test_first_point_is_zero_and_monotonic():
    from rcad.core.analyses import run_analysis

    result = run_analysis(NETLIST, ".tran")
    values = list(result["V(out)"])
    assert abs(values[0]) <= 1e-12
    assert all(b >= a - 1e-12 for a, b in zip(values, values[1:]))


def test_no_step_exceeds_default_maxstep():
    """FR-TRAN-005: без `.options maxstep` шаг не больше (tstop - tstart) / 100."""
    from rcad.core.analyses import run_analysis

    result = run_analysis(NETLIST, ".tran")
    steps = [b - a for a, b in zip(result["time"], result["time"][1:])]
    assert steps and max(steps) <= 10e-6 / 100 + 1e-18
