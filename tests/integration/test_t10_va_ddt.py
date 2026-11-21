"""T10: Verilog-A модель с `ddt` (нелинейная ёмкость). Критерий ТЗ п. 12.2 — 1e-3
против нативной RC-цепи."""

from __future__ import annotations

import math

import pytest

from conftest import EXAMPLES, requires_core, requires_va

pytestmark = [pytest.mark.tcase("T10"), requires_core, requires_va]

VA_SOURCE = EXAMPLES / "va_custom_model" / "va_nl_cap.va"

NL_NETLIST = """\
* T10: нелинейная ёмкость q = c0·v + c1·v² через ddt
.include "{va}"
V1 in 0 PWL(0 0 1m 1)
X1 in 0 va_nl_cap c0=1n c1=2n
R1 in 0 1meg
.tran 1u 1m
.end
"""

RC_NETLIST = """\
* T10: эталонная линейная RC-цепь
V1 in 0 PWL(0 0 1m 1)
R1 in 0 1meg
C1 in 0 1n
.tran 1u 1m
.end
"""


def test_va_ddt_source_exists() -> None:
    assert VA_SOURCE.is_file(), f"нет исходника VA-модели: {VA_SOURCE}"


def test_charge_equation_matches_analytic_c0_term() -> None:
    """На пологом фронте ёмкость близка к c0, ток совпадает с аналитикой c0·dv/dt."""
    from rcad.core.analyses import run_analysis

    result = run_analysis(NL_NETLIST.format(va=VA_SOURCE.as_posix()), ".tran")
    times, v = result["time"], result["V(in)"]
    for idx in range(2, len(times) - 2):
        dv_dt = (v[idx + 1] - v[idx - 1]) / (times[idx + 1] - times[idx - 1])
        c = 1e-9 + 2.0 * 2e-9 * v[idx]
        expected = c * dv_dt
        assert math.isclose(-result.element("X1", "i")[idx], expected, rel_tol=1e-3, abs_tol=1e-9)


def test_nonlinear_cap_differs_from_linear_rc() -> None:
    from rcad.core.analyses import run_analysis

    nl = run_analysis(NL_NETLIST.format(va=VA_SOURCE.as_posix()), ".tran")
    linear = run_analysis(RC_NETLIST, ".tran")
    final_nl, final_linear = nl["V(in)"][-1], linear["V(in)"][-1]
    assert abs(final_nl - final_linear) > 1e-3
