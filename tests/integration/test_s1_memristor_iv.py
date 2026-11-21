"""S1: ВАХ мемристора — «источник — мемристор — земля», TRAN, петля I(V) и траектория x(t).

Приёмка ТЗ п. 3, FR-SCN-S1: схема из 3 проводящих элементов, параметры Yakopcic
принимаются панелью свойств, проект сохраняется в `.rcad` и переоткрывается,
TRAN доступен, кривые `i(Xmem)` и `@Xmem.x` экспортируются в CSV.
"""

from __future__ import annotations

import json

import pytest

from conftest import requires_core, requires_services

pytestmark = [pytest.mark.tcase("S1"), requires_core, requires_services]

CELL = "memristor_iv"

SCHEMATIC = {
    "name": CELL,
    "ports": [],
    "instances": [
        {"name": "V1", "master_cell": "vsource", "x": 100, "y": 200,
         "rotation": 0, "mirror": "none", "params": {"DC": 0, "SIN": "0 1 1"}},
        {"name": "Xmem", "master_cell": "memristor_m1", "x": 200, "y": 200,
         "rotation": 0, "mirror": "none",
         "params": {"a1": 0.17, "a2": 0.17, "b": 0.05, "Vp": 0.65, "Vn": 0.56}},
        {"name": "Rprobe", "master_cell": "resistor", "x": 300, "y": 200,
         "rotation": 0, "mirror": "none", "params": {"R": 1e-3}},
    ],
    "wires": [
        {"net": "n1", "points": [[100, 180], [200, 170]]},
        {"net": "n2", "points": [[200, 230], [300, 200]]},
        {"net": "0", "points": [[300, 200], [300, 280], [100, 280], [100, 220]]},
    ],
    "junctions": [],
}


@pytest.fixture
def project(tmp_path):
    from rcad.services.project_service import ProjectService

    service = ProjectService()
    project = service.create(tmp_path / f"{CELL}.rcad", name=CELL)
    service.add_cell(project, SCHEMATIC)
    return service, project


def test_scenario_builds_three_element_schematic(project) -> None:
    from rcad.ui.api import CanvasApi

    api = CanvasApi(project=project[1])
    state = api.canvas_state(CELL)
    assert len(state["instances"]) == 3
    assert {wire["net"] for wire in state["wires"]} == {"n1", "n2", "0"}


def test_yakopcic_parameters_accepted(project) -> None:
    from rcad.ui.api import CanvasApi

    api = CanvasApi(project=project[1])
    api.set_params(CELL, "Xmem", {"a1": 0.17, "a2": 0.17, "b": 0.05, "Vp": 0.65, "Vn": 0.56})
    assert api.instance_params(CELL, "Xmem")["Vp"] == 0.65


def test_project_saved_and_reopened(project) -> None:
    service, proj = project
    service.save(proj)
    cells = json.loads((service.path(proj) / "cells" / f"{CELL}.json").read_text("utf-8"))
    reopened = service.open(service.path(proj))
    assert json.loads(service.path(proj).joinpath("cells", f"{CELL}.json").read_text("utf-8")) == cells
    assert reopened.name == proj.name


def test_transient_gives_loop_and_state_trace(project) -> None:
    from rcad.core.analyses import run_analysis

    from rcad.services.netlister import netlist_for

    netlist = netlist_for(project[1], CELL, tran="1m 2 0 1m")
    result = run_analysis(netlist, ".tran")
    assert len(result["time"]) == 2001
    assert "@Xmem.x" in result.names()
    assert "I(Xmem)" in result.names()


def test_both_series_are_exported_to_csv(project, tmp_path) -> None:
    from rcad.core.analyses import run_analysis

    from rcad.services.netlister import netlist_for
    from rcad.services.result_store import export_csv

    netlist = netlist_for(project[1], CELL, tran="1m 2 0 1m")
    result = run_analysis(netlist, ".tran")
    target = export_csv(result, ["I(Xmem)", "@Xmem.x"], tmp_path / "s1.csv")
    header = target.read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == ["time", "I(Xmem)", "@Xmem.x"]
    assert len(target.read_text(encoding="utf-8").splitlines()) == 2002
