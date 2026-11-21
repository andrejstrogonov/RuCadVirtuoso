"""Unit F2/F3/F6: ProjectService, ModelManager, CanvasApi (FR-PRJ-002/004/009/011/012, FR-PRS, FR-PRP)."""

from __future__ import annotations

import json

import pytest

from rcad.diagnostics import ProjectError, RcadError
from rcad.services.project_service import FORMAT_VERSION, ProjectService
from rcad.ui.api import CanvasApi

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
def service(tmp_path) -> ProjectService:
    return ProjectService()


def test_create_makes_dir_and_project_json(service, tmp_path) -> None:
    project = service.create(tmp_path / "proj.rcad", name="proj")
    assert service.path(project).is_dir()
    project_json = json.loads((service.path(project) / "project.json").read_text("utf-8"))
    assert project_json["name"] == "proj"
    assert project_json["format_version"] == FORMAT_VERSION
    assert project_json["libraries"]


def test_create_resolves_bare_path(service, tmp_path) -> None:
    project = service.create(tmp_path / "proj.rcad", name="proj")
    assert service.path(project).suffix == ".rcad"
    assert service.path(project).name == "proj.rcad"


def test_add_cell_and_save_reopen(service, tmp_path) -> None:
    project = service.create(tmp_path / "s1.rcad", name="s1")
    service.add_cell(project, S1)
    service.save(project)
    opened = service.open(service.path(project))
    assert opened.name == "s1"
    assert "memristor_iv" in opened.cell_names
    cell = opened.cell("memristor_iv")
    assert [i.name for i in cell.instances] == ["V1", "Xmem", "Rprobe"]


def test_save_reopen_json_identical(service, tmp_path) -> None:
    project = service.create(tmp_path / "s1.rcad", name="s1")
    service.add_cell(project, S1)
    service.save(project)
    cells = json.loads((service.path(project) / "cells" / "memristor_iv.json").read_text("utf-8"))
    service.open(service.path(project))
    reopened_json = json.loads(
        (service.path(project) / "cells" / "memristor_iv.json").read_text("utf-8")
    )
    assert reopened_json == cells


def test_double_save_is_idempotent_bytes(service, tmp_path) -> None:
    """NFR-TST-002: повторный save неизменённого проекта не меняет файлы."""
    project = service.create(tmp_path / "s1.rcad", name="s1")
    service.add_cell(project, S1)
    service.save(project)
    first = (service.path(project) / "cells" / "memristor_iv.json").read_bytes()
    service.save(project)
    second = (service.path(project) / "cells" / "memristor_iv.json").read_bytes()
    assert first == second


def test_open_missing_dir_raises(service, tmp_path) -> None:
    with pytest.raises(ProjectError):
        service.open(tmp_path / "nope.rcad")


def test_open_future_version_rejected_without_write(service, tmp_path) -> None:
    project = service.create(tmp_path / "v9.rcad", name="v9")
    project_json = service.path(project) / "project.json"
    data = json.loads(project_json.read_text("utf-8"))
    data["format_version"] = FORMAT_VERSION + 5
    project_json.write_text(json.dumps(data), encoding="utf-8")
    before = project_json.read_bytes()
    with pytest.raises(ProjectError):
        service.open(service.path(project))
    assert project_json.read_bytes() == before  # файл не изменён (FR-PRJ-004)


def test_open_lower_version_warns(service, tmp_path) -> None:
    project = service.create(tmp_path / "v0.rcad", name="v0")
    project_json = service.path(project) / "project.json"
    data = json.loads(project_json.read_text("utf-8"))
    data["format_version"] = 0
    project_json.write_text(json.dumps(data), encoding="utf-8")
    opened = service.open(service.path(project), confirm_upgrade=True)
    codes = {d.code.value for d in opened.diagnostics}
    assert "W_PROJECT_VERSION_OLD" in codes or any(d.code == "W_PROJECT_VERSION_OLD" for d in opened.diagnostics)


def test_open_corrupt_cell_partial(service, tmp_path) -> None:
    project = service.create(tmp_path / "s1.rcad", name="s1")
    service.add_cell(project, S1)
    service.add_cell(project, dict(S1, name="other"))
    service.save(project)
    (service.path(project) / "cells" / "other.json").write_text("{broken", encoding="utf-8")
    opened = service.open(service.path(project))
    assert "memristor_iv" in opened.cell_names  # остальные ячейки открыты (FR-PRJ-012)
    assert "other" not in opened.cell_names
    assert any(d.code == "E_PROJECT_CORRUPT" for d in opened.diagnostics)


def test_open_corrupt_project_json_raises(service, tmp_path) -> None:
    project = service.create(tmp_path / "s1.rcad", name="s1")
    (service.path(project) / "project.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(RcadError):
        service.open(service.path(project))


def test_no_absolute_paths_saved(service, tmp_path) -> None:
    """FR-PRJ-011: сохранение не содержит абсолютных путей машины."""
    project = service.create(tmp_path / "s1.rcad", name="s1")
    service.add_cell(project, S1)
    service.save(project)
    text = "\n".join(
        p.read_text("utf-8")
        for p in list((service.path(project) / "cells").glob("*.json"))
    )
    text += (service.path(project) / "project.json").read_text("utf-8")
    assert str(tmp_path) not in text


def test_autosave_and_recovery(service, tmp_path) -> None:
    project = service.create(tmp_path / "s1.rcad", name="s1")
    service.add_cell(project, S1)
    service.autosave(project, changed_cells={"memristor_iv"})
    recovery = service.path(project) / "recovery.json"
    assert recovery.exists()
    diags = service.recovery_state(project)
    assert diags
    service.save(project)
    assert not recovery.exists()  # FR-PRS-004: очищено после сохранения


def test_canvas_api_state_and_params(service, tmp_path) -> None:
    project = service.create(tmp_path / "s1.rcad", name="s1")
    service.add_cell(project, S1)
    api = CanvasApi(project=project)
    state = api.canvas_state("memristor_iv")
    assert len(state["instances"]) == 3
    assert {w["net"] for w in state["wires"]} == {"n1", "n2", "0"}
    api.set_params("memristor_iv", "Xmem", {"Vp": 0.9})
    assert api.instance_params("memristor_iv", "Xmem")["Vp"] == 0.9


def test_canvas_api_place_active_cell(service, tmp_path) -> None:
    project = service.create(tmp_path / "s2.rcad", name="s2")
    api = CanvasApi(project=project)
    api.place("vdut", "memristor_m1", x=100, y=100)
    assert "s2" in project.cell_names
    state = api.canvas_state("s2")
    assert state["instances"][0]["name"] == "vdut"


def test_canvas_api_place_rejects_duplicate_name(service, tmp_path) -> None:
    project = service.create(tmp_path / "s2.rcad", name="s2")
    api = CanvasApi(project=project)
    api.place("vdut", "memristor_m1", x=100, y=100)
    with pytest.raises(ValueError, match="занято"):
        api.place("vdut", "memristor_m1", x=200, y=100)


def test_model_manager_params_for_required(service, tmp_path) -> None:
    project = service.create(tmp_path / "s1.rcad", name="s1")
    specs = project.model_manager.params_for("memristor_m1")
    names = {spec.name for spec in specs}
    assert {"a1", "a2", "b", "Vp", "Vn", "Ap", "An", "xo", "eta"} <= names


def test_model_manager_symbol_for_x_cards() -> None:
    from rcad.services.model_manager import ModelManager

    manager = ModelManager()
    symbol = manager.symbol_for("memristor_m1")
    assert symbol is not None
    assert [pin.name for pin in symbol.pins] == ["A", "B"]
