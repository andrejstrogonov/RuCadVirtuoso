"""Unit F4/F5: Netlister (автоимена, roundtrip, S4 import/export) и ResultStore CSV."""

from __future__ import annotations

import pytest

from rcad.diagnostics import NetlistError
from rcad.schemas.cell import CellSchema
from rcad.services.netlister import (
    absolute_pins,
    export_netlist,
    import_netlist,
    netlist_for,
    next_net_name,
    parse_value,
    resolve_bindings,
    validate_net_name,
)
from rcad.services.project_service import ProjectService

S1 = {
    "name": "memristor_iv",
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
    service = ProjectService()
    project = service.create(tmp_path / "s1.rcad", name="s1")
    service.add_cell(project, S1)
    return project


def test_absolute_pins_geometry(project) -> None:
    cell = project.cell("memristor_iv")
    xmem = next(i for i in cell.instances if i.name == "Xmem")
    pins = dict(absolute_pins(project, xmem))
    assert pins["A"] == (200, 170)
    assert pins["B"] == (200, 230)


def test_resolve_bindings_s1(project) -> None:
    cell = project.cell("memristor_iv")
    bindings = resolve_bindings(project, cell)
    {(name) for name, net in bindings["V1"]}
    v1 = dict(bindings["V1"])
    assert v1["P"] == "n1"
    assert v1["N"] == "0"
    xmem = dict(bindings["Xmem"])
    assert xmem["A"] == "n1"
    assert xmem["B"] == "n2"
    rprobe = dict(bindings["Rprobe"])
    assert rprobe["P"] == "n2"
    assert rprobe["N"] == "0"


def test_netlist_for_s1_contains_cards(project) -> None:
    text = netlist_for(project, "memristor_iv", tran="1m 2 0 1m")
    assert "V1 n1 0" in text
    assert "Xmem n1 n2" in text
    assert "memristor_yakopcic" in text
    assert ".include" in text
    assert ".tran 1m 2 0 1m" in text
    assert text.rstrip().endswith(".end")


def test_netlist_for_adds_default_params(project) -> None:
    """Частичные params (S1) дополняются дефолтами из библиотеки (Xmem → Vp/Vn/Ap)."""
    text = netlist_for(project, "memristor_iv", tran="1m 2 0 1m")
    xmem_line = next(line for line in text.splitlines() if line.startswith("Xmem"))
    assert "Vp=0.65" in xmem_line
    assert "eta=1" in xmem_line


def test_netlist_for_string_params_kept(project) -> None:
    cell = CellSchema.model_validate({
        "name": "lif",
        "ports": [],
        "instances": [
            {"name": "Iin", "master_cell": "isource", "x": 100, "y": 300,
             "rotation": 0, "mirror": "none", "params": {"PULSE": "100u 0 1n 1p 1p 1m 2m"}},
        ],
        "wires": [],
    })
    project.cells["lif"] = cell
    text = netlist_for(project, "lif")
    iin = next(line for line in text.splitlines() if line.startswith("Iin"))
    assert "100u 0 1n 1p 1p 1m 2m" in iin


def test_export_netlist_no_directive(project) -> None:
    text = export_netlist(project, "memristor_iv")
    assert ".end" in text
    assert ".tran" not in text


def test_next_net_name_no_reuse() -> None:
    assert next_net_name(["n1", "n2"]) == "n3"
    assert next_net_name(["n2"]) == "n1"
    assert next_net_name(["0"]) == "n1"
    assert next_net_name(["n1", "n3"]) == "n2"


def test_validate_net_name_reject_merge() -> None:
    diags = validate_net_name("bad name", [])
    assert any(d.code == "E_NETLIST" for d in diags)
    diags = validate_net_name("n2", ["n1", "n2"])
    codes = {d.code.value for d in diags}
    assert "W_DC_DISCONTINUITY" in codes


def test_parse_value_suffixes() -> None:
    assert parse_value("1k") == 1000
    assert parse_value("2u") == 2e-6
    assert parse_value("1meg") == 1e6
    assert parse_value("100f") == 100e-15
    assert parse_value("10") == 10
    assert parse_value("1.5") == 1.5
    assert parse_value("SIN(0 1 1)") == "SIN(0 1 1)"
    assert parse_value("") == ""


S4 = """\
* S4: кроссбар 4x4 через subckt
.include "models/memristor_yakopcic.lib"
.subckt mem_cell top bot
Xmem top bot memristor_yakopcic a1=0.17 a2=0.17 b=0.05 Vp=0.65 Vn=0.56 Ap=4000 An=4000
+ xp=0.3 xn=0.3 alphap=3 alphan=3 xo=0.1 eta=1
.ends
.subckt crossbar4 c0 c1 c2 c3
.include "crossbar4.dummy"
.ends
V0 c0 0 SIN(0 1 1k)
R0 r0 0 100
X00 c0 r0 mem_cell
.tran 10u 1m 0 10u
.end
"""


def test_import_creates_hierarchy(tmp_path) -> None:
    service = ProjectService()
    project = service.create(tmp_path / "s4.rcad", name="s4")
    import_netlist(project, S4, main="top")
    assert "mem_cell" in project.cell_names
    assert "top" in project.cell_names
    assert project.cell("top").hierarchy_children


def test_hierarchy_exports_back_to_netlist(tmp_path) -> None:
    service = ProjectService()
    project = service.create(tmp_path / "s4.rcad", name="s4")
    import_netlist(project, S4, main="top")
    exported = export_netlist(project, "top")
    assert ".subckt mem_cell" in exported
    assert exported.count("mem_cell") >= 2


def test_import_error_leaves_project_unchanged(tmp_path) -> None:
    service = ProjectService()
    project = service.create(tmp_path / "s4.rcad", name="s4")
    # строка с ошибкой (.subckt без имени)
    with pytest.raises(NetlistError):
        import_netlist(project, ".subckt\n", main="top")
    assert "top" not in project.cell_names


def test_subckt_two_level_roundtrip(tmp_path) -> None:
    text = """\
* two-level
.subckt a1 p n
R1 p n 1k
.ends
.subckt top x y
Xa1 x y a1
.ends
V1 x 0 1
.expand
.end
"""
    service = ProjectService()
    project = service.create(tmp_path / "r.rcad", name="r")
    import_netlist(project, text, main="main")
    project.cell("main")
    top_cell = project.cell("top")
    assert top_cell.hierarchy_children == ["a1"]
    exported = export_netlist(project, "top")
    assert ".subckt a1" in exported
    assert "Xa1" in exported


def test_result_store_csv(tmp_path) -> None:
    from rcad.services.result_store import export_csv

    class FakeResult:
        data = {"time": [0.0, 1.0, 2.0], "I(Xmem)": [1.0, 2.0, 3.0], "@Xmem.x": [0.1, 0.2, 0.3]}

        def names(self) -> list[str]:
            return ["time", "I(Xmem)", "@Xmem.x"]

        def names_minus_time(self) -> list[str]:
            return ["I(Xmem)", "@Xmem.x"]

        def __getitem__(self, name):
            return self.data[name]

    target = export_csv(FakeResult(), ["I(Xmem)", "@Xmem.x"], tmp_path / "s1.csv")
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "time,I(Xmem),@Xmem.x"
    assert len(lines) == 4
