"""T5: мемристор Yakopcic (M1) — петля I-V на SIN 1 Гц, SV x ∈ [0, 1].

Критерий ТЗ п. 12.2: монотонность x на полупериоде, качественная форма петли,
пики токов в пределах 5 % от эталона (golden-кривая).
"""

from __future__ import annotations

import math

import pytest

from conftest import close, read_golden, requires_core

pytestmark = [pytest.mark.tcase("T5"), requires_core]

NETLIST = """\
* T5: петля гистерезиса мемристора Yakopcic
.include "models/memristor_yakopcic.lib"
V1 top 0 SIN(0 1 1)
Xmem top 0 memristor_yakopcic a1=0.17 a2=0.17 b=0.05 Vp=0.65 Vn=0.56 Ap=4000 An=4000
+ xp=0.3 xn=0.3 alphap=3 alphan=3 xo=0.1 eta=1
.tran 1m 2 0 1m
.end
"""


@pytest.fixture(scope="module")
def tran():
    from rcad.core.analyses import run_analysis

    return run_analysis(NETLIST, ".tran")


def test_state_within_bounds(tran) -> None:
    for x in tran["@Xmem.x"]:
        assert -1e-12 <= x <= 1.0 + 1e-12


def test_state_monotonic_on_first_half_period(tran) -> None:
    """При eta=1 и положительной полуволне x растёт монотонно до окна xp."""
    times, x = tran["time"], tran["@Xmem.x"]
    rising = [(t, v) for t, v in zip(times, x, strict=False) if t <= 0.5]
    assert all(b >= a - 1e-9 for (_, a), (_, b) in zip(rising, rising[1:], strict=False))
    assert rising[-1][1] > rising[0][1]


def test_pinch_and_hysteresis_loop(tran) -> None:
    """Петля замкнута в нуле и различает ветви прямого и обратного хода."""
    v, i = tran["V(top)"], tran["I(V1)"]
    zero_crossings = [idx for idx in range(1, len(v)) if v[idx - 1] * v[idx] < 0]
    assert zero_crossings, "сигнал не меняет знак — петля не образуется"
    forward = [i[idx] for idx in zero_crossings[0::2]]
    backward = [i[idx] for idx in zero_crossings[1::2]]
    assert forward and backward
    assert abs(sum(forward) / len(forward)) > abs(sum(backward) / len(backward))


@pytest.mark.parametrize("threshold", [0.05])
def test_current_peaks_against_golden(tran, threshold: float) -> None:
    golden = list(read_golden("t05_memristor_iv.csv"))
    assert len(golden) == len(tran["time"])
    peak_actual = max(abs(i) for i in tran["I(V1)"])
    peak_expected = max(abs(row["i"]) for row in golden)
    assert abs(peak_actual - peak_expected) <= threshold * peak_expected


def test_state_trace_against_golden(tran) -> None:
    for x, row in zip(tran["@Xmem.x"], read_golden("t05_memristor_iv.csv"), strict=False):
        assert close(x, row["x"], reltol=1e-2, abstol=1e-6)


def test_current_equation_by_sign(tran) -> None:
    """FR-MEM-006: I = a1·x·sinh(b·V) при V ≥ 0 и a2·x·sinh(b·V) при V < 0."""
    a1 = a2 = 0.17
    b = 0.05
    for v, x, i in zip(tran["V(top)"], tran["@Xmem.x"], tran["I(V1)"], strict=False):
        amp = a1 if v >= 0 else a2
        expected = amp * x * math.sinh(b * v)
        assert abs(-i - expected) <= 1e-3 * max(abs(expected), 1e-12)
