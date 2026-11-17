"""T13: кроссбар 16×16 мемристоров — 10 000 точек TRAN, ≤ 120 с, SV без разрывов.

Критерии ТЗ п. 12.2 и п. 13 (эталонная машина: 8 ядер, 16 ГБ, SSD).
Эталонный netlist версионируется в `tests/perf/` и не меняется без пересмотра
базовых значений (NFR-PERF).
"""

from __future__ import annotations

import math
import time

import pytest

from conftest import requires_core

pytestmark = [pytest.mark.tcase("T13"), pytest.mark.perf, requires_core]

ROWS = 16
COLS = 16
TIME_BUDGET_S = 120.0
POINTS = 10_000


def build_netlist() -> str:
    lines = [
        "* T13: кроссбар 16x16 мемристоров Yakopcic",
        '.include "models/memristor_yakopcic.lib"',
    ]
    for col in range(COLS):
        lines.append(
            f"V{col} col{col} 0 SIN(0 1 1k 0 0 {90 + col * 5})"
        )
    for row in range(ROWS):
        for col in range(COLS):
            lines.append(
                f"X{row}_{col} col{col} row{row} memristor_yakopcic "
                "a1=0.17 a2=0.17 b=0.05 Vp=0.65 Vn=0.56 Ap=4000 An=4000 "
                "xp=0.3 xn=0.3 alphap=3 alphan=3 xo=0.1 eta=1"
            )
    for row in range(ROWS):
        lines.append(f"R{row} row{row} 0 100")
    lines.append(".tran 1u 10m 0 1u")
    lines.append(".end")
    return "\n".join(lines) + "\n"


NETLIST = build_netlist()


def test_all_devices_are_instantiated() -> None:
    assert NETLIST.count("memristor_yakopcic a1=") == ROWS * COLS


def test_transient_within_time_budget() -> None:
    from rcad.core.analyses import run_analysis

    started = time.perf_counter()
    result = run_analysis(NETLIST, ".tran")
    elapsed = time.perf_counter() - started
    assert len(result["time"]) == POINTS
    assert elapsed <= TIME_BUDGET_S


def test_state_variables_are_continuous() -> None:
    """NFR-DEV-003: без разрывов в SV, значения в [0, 1]."""
    from rcad.core.analyses import run_analysis

    result = run_analysis(NETLIST, ".tran")
    for row in range(ROWS):
        for col in range(COLS):
            series = result[f"@X{row}_{col}.x"]
            assert all(math.isfinite(x) for x in series)
            assert all(-1e-12 <= x <= 1.0 + 1e-12 for x in series)
            assert max(abs(b - a) for a, b in zip(series, series[1:])) < 0.1
