"""T3: RLC-контур в AC. Критерии ТЗ п. 12.2 — резонанс ±1 %, добротность ±2 %."""

from __future__ import annotations

import cmath
import math

import pytest

from conftest import requires_core

pytestmark = [pytest.mark.tcase("T3"), requires_core]

NETLIST = """\
* T3: RLC-контур на AC (последовательный)
V1 in 0 DC 0 AC 1
R1 in n1 10
L1 n1 out 1m
C1 out 0 100n
.ac dec 10 1k 10meg
.end
"""

R = 10.0
L = 1e-3
C = 100e-9
F0 = 1.0 / (2.0 * math.pi * math.sqrt(L * C))
Q = math.sqrt(L / C) / R


def transfer(freq: float) -> complex:
    w = 2.0 * math.pi * freq
    return 1.0 / (1.0 + 1j * (w * L - 1.0 / (w * C)) / R)


@pytest.fixture(scope="module")
def ac_result():
    from rcad.core.analyses import run_analysis

    return run_analysis(NETLIST, ".ac")


def test_resonance_frequency(ac_result):
    freqs = ac_result["freq"]
    peak = freqs[max(range(len(freqs)), key=lambda i: abs(ac_result["V(out)"][i]))]
    assert abs(peak - F0) <= 0.01 * F0


def test_quality_factor(ac_result):
    mags = [abs(v) for v in ac_result["V(out)"]]
    peak = max(mags)
    level = peak / math.sqrt(2.0)
    freqs = ac_result["freq"]
    above = [f for f, m in zip(freqs, mags, strict=False) if m >= level]
    bandwidth = above[-1] - above[0]
    assert abs(F0 / bandwidth - Q) <= 0.02 * Q


def test_complex_output_matches_analytic(ac_result):
    for f, v in zip(ac_result["freq"], ac_result["V(out)"], strict=False):
        expected = transfer(f)
        assert cmath.isclose(v, expected, rel_tol=1e-3, abs_tol=1e-9)


def test_dec_sweep_grid(ac_result):
    """FR-AC-002: `dec 10` даёт шаг 10**(k/10)."""
    freqs = list(ac_result["freq"])
    assert len(freqs) == 41
    assert math.isclose(freqs[1] / freqs[0], 10 ** (1 / 10), rel_tol=1e-12)
