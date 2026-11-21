"""S4: кроссбар 4×4 мемристоров через subckt-иерархию.

Приёмка ТЗ п. 3, FR-SCN-S4: netlist импортируется, иерархия `subckt` → ячейки
создаётся и экспортируется обратно, TRAN даёт 4 ряда токов столбцов, результат
идентичен плоской схеме.
"""

from __future__ import annotations

import pytest

from conftest import max_rel_error, requires_core, requires_services

pytestmark = [pytest.mark.tcase("S4"), requires_core, requires_services]

HIERARCHICAL = """\
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
V1 c1 0 SIN(0 1 1k 0 0 90)
V2 c2 0 SIN(0 1 1k 0 0 180)
V3 c3 0 SIN(0 1 1k 0 0 270)
X00 c0 r0 mem_cell
X01 c1 r0 mem_cell
X02 c2 r0 mem_cell
X03 c3 r0 mem_cell
R0 r0 0 100
.tran 10u 1m 0 10u
.end
"""

FLAT = """\
* S4: плоский эквивалент одного столбца
.include "models/memristor_yakopcic.lib"
V0 c0 0 SIN(0 1 1k)
X00 c0 r0 memristor_yakopcic a1=0.17 a2=0.17 b=0.05 Vp=0.65 Vn=0.56 Ap=4000 An=4000
+ xp=0.3 xn=0.3 alphap=3 alphan=3 xo=0.1 eta=1
R0 r0 0 100
.tran 10u 1m 0 10u
.end
"""


def test_netlist_import_creates_hierarchy(tmp_path) -> None:
    from rcad.services.netlister import import_netlist
    from rcad.services.project_service import ProjectService

    project = ProjectService().create(tmp_path / "s4.rcad", name="s4")
    import_netlist(project, HIERARCHICAL, main="top")
    assert "mem_cell" in project.cell_names
    assert "top" in project.cell_names
    assert project.cell("top").hierarchy_children


def test_hierarchy_exports_back_to_netlist(tmp_path) -> None:
    from rcad.services.netlister import export_netlist, import_netlist
    from rcad.services.project_service import ProjectService

    project = ProjectService().create(tmp_path / "s4.rcad", name="s4")
    import_netlist(project, HIERARCHICAL, main="top")
    exported = export_netlist(project, "top")
    assert ".subckt mem_cell" in exported
    assert exported.count("mem_cell") >= 2


def test_four_column_currents_are_available(tmp_path) -> None:
    from rcad.core.analyses import run_analysis

    from rcad.services.netlister import import_netlist
    from rcad.services.project_service import ProjectService

    project = ProjectService().create(tmp_path / "s4.rcad", name="s4")
    import_netlist(project, HIERARCHICAL, main="top")
    from rcad.services.netlister import netlist_for

    result = run_analysis(netlist_for(project, "top", tran="10u 1m 0 10u"), ".tran")
    columns = [name for name in result.names() if name.startswith("I(V")]
    assert len(columns) == 4
    assert all(len(result[name]) == len(result["time"]) for name in columns)


def test_hierarchical_result_matches_flat() -> None:
    from rcad.core.analyses import run_analysis

    hierarchical = run_analysis(HIERARCHICAL, ".tran")
    flat = run_analysis(FLAT, ".tran")
    assert max_rel_error(list(hierarchical["I(V0)"]), list(flat["I(V0)"])) <= 1e-3
    assert max_rel_error(
        list(hierarchical["@X00.Xmem.x"]), list(flat["@X00.x"])
    ) <= 1e-3
