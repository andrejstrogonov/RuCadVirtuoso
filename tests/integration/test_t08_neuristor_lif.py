"""T8: нейристор N1/N2 в LIF-нейроне — спайки, частота монотонно растёт с током.

Критерий ТЗ п. 12.2: генерация спайков и монотонная зависимость f(I_in).
Проверяется для обеих моделей нейристора (FR-NR-001).
"""

from __future__ import annotations

import pytest

from conftest import requires_core

pytestmark = [pytest.mark.tcase("T8"), requires_core]

MODELS = {
    "n1": """\
.include "models/neuristor_n1.lib"
XN in 0 neuristor_n1 R_on=5k R_off=500k V_set=1.2 V_hold=0.4 t_delay=10n t_relax=50n C_par=2p
""",
    "n2": """\
.include "models/neuristor_n2.lib"
XN in 0 neuristor_n2 R_on=5k R_off=500k V_set=1.2 V_hold=0.4 tau_set=1n tau_relax=5n
+ s_init=0 sigma=1
""",
}

NETLIST = """\
* T8: LIF-нейрон на нейристоре
{model}
C1 in 0 1p
Iin 0 in PULSE({current} 0 1n 1p 1p 1m 2m)
.tran 1n 20u
.end
"""

CURRENTS = ["50u", "100u", "200u"]


def counts(model: str, current: str) -> tuple[int, list[float]]:
    from rcad.core.analyses import run_analysis

    result = run_analysis(NETLIST.format(model=MODELS[model], current=current), ".tran")
    v = list(result["V(in)"])
    spikes = [i for i in range(1, len(v)) if v[i - 1] < 1.0 <= v[i]]
    return len(spikes), spikes


@pytest.mark.parametrize("model", sorted(MODELS))
def test_spikes_are_generated(model: str) -> None:
    count, _ = counts(model, "100u")
    assert count >= 3


@pytest.mark.parametrize("model", sorted(MODELS))
def test_spike_rate_grows_with_input_current(model: str) -> None:
    rates = [counts(model, current)[0] for current in CURRENTS]
    assert rates[0] < rates[1] < rates[2], f"{model}: {rates}"


@pytest.mark.parametrize("model", sorted(MODELS))
def test_no_chattering_on_switching_edge(model: str) -> None:
    """FR-NR-004: переключение за один шаг, без многократных рестартов интегратора."""
    from rcad.core.analyses import run_analysis

    result = run_analysis(NETLIST.format(model=MODELS[model], current="100u"), ".tran")
    assert result.report.get("step_rejections", 0) == 0
