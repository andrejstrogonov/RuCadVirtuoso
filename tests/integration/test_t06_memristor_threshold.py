"""T6: порог мемристора — при |V| < Vp на положительной и |V| < Vn на отрицательной
полуволне состояние не меняется. Критерий ТЗ п. 12.2 — Δx < 1e-6."""

from __future__ import annotations

import pytest

from conftest import requires_core

pytestmark = [pytest.mark.tcase("T6"), requires_core]

NETLIST = """\
* T6: подпороговая полуволна
.include "models/memristor_yakopcic.lib"
V1 top 0 SIN(0 {ampl} 1)
Xmem top 0 memristor_yakopcic a1=0.17 a2=0.17 b=0.05 Vp=0.65 Vn=0.56 Ap=4000 An=4000
+ xp=0.3 xn=0.3 alphap=3 alphan=3 xo=0.1 eta=1
.tran 1m 2 0 1m
.end
"""


@pytest.mark.parametrize("amplitude", [0.5, -0.4])
def test_no_state_motion_below_threshold(amplitude: float) -> None:
    from rcad.core.analyses import run_analysis

    result = run_analysis(NETLIST.format(ampl=amplitude), ".tran")
    x = list(result["@Xmem.x"])
    assert max(x) - min(x) < 1e-6


def test_dc_sweep_below_threshold_keeps_state() -> None:
    from rcad.core.analyses import run_analysis

    netlist = """\
* T6: DC-развёртка в пределах порога
.include "models/memristor_yakopcic.lib"
V1 top 0 DC 0
Xmem top 0 memristor_yakopcic a1=0.17 a2=0.17 b=0.05 Vp=0.65 Vn=0.56 Ap=4000 An=4000
+ xp=0.3 xn=0.3 alphap=3 alphan=3 xo=0.1 eta=1
.dc V1 0 0.6 0.01
.end
"""
    result = run_analysis(netlist, ".dc")
    x = list(result["@Xmem.x"])
    assert max(x) - min(x) < 1e-6
