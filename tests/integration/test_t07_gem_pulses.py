"""T7: мемтранзистор GEM — 10 импульсов vgs дают монотонные ступени ids, w в границах."""

from __future__ import annotations

import pytest

from conftest import requires_core

pytestmark = [pytest.mark.tcase("T7"), requires_core]

W_ON = 1.0
W_OFF = 0.0
PULSES = 10

NETLIST = """\
* T7: 10 импульсов затвора мемтранзистора GEM
.include "models/memtransistor_gem.lib"
VD d 0 DC 0.5
VG g 0 PULSE(0 2 10n 1n 1n 20n 100n)
XMT d g 0 memtransistor_gem w_on=1 w_off=0 k_on=1e-4 k_off=1e-4 alpha_on=4 alpha_off=4
+ s_on=2 s_off=2 beta_on=1e-3 beta_off=1e-3 v_on=1 v_off=-1 r_on=1k r_off=100k
+ mu=1e-3 w_init=0.5
.tran 1n 1u
.end
"""


@pytest.fixture(scope="module")
def tran():
    from rcad.core.analyses import run_analysis

    return run_analysis(NETLIST, ".tran")


def test_state_stays_within_window(tran) -> None:
    for w in tran["@XMT.w"]:
        assert W_OFF - 1e-12 <= w <= W_ON + 1e-12


def test_state_start_is_w_init(tran) -> None:
    assert abs(tran["@XMT.w"][0] - 0.5) <= 1e-12


def test_ten_pulses_give_monotonic_steps(tran) -> None:
    """Значения w в конце каждого импульса образуют монотонную ступенчатую последовательность."""
    times, w = tran["time"], tran["@XMT.w"]
    ends = [10e-9 + n * 100e-9 for n in range(PULSES)]
    samples = [w[min(range(len(times)), key=lambda i: abs(times[i] - t))] for t in ends]
    deltas = [b - a for a, b in zip(samples, samples[1:])]
    assert len(set(round(d, 12) for d in deltas)) > 1, "нет различимых ступеней"
    assert all(d >= -1e-9 for d in deltas) or all(d <= 1e-9 for d in deltas)


def test_ids_steps_follow_state(tran) -> None:
    ids, w = tran["I(VD)"], tran["@XMT.w"]
    ends = [10e-9 + n * 100e-9 for n in range(PULSES)]
    grid = list(zip(tran["time"], w, ids))
    samples = [min(grid, key=lambda row: abs(row[0] - t)) for t in ends]
    for (_, w_prev, i_prev), (_, w_next, i_next) in zip(samples, samples[1:]):
        assert (w_next - w_prev) * (i_next - i_prev) >= -1e-15


def test_gate_current_is_zero(tran) -> None:
    """FR-MT-011: терминал G не потребляет постоянного тока."""
    for i in tran["I(VG)"]:
        assert abs(i) <= 1e-12


def test_no_state_change_between_thresholds() -> None:
    """FR-MT-009: при v_off <= vgs <= v_on состояние не меняется."""
    from rcad.core.analyses import run_analysis

    netlist = NETLIST.replace("PULSE(0 2 10n 1n 1n 20n 100n)", "DC 0.5")
    result = run_analysis(netlist, ".tran")
    w = list(result["@XMT.w"])
    assert max(w) - min(w) < 1e-6
