"""Реестр обязательных тест-кейсов ТЗ п. 12.2 (T1–T15) и приёмочных сценариев ТЗ п. 3 (S1–S4).

Единственный источник правды о связи «тест-кейс → файл теста → этап плана».
`tests/unit/test_trace.py` сверяет реестр с перечнем из ТЗ и проверяет, что каждый
файл существует и каждый ID объявлен в тестах маркером `tcase`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Level(str, Enum):
    """Уровень теста по ТЗ п. 12.1."""

    UNIT = "unit"
    GOLDEN = "golden"
    INTEGRATION = "integration"
    PERF = "perf"


@dataclass(frozen=True)
class Case:
    id: str
    title: str
    level: Level
    stage: str
    test: str
    tol: str | None = None


REGISTRY: dict[str, Case] = {
    case.id: case
    for case in (
        Case("T1", "MNA: делитель R-R DC", Level.UNIT, "E0",
             "tests/integration/test_t01_mna_divider.py", "1e-12"),
        Case("T2", "RC-заряд через TRAN", Level.UNIT, "E0",
             "tests/integration/test_t02_rc_tran.py", "1e-3"),
        Case("T3", "RLC-контур AC: резонанс", Level.UNIT, "E0",
             "tests/integration/test_t03_rlc_ac.py", "f 1%, Q 2%"),
        Case("T4", "MOSFET: 3 области, сверка с ручным расчётом", Level.GOLDEN, "E1",
             "tests/integration/test_t04_mosfet.py", "1e-3"),
        Case("T5", "Мемристор Yakopcic: петля I-V на SIN 1 Гц, SV в [0,1]", Level.GOLDEN, "E1",
             "tests/integration/test_t05_memristor_loop.py", "5%"),
        Case("T6", "Мемристор: порог (|V| < Vp → нет движения SV)", Level.UNIT, "E1",
             "tests/integration/test_t06_memristor_threshold.py", "1e-6"),
        Case("T7", "Мемтранзистор GEM: 10 импульсов vgs → ступени ids", Level.UNIT, "E1",
             "tests/integration/test_t07_gem_pulses.py"),
        Case("T8", "Нейристор N1/N2 в LIF-нейроне", Level.INTEGRATION, "E1",
             "tests/integration/test_t08_neuristor_lif.py"),
        Case("T9", "Verilog-A: линейный резистор как VA-модель", Level.UNIT, "E2",
             "tests/integration/test_t09_va_resistor.py", "1e-9"),
        Case("T10", "Verilog-A: нелинейная ёмкость с ddt", Level.UNIT, "E2",
             "tests/integration/test_t10_va_ddt.py", "1e-3"),
        Case("T11", "Verilog-A: ошибки (синтаксис, неподдерживаемая конструкция)", Level.UNIT, "E2",
             "tests/integration/test_t11_va_errors.py"),
        Case("T12", "Иерархия subckt, 3 уровня", Level.UNIT, "E0",
             "tests/integration/test_t12_subckt_hierarchy.py"),
        Case("T13", "Кроссбар 16×16 мемристоров, 10 000 точек TRAN", Level.PERF, "E1",
             "tests/integration/test_t13_crossbar.py", "120 s"),
        Case("T14", "Разрыв источника PULSE: попадание в точку фронта", Level.UNIT, "E0",
             "tests/integration/test_t14_pulse_breakpoint.py", "1e-12 s"),
        Case("T15", "Диагностика висящего узла", Level.UNIT, "E0",
             "tests/integration/test_t15_floating_node.py"),
        Case("S1", "ВАХ мемристора: V — мемристор — gnd, TRAN", Level.INTEGRATION, "E3",
             "tests/integration/test_s1_memristor_iv.py"),
        Case("S2", "Импорт собственной Verilog-A модели", Level.INTEGRATION, "E3",
             "tests/integration/test_s2_import_va.py"),
        Case("S3", "Нейристорный LIF-нейрон", Level.INTEGRATION, "E3",
             "tests/integration/test_s3_neuristor_neuron.py"),
        Case("S4", "Кроссбар 4×4 через subckt-иерархию", Level.INTEGRATION, "E3",
             "tests/integration/test_s4_crossbar_4x4.py"),
    )
}

TEST_CASES = tuple(case for case in REGISTRY if case.startswith("T"))
SCENARIOS = tuple(case for case in REGISTRY if case.startswith("S"))
