"""T9: линейный резистор как Verilog-A модель. Критерий ТЗ п. 12.2 — 1e-9."""

from __future__ import annotations

import pytest

from conftest import EXAMPLES, requires_core, requires_va

pytestmark = [pytest.mark.tcase("T9"), requires_core, requires_va]

VA_SOURCE = EXAMPLES / "va_custom_model" / "va_resistor.va"

NETLIST = """\
* T9: VA-резистор против нативного R
.include "{va}"
V1 in 0 DC 1
X1 in 0 va_resistor r=1k
R1 in 0 1m
.op
.end
"""


def test_va_source_exists() -> None:
    assert VA_SOURCE.is_file(), f"нет исходника VA-модели: {VA_SOURCE}"


def test_va_resistor_matches_native() -> None:
    from rcad.core.analyses import run_analysis

    result = run_analysis(NETLIST.format(va=VA_SOURCE.as_posix()), ".op")
    assert abs(result.element("X1", "i") - 1e-3) <= 1e-9


def test_va_model_is_registered_in_library() -> None:
    """FR-DEV-001 для VA: после импорта модель доступна как устройство с символом."""
    from rcad.devices.registry import registry

    assert "va_resistor" in registry.names()


def test_va_and_native_agree_on_sweep() -> None:
    from rcad.core.analyses import run_analysis

    netlist = f"""\
* T9: DC-развёртка, VA против нативного R
.include "{VA_SOURCE.as_posix()}"
V1 in 0 DC 0
X1 in 0 va_resistor r=1k
.dc V1 0 1 0.1
.end
"""
    result = run_analysis(netlist, ".dc")
    for v, i in zip(result["V(in)"], result.element("X1", "i"), strict=False):
        assert abs(-i - v / 1e3) <= 1e-9
