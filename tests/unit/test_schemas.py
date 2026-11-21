"""Тесты схем F1: cell/project/model/analysis/result (FR-PRJ-003/004/005, FR-CEL, FR-ERC-002).

Здесь — контрактные unit-тесты без ядра: валидация SCHEMATIC из S1/S3, отклонение
дубликатов, каноническая сериализация, версия формата (FR-PRJ-004/005).
"""

from __future__ import annotations

import pytest

from rcad.schemas.analysis import DcSpec, OpSpec, TranSpec, spec_from_directive
from rcad.schemas.cell import CellSchema, transform_point
from rcad.schemas.model import LibrarySchema, ModelEntry, ParamSpec
from rcad.schemas.project import FORMAT_VERSION, ProjectSchema

S1_SCHEMATIC = {
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


def test_s1_schematic_validates() -> None:
    cell = CellSchema.model_validate(S1_SCHEMATIC)
    assert cell.name == "memristor_iv"
    assert len(cell.instances) == 3
    assert cell.net_names() == {"n1", "n2", "0"}


def test_s3_schematic_validates() -> None:
    schematic = {
        "name": "lif_neuron",
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
    cell = CellSchema.model_validate(schematic)
    assert len(cell.instances) == 4
    assert len(cell.net_names()) >= 3


def test_duplicate_instance_names_rejected() -> None:
    schematic = dict(S1_SCHEMATIC, name="dup_inst")
    schematic["instances"] = [
        {"name": "A", "master_cell": "resistor", "x": 0, "y": 0,
         "rotation": 0, "mirror": "none", "params": {"R": 100}},
        {"name": "A", "master_cell": "resistor", "x": 0, "y": 0,
         "rotation": 0, "mirror": "none", "params": {"R": 200}},
    ]
    with pytest.raises(ValueError, match="повторяются"):
        CellSchema.model_validate(schematic)


def test_duplicate_net_names_rejected() -> None:
    schematic = dict(S1_SCHEMATIC, name="dup_net")
    schematic["instances"] = [
        {"name": "A", "master_cell": "resistor", "x": 0, "y": 0,
         "rotation": 0, "mirror": "none", "params": {"R": 100}},
    ]
    schematic["wires"] = [
        {"net": "n1", "points": [[0, 0], [10, 10]]},
        {"net": "n1", "points": [[10, 10], [20, 20]]},
    ]
    with pytest.raises(ValueError, match="повторяются"):
        CellSchema.model_validate(schematic)


@pytest.mark.parametrize("rotation", [5, -90, 360])
def test_invalid_rotation_rejected(rotation: int) -> None:
    schematic = dict(S1_SCHEMATIC, name="rot")
    schematic["instances"] = [
        {"name": "A", "master_cell": "resistor", "x": 0, "y": 0,
         "rotation": rotation, "mirror": "none", "params": {"R": 100}},
    ]
    schematic["wires"] = []
    with pytest.raises(ValueError):
        CellSchema.model_validate(schematic)


def test_invalid_mirror_rejected() -> None:
    schematic = dict(S1_SCHEMATIC, name="mir")
    schematic["instances"] = [
        {"name": "A", "master_cell": "resistor", "x": 0, "y": 0,
         "rotation": 0, "mirror": "diag", "params": {"R": 100}},
    ]
    schematic["wires"] = []
    with pytest.raises(ValueError):
        CellSchema.model_validate(schematic)


def test_cell_serialization_is_canonical() -> None:
    """Повторная сериализация одного и того же CellSchema даёт идентичные байты."""
    cell = CellSchema.model_validate(S1_SCHEMATIC)
    once = cell.model_dump_json(exclude_none=True)
    again = cell.model_dump_json(exclude_none=True)
    assert once == again
    assert '"name":"memristor_iv"' in once


def test_transform_point_rotation90() -> None:
    assert transform_point(10, 20, rotation=90) == (-20, 10)
    assert transform_point(10, 20, rotation=180) == (-10, -20)
    assert transform_point(10, 20, rotation=270) == (20, -10)


def test_transform_point_mirror() -> None:
    assert transform_point(10, 20, mirror="x") == (-10, 20)
    assert transform_point(10, 20, mirror="y") == (10, -20)


def test_project_schema_defaults() -> None:
    schema = ProjectSchema(name="my_proj")
    assert schema.format_version == FORMAT_VERSION
    assert schema.libraries == []


def test_project_extra_field_forbidden() -> None:
    with pytest.raises(ValueError):
        ProjectSchema.model_validate({"name": "x", "unexpected": True})


def test_model_entry_from_library_json() -> None:
    entry = ModelEntry.model_validate({
        "cell": "memristor_m1",
        "role": "device",
        "netlist_card": "X",
        "params": {"a1": 0.17, "Vp": 0.65},
        "include": "models/memristor_yakopcic.lib",
        "subckt": "memristor_yakopcic",
    })
    assert entry.is_native is False
    assert entry.cell == "memristor_m1"


def test_library_schema_requires_cells() -> None:
    with pytest.raises(ValueError):
        LibrarySchema.model_validate({"name": "empty", "cells": []})


def test_param_spec_bounds() -> None:
    spec = ParamSpec(name="von", kind="real", default=0.5, bounds=(0.0, 10.0))
    spec.validate_value(0.5)
    spec.validate_value(10.0)
    from rcad.diagnostics import ParameterRangeError

    with pytest.raises(ParameterRangeError):
        spec.validate_value(-1.0)


def test_analysis_spec_directives() -> None:
    assert OpSpec().to_directive() == ".op"
    assert DcSpec(src="V1", start=0, stop=1, step=0.01).to_directive() == ".dc V1 0 1 0.01"
    assert TranSpec(tstep=1e-3, tstop=2, tstart=0, tmax=1e-3).to_directive() == \
        ".tran 0.001 2 0 0.001"


def test_spec_from_directive() -> None:
    spec = spec_from_directive(".tran 1m 2 0 1m")
    assert isinstance(spec, TranSpec)
    assert spec.tstep == 1e-3
    assert spec.tstop == 2
