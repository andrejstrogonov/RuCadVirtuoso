"""T15: диагностика висящего узла — ошибка до решения, с именем узла."""

from __future__ import annotations

import pytest

from conftest import requires_core

pytestmark = [pytest.mark.tcase("T15"), requires_core]

DANGLING = """\
* T15: узел mid имеет одно подключение — висящий вывод
V1 in 0 DC 1
R1 in out 1k
R2 out 0 2k
R3 out float 1k
.op
.end
"""

NO_GROUND_PATH = """\
* T15: узел island не имеет DC-пути к земле
V1 in 0 DC 1
R1 in island 1k
C1 island 0 1u
R2 island island2 1k
.op
.end
"""


def test_dangling_node_error_names_the_node() -> None:
    from rcad.core.analyses import AnalysisError, precheck

    with pytest.raises(AnalysisError) as excinfo:
        precheck(DANGLING)
    assert excinfo.value.diagnostic.code.startswith("E_")
    assert "float" in str(excinfo.value)


def test_error_is_raised_before_solving() -> None:
    """Сообщение возникает на этапе ERC-lite, до вызова решателя."""
    from rcad.core.analyses import AnalysisError, precheck

    with pytest.raises(AnalysisError) as excinfo:
        precheck(DANGLING)
    assert excinfo.value.diagnostic.object_name == "float"


def test_no_ground_path_is_reported() -> None:
    from rcad.core.analyses import AnalysisError, precheck

    with pytest.raises(AnalysisError) as excinfo:
        precheck(NO_GROUND_PATH)
    assert excinfo.value.diagnostic.code == "E_NO_DC_PATH"
    assert "island" in str(excinfo.value)


def test_valid_netlist_passes_precheck() -> None:
    from rcad.core.analyses import precheck

    precheck("V1 in 0 DC 1\nR1 in 0 1k\n.op\n.end\n")
