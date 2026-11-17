"""S3: нейристорный LIF-нейрон — нейристор + конденсатор + резистор + импульсный источник.

Приёмка ТЗ п. 3, FR-SCN-S3: в редакторе собирается схема из 4 инстансов и ≥ 3 net,
проект сохраняется, TRAN даёт различимые спайки, частота монотонно растёт с током,
изменённая амплитуда источника воспроизводится после переоткрытия проекта.
"""

from __future__ import annotations

import pytest

from conftest import requires_core

pytestmark = [pytest.mark.tcase("S3"), requires_core]

CELL = "lif_neuron"

SCHEMATIC = {
    "name": CELL,
    "ports": [{"name": "spike", "direction": "out", "x": 400, "y": 200}],
    "instances": [
        {"name": "Iin", "master_cell": "isource", "x": 100, "y": 300,
         "rotation": 0, "mirror": "none", "params": {"PULSE": "100u 0 1n 1p 1p 1m 2m"}},
        {"name": "XN", "master_cell": "neuristor_n1", "x": 200, "y": 200,
         "rotation": 0, "mirror": "none",
         "params": {"R_on": "5k", "R_off": "500k", "V_set": 1.2, "V_hold": 0.4,
                    "t_delay": "10n", "t_relax": "50n", "C_par": "2p"}},
        {"name": "C1", "master_cell": "capacitor", "x": 300, "y": 200,
         "rotation": 0, "mirror": "none", "params": {"C": "1p"}},
        {"name": "R1", "master_cell": "resistor", "x": 300, "y": 300,
         "rotation": 0, "mirror": "none", "params": {"R": "10meg"}},
    ],
    "wires": [
        {"net": "n_spike", "points": [[200, 200], [300, 170]]},
        {"net": "n_in", "points": [[100, 280], [200, 200]]},
        {"net": "0", "points": [[100, 320], [100, 360], [300, 360], [300, 330]]},
    ],
    "junctions": [],
}

CURRENTS = [50e-6, 100e-6, 200e-6]


@pytest.fixture
def project(tmp_path):
    from rcad.services.project_service import ProjectService

    service = ProjectService()
    project = service.create(tmp_path / f"{CELL}.rcad", name=CELL)
    service.add_cell(project, SCHEMATIC)
    service.save(project)
    return service, project


def spike_count(result) -> int:
    v = list(result["V(n_spike)"])
    return sum(1 for a, b in zip(v, v[1:]) if a < 1.0 <= b)


def test_schematic_has_four_instances_and_three_nets(project) -> None:
    from rcad.ui.api import CanvasApi

    state = CanvasApi(project=project[1]).canvas_state(CELL)
    assert len(state["instances"]) == 4
    assert len({wire["net"] for wire in state["wires"]}) >= 3


def test_transient_shows_spikes(project) -> None:
    from rcad.core.analyses import run_analysis
    from rcad.services.netlister import netlist_for

    netlist = netlist_for(project[1], CELL, tran="1n 20u")
    assert spike_count(run_analysis(netlist, ".tran")) >= 3


def test_frequency_grows_with_input_current(project) -> None:
    from rcad.core.analyses import run_analysis
    from rcad.services.netlister import netlist_for
    from rcad.ui.api import CanvasApi

    api = CanvasApi(project=project[1])
    counts = []
    for current in CURRENTS:
        api.set_params(CELL, "Iin", {"PULSE": f"{current} 0 1n 1p 1p 1m 2m"})
        netlist = netlist_for(project[1], CELL, tran="1n 20u")
        counts.append(spike_count(run_analysis(netlist, ".tran")))
    assert counts[0] < counts[1] < counts[2]


def test_amplitude_change_survives_reopen(project) -> None:
    from rcad.ui.api import CanvasApi

    service, proj = project
    CanvasApi(project=proj).set_params(CELL, "Iin", {"PULSE": "200u 0 1n 1p 1p 1m 2m"})
    service.save(proj)
    reopened = service.open(service.path(proj))
    params = CanvasApi(project=reopened).instance_params(CELL, "Iin")
    assert params["PULSE"] == "200u 0 1n 1p 1p 1m 2m"
