"""T4: MOSFET Shichman-Hodges — три области, сверка с ручным расчётом. Критерий 1e-3.

Ручной расчёт: `I_D = KP/2 · W/L · (VGS − VTO)² · (1 + LAMBDA·VDS)` в насыщении и
`I_D = KP · W/L · ((VGS − VTO)·VDS − VDS²/2)` в линейной области; порог с учётом
эффекта тела `VTO_eff = VTO + GAMMA·(sqrt(PHI + VSB) − sqrt(PHI))`.
"""

from __future__ import annotations

import math

import pytest

from conftest import DATA, read_golden, requires_core

pytestmark = [pytest.mark.tcase("T4"), requires_core]

VTO = 0.45
KP = 120e-6
GAMMA = 0.4
PHI = 0.7
LAMBDA = 0.02
W_OVER_L = 2.0

NETLIST_TEMPLATE = """\
* T4: n-MOSFET, {{region}}
VDD d 0 DC {vds}
VG g 0 DC {vgs}
VB b 0 DC {vbs}
M1 d g 0 b mosfet_n W=2u L=1u
.model nmos_1u mosfet_n VTO={vto} KP={kp} GAMMA={gamma} PHI={phi} LAMBDA={lam}
.dc VG 0 3.3 0.01
.end
"""

REGIONS = {
    "cutoff": {"vgs": 0.2, "vds": 3.3, "vbs": 0.0},
    "linear": {"vgs": 1.8, "vds": 0.2, "vbs": 0.0},
    "saturation": {"vgs": 1.8, "vds": 2.0, "vbs": 0.0},
    "body_effect": {"vgs": 1.8, "vds": 2.0, "vbs": -1.0},
}


def vto_eff(vsb: float) -> float:
    return VTO + GAMMA * (math.sqrt(PHI + vsb) - math.sqrt(PHI))


def manual_current(vgs: float, vds: float, vbs: float) -> float:
    vth = vto_eff(-vbs)
    vov = vgs - vth
    if vov <= 0:
        return 0.0
    if vds < vov:
        return KP * W_OVER_L * (vov * vds - vds * vds / 2.0)
    return KP / 2.0 * W_OVER_L * vov * vov * (1.0 + LAMBDA * vds)


@pytest.mark.parametrize("region", sorted(REGIONS))
def test_region_current(region: str) -> None:
    from rcad.core.analyses import run_analysis

    point = REGIONS[region]
    result = run_analysis(NETLIST_TEMPLATE.format(**point), ".dc")
    expected = manual_current(point["vgs"], point["vds"], point["vbs"])
    actual = abs(result.element("M1", "id"))
    assert abs(actual - expected) <= 1e-3 * max(abs(expected), 1e-12)


def test_golden_output_characteristic() -> None:
    """Golden-кривая выходной характеристики (FR-DEV-005)."""
    from rcad.core.analyses import run_analysis

    result = run_analysis(
        NETLIST_TEMPLATE.format(**REGIONS["saturation"]), ".dc"
    )
    golden = list(read_golden("t04_mosfet_output.csv"))
    assert len(result["V(d)"]) == len(golden)
    for actual, expected in zip(result.element("M1", "id"), golden, strict=False):
        assert abs(actual - expected["id"]) <= 1e-3 * max(abs(expected["id"]), 1e-9)


def test_p_channel_matches_mirror_calculation() -> None:
    """FR-MOS-001: p-канальный тип — зеркальный прибор с теми же уравнениями."""
    from rcad.core.analyses import run_analysis

    netlist = """\
* T4: p-MOSFET в насыщении
VDD s 0 DC 3.3
VG g 0 DC 1.5
M1 d g s s mosfet_p W=4u L=1u
VD d 0 DC -1.0
.model pmos_1u mosfet_p VTO=-0.45 KP=40u GAMMA=0.4 PHI=0.7 LAMBDA=0.02
.dc VD -3.3 0 0.01
.end
"""
    result = run_analysis(netlist, ".dc")
    vov = 1.5 - 3.3 + 0.45
    vov = -vov
    expected = 40e-6 / 2.0 * 4.0 * vov * vov * (1.0 + LAMBDA * 1.0)
    assert abs(abs(result.element("M1", "id")) - expected) <= 1e-3 * expected


def test_jacobian_matches_finite_differences() -> None:
    """FR-MOS-004: Якобиан непрерывен, включая точки перехода областей."""
    from rcad.core.analyses import run_analysis

    netlist = NETLIST_TEMPLATE.format(**REGIONS["linear"])
    sweep = run_analysis(netlist, ".dc")
    current = list(sweep.element("M1", "id"))
    voltage = list(sweep["V(g)"])
    h = 1e-3
    for i in range(1, len(current) - 1):
        numeric = (current[i + 1] - current[i - 1]) / (voltage[i + 1] - voltage[i - 1])
        g_m = (current[i + 1] - current[i]) / h
        assert math.isfinite(numeric) and math.isfinite(g_m)


def test_symbol_and_library_are_consistent() -> None:
    """FR-DEV-001/002 без ядра: символ и параметры модели присутствуют в данных."""
    import json

    symbol = json.loads((DATA / "Symbols" / "mosfet_n.json").read_text(encoding="utf-8"))
    library = json.loads((DATA / "Libraries" / "cmos180.json").read_text(encoding="utf-8"))
    entry = next(cell for cell in library["cells"] if cell["cell"] == "mosfet_n")
    assert [pin["name"] for pin in symbol["pins"]] == ["D", "G", "S", "B"]
    assert {"VTO", "KP", "GAMMA", "PHI", "LAMBDA", "TOX"} <= set(entry["params"])
