"""Целостность библиотеки символов и технологических библиотек (FR-DEV-001, FR-LIB-001).

Проверяется то, что не зависит от ядра моделирования: JSON-контракт символа,
соответствие выводов симво­ла терминалам модели (приложение B ТЗ) и корректность
ссылок технологических библиотек на существующие символы.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rcad.schemas.symbol import GRID, SymbolSchema, side_of

ROOT = Path(__file__).resolve().parents[2]
SYMBOLS_DIR = ROOT / "data" / "Symbols"
LIBRARIES_DIR = ROOT / "data" / "Libraries"

# Терминалы приборов по приложению B ТЗ (порядок — как в описании модели).
DEVICE_TERMINALS = {
    "mosfet_n": ["D", "G", "S", "B"],
    "mosfet_p": ["D", "G", "S", "B"],
    "memristor_m1": ["A", "B"],
    "memristor_m2": ["A", "B"],
    "memristor_m3": ["A", "B"],
    "memtransistor_gem": ["D", "G", "S"],
    "neuristor_n1": ["A", "B"],
    "neuristor_n2": ["A", "B"],
}

# Параметры моделей по ТЗ 9.1–9.4; набор в библиотеке может быть шире,
# но обязательные имена должны присутствовать.
REQUIRED_PARAMS = {
    "mosfet_n": {"W", "L", "VTO", "KP", "GAMMA", "PHI", "LAMBDA", "TOX",
                 "CGSO", "CGDO", "CGBO", "RD", "RS"},
    "mosfet_p": {"W", "L", "VTO", "KP", "GAMMA", "PHI", "LAMBDA", "TOX",
                 "CGSO", "CGDO", "CGBO", "RD", "RS"},
    "memristor_m1": {"a1", "a2", "b", "Vp", "Vn", "Ap", "An", "xp", "xn",
                     "alphap", "alphan", "xo", "eta"},
    "memristor_m2": {"Ron", "Roff", "D", "mu_v", "x0"},
    "memtransistor_gem": {"w_on", "w_off", "k_on", "k_off", "alpha_on", "alpha_off",
                          "s_on", "s_off", "beta_on", "beta_off", "v_on", "v_off",
                          "r_on", "r_off", "mu", "w_init"},
    "neuristor_n1": {"R_on", "R_off", "V_set", "V_hold", "t_delay", "t_relax", "C_par"},
    "neuristor_n2": {"R_on", "R_off", "V_set", "V_hold", "tau_set", "tau_relax",
                     "s_init", "sigma"},
}

PRIMITIVES = {"resistor", "capacitor", "inductor", "vsource", "isource",
              "vcvs", "vccs", "cccs", "ccvs", "bsource"}


def symbol_files() -> list[Path]:
    return sorted(SYMBOLS_DIR.glob("*.json"))


def library_files() -> list[Path]:
    return sorted(LIBRARIES_DIR.glob("*.json"))


@pytest.fixture(scope="module")
def symbols() -> dict[str, SymbolSchema]:
    return {
        path.stem: SymbolSchema.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for path in symbol_files()
    }


def test_symbol_files_exist() -> None:
    assert symbol_files(), f"нет символов в {SYMBOLS_DIR}"


def test_library_files_exist() -> None:
    assert library_files(), f"нет библиотек в {LIBRARIES_DIR}"


@pytest.mark.parametrize("path", symbol_files(), ids=lambda p: p.stem)
def test_symbol_is_valid(path: Path) -> None:
    symbol = SymbolSchema.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert symbol.cell == path.stem, "имя файла символа не совпадает с полем cell"
    assert symbol.graphics, "у символа нет графики"


def test_devices_and_primitives_are_covered(symbols: dict[str, SymbolSchema]) -> None:
    missing = (set(DEVICE_TERMINALS) | PRIMITIVES) - set(symbols)
    assert not missing, f"нет символов для: {sorted(missing)}"


@pytest.mark.parametrize("cell,terminals", DEVICE_TERMINALS.items())
def test_pin_names_match_model_terminals(cell: str, terminals: list[str],
                                         symbols: dict[str, SymbolSchema]) -> None:
    assert [pin.name for pin in symbols[cell].pins] == terminals


@pytest.mark.parametrize("cell", sorted(PRIMITIVES))
def test_primitive_has_at_least_two_pins(cell: str, symbols: dict[str, SymbolSchema]) -> None:
    assert len(symbols[cell].pins) >= 2


@pytest.mark.parametrize("path", symbol_files(), ids=lambda p: p.stem)
def test_pin_side_matches_position(path: Path) -> None:
    symbol = SymbolSchema.model_validate(json.loads(path.read_text(encoding="utf-8")))
    for pin in symbol.pins:
        assert pin.side == side_of(pin.point)
        assert pin.x % GRID == 0 and pin.y % GRID == 0


@pytest.mark.parametrize("path", symbol_files(), ids=lambda p: p.stem)
def test_pin_marks_output_line(path: Path) -> None:
    """Все выводы лежат внутри поля символа: графика по обеим осям не меньше 10 px."""
    symbol = SymbolSchema.model_validate(json.loads(path.read_text(encoding="utf-8")))
    xs = {pin.x for pin in symbol.pins}
    ys = {pin.y for pin in symbol.pins}
    assert max(xs) - min(xs) >= GRID or max(ys) - min(ys) >= GRID


def test_duplicate_pin_names_rejected() -> None:
    with pytest.raises(ValueError, match="повторяются"):
        SymbolSchema.model_validate({
            "cell": "x",
            "pins": [
                {"name": "P", "x": -10, "y": 0, "side": "right"},
                {"name": "P", "x": 10, "y": 0, "side": "right"},
            ],
            "graphics": [],
        })


def test_pin_off_grid_rejected() -> None:
    with pytest.raises(ValueError, match="сетки"):
        SymbolSchema.model_validate({
            "cell": "x",
            "pins": [{"name": "P", "x": 3, "y": 0, "side": "right"}],
            "graphics": [],
        })


@pytest.mark.parametrize("path", library_files(), ids=lambda p: p.stem)
def test_library_cells_resolve(path: Path, symbols: dict[str, SymbolSchema]) -> None:
    library = json.loads(path.read_text(encoding="utf-8"))
    assert library["name"] == path.stem
    assert library["cells"], "библиотека без ячеек"
    names = [entry["cell"] for entry in library["cells"]]
    assert len(set(names)) == len(names), f"повторяющиеся ячейки: {names}"
    unknown = set(names) - set(symbols)
    assert not unknown, f"нет символов для ячеек {sorted(unknown)}"


@pytest.mark.parametrize("path", library_files(), ids=lambda p: p.stem)
def test_library_params_cover_required(path: Path) -> None:
    library = json.loads(path.read_text(encoding="utf-8"))
    for entry in library["cells"]:
        required = REQUIRED_PARAMS.get(entry["cell"])
        if required is None:
            continue
        missing = required - set(entry["params"])
        assert not missing, f"{path.stem}/{entry['cell']}: нет параметров {sorted(missing)}"


@pytest.mark.parametrize("path", library_files(), ids=lambda p: p.stem)
def test_library_subckt_only_for_devices(path: Path) -> None:
    library = json.loads(path.read_text(encoding="utf-8"))
    for entry in library["cells"]:
        if entry["role"] == "device" and entry["netlist_card"] == "X":
            assert entry["subckt"], f"{path.stem}/{entry['cell']}: X-карточка без subckt"
            assert entry["include"] != "*", f"{path.stem}/{entry['cell']}: нет include"
        if entry["role"] == "primitive":
            assert entry["subckt"] is None
