"""T11: ошибки Verilog-A — структурное сообщение, приложение не падает."""

from __future__ import annotations

import pytest

from conftest import requires_core

pytestmark = [pytest.mark.tcase("T11"), requires_core]

SYNTAX_ERROR = """\
`include "constants.vams"
module broken_model(p, n);
  inout p, n;
  parameter real r = 1k;
  analog begin
    I(p, n) <+ V(p, n) / r
  end
endmodule
"""

UNSUPPORTED = """\
`include "constants.vams"
module unsupported_model(p, n);
  inout p, n;
  parameter real r = 1k;
  analog begin
    I(p, n) <+ ddx(V(p, n)) / r;
  end
endmodule
"""

TWO_ANALOG = """\
module two_analog(p, n);
  inout p, n;
  analog I(p, n) <+ 0;
  analog I(p, n) <+ 1;
endmodule
"""


@pytest.fixture
def imported(tmp_path):
    from rcad.veriloga import VaImportService

    service = VaImportService(project_dir=tmp_path)
    return service


@pytest.mark.parametrize(
    "source,code",
    [
        (SYNTAX_ERROR, "VA_PARSE_ERROR"),
        (UNSUPPORTED, "VA_UNSUPPORTED"),
        (TWO_ANALOG, "VA_SEMANTIC_ERROR"),
    ],
)
def test_error_is_structured_and_non_fatal(imported, tmp_path, source, code) -> None:
    path = tmp_path / "model.va"
    path.write_text(source, encoding="utf-8")
    outcome = imported.import_file(path)
    assert outcome.ok is False
    assert outcome.diagnostics
    diagnostic = outcome.diagnostics[0]
    assert diagnostic.code == code
    assert diagnostic.file.endswith("model.va")
    assert diagnostic.line is not None and diagnostic.line > 0


def test_import_failure_does_not_register_model(imported, tmp_path) -> None:
    from rcad.devices.registry import registry

    path = tmp_path / "model.va"
    path.write_text(SYNTAX_ERROR, encoding="utf-8")
    imported.import_file(path)
    assert "broken_model" not in registry.names()


def test_missing_compiler_reports_hint(imported, tmp_path, monkeypatch) -> None:
    """FR-VA-ERR-003: отсутствие cl.exe — диагностика с подсказкой, без падения."""
    valid = tmp_path / "ok.va"
    valid.write_text(
        "module ok(p, n); inout p, n; analog I(p, n) <+ 1e-3; endmodule\n", encoding="utf-8"
    )
    monkeypatch.setattr(imported, "find_compiler", lambda: None)
    outcome = imported.import_file(valid)
    assert outcome.ok is False
    assert any(d.code == "VA_COMPILER_NOT_FOUND" for d in outcome.diagnostics)
    assert outcome.diagnostics[0].hint_ru
