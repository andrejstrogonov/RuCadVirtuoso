"""S2: импорт собственной Verilog-A модели — компиляция, символ, DC-развёртка.

Приёмка ТЗ п. 3, FR-SCN-S2. В качестве пользовательской модели используется
VTEAM (`examples/va_custom_model/vteam.va`, FR-MEM3-003).
"""

from __future__ import annotations

import pytest

from conftest import EXAMPLES, requires_core, requires_va

pytestmark = [pytest.mark.tcase("S2"), requires_core, requires_va]

VA_SOURCE = EXAMPLES / "va_custom_model" / "vteam.va"


@pytest.fixture
def imported(tmp_path):
    from rcad.veriloga import VaImportService

    from rcad.services.project_service import ProjectService

    service = ProjectService()
    project = service.create(tmp_path / "s2.rcad", name="s2")
    outcome = VaImportService(project_dir=service.path(project)).import_file(VA_SOURCE)
    return service, project, outcome


def test_import_reports_success(imported) -> None:
    _, _, outcome = imported
    assert outcome.ok is True
    assert outcome.diagnostics == [] or all(d.severity != "error" for d in outcome.diagnostics)


def test_source_is_copied_to_veriloga(imported) -> None:
    service, project, _ = imported
    stored = service.path(project) / "veriloga" / VA_SOURCE.name
    assert stored.is_file()
    assert stored.read_bytes() == VA_SOURCE.read_bytes()


def test_symbol_with_model_ports_appears(imported) -> None:
    from rcad.devices.registry import registry

    _, project, outcome = imported
    symbol = registry.symbol_for(outcome.model_name)
    assert symbol is not None
    assert [pin.name for pin in symbol.pins] == ["p", "n"]
    assert project.libraries


def test_parameters_are_validated_against_range(imported) -> None:
    from rcad.diagnostics import ParameterRangeError

    _, project, outcome = imported
    from rcad.ui.api import CanvasApi

    api = CanvasApi(project=project)
    api.place("vdut", outcome.model_name, x=100, y=100)
    api.set_params("s2", "vdut", {"von": 0.5})
    with pytest.raises(ParameterRangeError):
        api.set_params("s2", "vdut", {"von": -1.0})


def test_dc_sweep_runs_on_imported_model(imported) -> None:
    from rcad.core.analyses import run_analysis

    from rcad.ui.api import CanvasApi

    _, project, outcome = imported
    api = CanvasApi(project=project)
    api.place("vdut", outcome.model_name, x=100, y=100)
    api.place("V1", "vsource", x=100, y=300)
    netlist = api.build_netlist("s2", dc="V1 0 1 0.01")
    result = run_analysis(netlist, ".dc")
    assert len(result["V(1)"]) == 101
    assert result.names_minus_time()
