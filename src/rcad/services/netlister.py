"""Генерация и импорт SPICE-netlist (FR-NLV-001…005, FR-WIR-002…004, FR-CEL-004).

Соединения инстансов с net решаются геометрически (контракт S1/S3):
абсолютная позиция вывода = (inst.x + pin.x, inst.y + pin.y) должна совпасть
с точкой провода; инстанс считается подключённым к net. Для инстансов, у
которых выводы не совпали ни с одной точкой (провода «до центра» — S3),
применяется fallback: центр (x, y) инстанса, встречающийся в точках net.

Нетлист собирается в порядке: `.include` внешних моделей (кроме "*"),
`.subckt`-заглушки ячеек иерархии, карты инстансов, директива, `.end`.
Модуль headless — без PySide6 (ARCh §3); исключения — `NetlistError`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path

from rcad.diagnostics import Diagnostic, DiagnosticCode, NetlistError, RcadError, Severity
from rcad.schemas.cell import CellSchema, InstanceSchema, Point, transform_point
from rcad.schemas.model import ModelEntry
from rcad.services.project_service import ProjectDoc

INCLUDE_RE = re.compile(r'^\s*\.include\s+"([^"]+)"\s*$')
ELEMENT_RE = re.compile(r"^\s*([RCLVIEGFHDQBMX])([A-Za-z0-9_$]+)\s*(.*)$")
DIRECTIVE_RE = re.compile(r"^\s*\.\w+")

PRIMITIVE_MASTERS = {
    "R": "resistor",
    "C": "capacitor",
    "L": "inductor",
    "V": "vsource",
    "I": "isource",
    "G": "vccs",
    "E": "vcvs",
    "F": "cccs",
    "H": "ccvs",
    "B": "bsource",
}

_MORE = r"[a-zA-Z]"
_SUFFIXES = {
    "T": 1e12, "G": 1e9, "MEG": 1e6, "K": 1e3,
    "M": 1e-3, "U": 1e-6, "N": 1e-9, "P": 1e-12, "F": 1e-15,
}
_NUM_RE = re.compile(r"^([+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?)([a-zA-Z]*)$")


def parse_value(text: str) -> float | int | str:
    """SPICE-значение: число с суффиксом (1k/2u/1meg) либо строка (PULSE(...)).

    Числа с суффиксами конвертируются; строки-выражения возвращаются как есть —
    ядро разбирает их (S1: `"0 1 1"` для SIN).
    """
    text = text.strip()
    if not text:
        return ""
    m = _NUM_RE.match(text)
    if not m:
        return text
    number, _, _, suffix = m.group(1), m.group(2), m.group(3), m.group(4)
    value = float(number)
    if suffix:
        factor = _SUFFIXES.get(suffix.upper())
        if factor is not None:
            value *= factor
            return int(value) if value.is_integer() else value
        return text
    return int(value) if value.is_integer() else value


def fmt_value(value: float | int | str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    return f"{value:g}".replace("e+06", "meg").replace("e+09", "g")


def netlist_for(
    project: ProjectDoc,
    cell: str,
    *,
    dc: str | None = None,
    tran: str | None = None,
    ac: str | None = None,
) -> str:
    """Netlist ячейки с директивой анализа (S1/S3/S4)."""
    return _compose(project, project.cell(cell), _directive(dc, tran, ac) or "")


def export_netlist(project: ProjectDoc, cell: str) -> str:
    """Тот же netlist без директивы (NetlistView, FR-NLV-001/003)."""
    return _compose(project, project.cell(cell), "")


def _directive(dc: str | None, tran: str | None, ac: str | None) -> str | None:
    if dc is not None:
        return f".dc {dc}" if not dc.lstrip().startswith(".") else dc
    if tran is not None:
        return f".tran {tran}" if not tran.lstrip().startswith(".") else tran
    if ac is not None:
        return f".ac {ac}" if not ac.lstrip().startswith(".") else ac
    return None


def _compose(project: ProjectDoc, top: CellSchema, directive: str) -> str:
    lines: list[str] = [f"* netlist for cell {top.name}"]
    for include in sorted(_used_includes(project, top)):
        lines.append(f'.include "{include}"')
    for child in _hierarchy_order(project, top):
        lines.extend(_subckt_block(project, child))
    bindings = resolve_bindings(project, top)
    for inst in top.instances:
        lines.append(_instance_line(project, inst, bindings))
    if directive:
        lines.append(directive)
    lines.append(".end")
    return "\n".join(lines) + "\n"


def _used_includes(project: ProjectDoc, cell: CellSchema) -> set[str]:
    out: set[str] = set()
    for inst in cell.instances:
        entry = project.model_manager.entry(inst.master_cell)
        if entry is not None and entry.include not in ("*", ""):
            out.add(entry.include)
    return out


def _hierarchy_order(project: ProjectDoc, top: CellSchema) -> list[CellSchema]:
    """BFS дочерних ячеек проекта (subckt), на которые ссылается топ."""
    order: list[CellSchema] = []
    seen: set[str] = {top.name}
    queue = [inst.master_cell for inst in top.instances]
    while queue:
        name = queue.pop(0)
        if name in seen or name not in project.cells:
            continue
        seen.add(name)
        child = project.cells[name]
        order.append(child)
        queue.extend(i.master_cell for i in child.instances)
    return order


def _subckt_block(project: ProjectDoc, cell: CellSchema) -> list[str]:
    ports = " ".join(p.name for p in cell.ports)
    lines = [f".subckt {cell.name}" + (f" {ports}" if ports else "")]
    for include in sorted(_used_includes(project, cell)):
        lines.append(f'  .include "{include}"')
    bindings = resolve_bindings(project, cell)
    for inst in cell.instances:
        lines.append(_instance_line(project, inst, bindings, in_subckt=True))
    lines.append(".ends")
    return lines


# --- геометрия и резолвер ---------------------------------------------------

def _pin_offsets(project: ProjectDoc, inst: InstanceSchema) -> list[tuple[str, Point]]:
    """(имя пина, локальная точка) в порядке выводов символа мастера."""
    symbol = project.model_manager.symbol(inst.master_cell)
    if symbol is not None:
        offsets = [(pin.name, (pin.x, pin.y)) for pin in symbol.pins]
    else:
        entry = project.model_manager.entry(inst.master_cell)
        count = len(entry.pins) if entry is not None else 1
        offsets = [(f"p{i + 1}", (0, 0)) for i in range(count)]
    return [
        (name, transform_point(x, y, inst.rotation, inst.mirror))
        for name, (x, y) in offsets
    ]


def absolute_pins(project: ProjectDoc, inst: InstanceSchema) -> list[tuple[str, Point]]:
    return [(name, (inst.x + x, inst.y + y)) for name, (x, y) in _pin_offsets(project, inst)]


def resolve_bindings(project: ProjectDoc, cell: CellSchema) -> dict[str, list[tuple[str, str]]]:
    """Инстанс → [(pin, net), ...] по геометрическому совпадению точек провода.

    Первичное правило — точное совпадение абсолютной позиции вывода с точкой
    провода. Если выводы не тождественны ни одной точке, net ищут по совпадению
    центра инстанса с точкой провода (S3: провода к центру символа).
    """
    net_points: dict[str, set[Point]] = {}
    for wire in cell.wires:
        net_points.setdefault(wire.net, set()).update(wire.points)

    result: dict[str, list[tuple[str, str]]] = {}
    for inst in cell.instances:
        pins = _pin_offsets(project, inst)
        assignments: list[tuple[str, str]] = []
        for pin_name, (lx, ly) in pins:
            absolute = (inst.x + lx, inst.y + ly)
            net = next((n for n, pts in net_points.items() if absolute in pts), "")
            assignments.append((pin_name, net))
        if all(net == "" for _, net in assignments):
            center = (inst.x, inst.y)
            touching = [n for n, pts in net_points.items() if center in pts]
            if touching:
                # пары «вывод i → net i» по порядку net в проводах ячейки
                for idx, (pin_name, _) in enumerate(assignments):
                    assignments[idx] = (pin_name, touching[idx % len(touching)] if touching else "")
        result[inst.name] = assignments
    return result


# --- карта инстанса ---------------------------------------------------------

def _instance_line(
    project: ProjectDoc,
    inst: InstanceSchema,
    bindings: dict[str, list[tuple[str, str]]],
    *,
    in_subckt: bool = False,
) -> str:
    entry = project.model_manager.entry(inst.master_cell)
    project_child = inst.master_cell in project.cells

    if entry is None and not project_child:
        raise RcadError(f"отсутствующий мастер {inst.master_cell!r} для инстанса {inst.name!r}")

    # Явные узлы из импорта (S4: X00 c0 r0 mem_cell / Xmem top bot model)
    if inst.nodes:
        nodes = list(inst.nodes)
    else:
        pins = _pin_offsets(project, inst)
        pin_nets = dict(bindings.get(inst.name, []))
        nodes = [pin_nets.get(name, f"{inst.name}_{name}") for name, _ in pins]

    # Ссылка на ячейку проекта (subckt): имя инстанса уже содержит префикс `X`.
    if project_child:
        params = "".join(f" {k}={fmt_value(v)}" for k, v in inst.params.items())
        return f"{inst.name} {' '.join(nodes)} {inst.master_cell}{params}"

    if entry is None:  # непокрытый отсутствующий мастер — не должно случаться после raise выше
        raise RcadError(f"отсутствующий мастер {inst.master_cell!r} для инстанса {inst.name!r}")

    element = inst.name
    card = entry.netlist_card
    if card in ("R", "C", "L"):
        key = {"R": "R", "C": "C", "L": "L"}[card]
        value = inst.params.get(key, entry.params.get(key, "0"))
        return f"{element} {' '.join(nodes)} {fmt_value(value)}"
    if card in ("V", "I"):
        source = _source_text(inst)
        return f"{element} {' '.join(nodes)} {source}"
    if card == "M":
        model = entry.subckt or inst.master_cell
        return f"{element} {' '.join(nodes)} {model}" + _params_text(entry, inst)
    if card == "X":
        model = entry.subckt or inst.master_cell
        return f"{element} {' '.join(nodes)} {model}" + _params_text(entry, inst)
    raise NetlistError(f"карта {card!r} для {inst.name!r} не поддерживается экспортом", file=inst.name)


def _source_text(inst: InstanceSchema) -> str:
    """Параметры источника: DC/SIN/PULSE/… в SPICE-форме.

    Числа: `DC=0`. Выражения-строки: `SIN(0 1 1)`, `PULSE(1 2 3)`, иначе `key=value`.
    """
    if not inst.params:
        return "0"
    parts: list[str] = []
    for key, value in inst.params.items():
        key = key.upper()
        if isinstance(value, str):
            inner = value.strip()
            if key in ("SIN", "PULSE", "EXP", "SFFM", "PWL", "AM"):
                if inner.startswith(key):
                    parts.append(inner)
                elif inner.startswith("("):
                    parts.append(f"{key}{inner}")
                else:
                    parts.append(f"{key}({inner})")
            elif key in ("DC", "AC"):
                parts.append(f"{key}={value}")
            else:
                parts.append(f"{key}={value}")
        else:
            parts.append(f"{key}={fmt_value(value)}")
    return " ".join(parts)


def _params_text(entry: ModelEntry, inst: InstanceSchema) -> str:
    params = dict(entry.params)
    params.update(inst.params)
    return "".join(f" {k}={fmt_value(v)}" for k, v in params.items())


# --- автоимена net ----------------------------------------------------------

def next_net_name(existing: Iterable[str]) -> str:
    """Автоимя `n<k>`: минимальный свободный номер (FR-WIR-002), узел 0 не трогаем."""
    taken = {str(n) for n in existing} - {"0"}
    k = 1
    while f"n{k}" in taken:
        k += 1
    return f"n{k}"


def validate_net_name(name: str, existing: Iterable[str]) -> list[Diagnostic]:
    """Ручное переименование net (FR-WIR-004): reject (недопустимые) / merge (занято)."""
    diags: list[Diagnostic] = []
    if name != "0" and not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", name):
        diags.append(
            Diagnostic(
                code=DiagnosticCode.E_NETLIST,
                message=f"invalid net name {name!r}",
                hint_ru=f"Недопустимое имя net {name!r}: только буквы/цифры/_/$.",
            )
        )
    taken = {str(n) for n in existing} - {"0"}
    if name in taken:
        diags.append(
            Diagnostic(
                code=DiagnosticCode.W_DC_DISCONTINUITY,
                severity=Severity.WARNING,
                message=f"net name {name!r} already exists",
                hint_ru=f"Имя {name!r} занято: требуется явное объединение или отказ (FR-WIR-004).",
            )
        )
    return diags


# --- импорт -----------------------------------------------------------------

def import_netlist(
    project: ProjectDoc,
    text: str,
    *,
    main: str = "main",
    include_paths: Sequence[Path] = (),
) -> list[Diagnostic]:
    """Импорт netlist → ячейки проекта (FR-NLV-004/005, S4).

    `.subckt` → ячейки с портами, `X` → инстансы дочерних ячеек/моделей,
    `R/C/V/…` → примитивы. `.include` воспроизводится при экспорте. Ошибки
    разбора → `NetlistError` (проект при этом не изменяется, FR-NLV-005).
    """
    lines = _expand_continuations(text)
    top_body: list[str] = []
    active: str | None = None
    current_ports: list[str] = []
    subckt_map: dict[str, tuple[list[str], list[str]]] = {}

    raw: list[str] = []
    for stripped in lines:
        if not stripped or stripped.startswith("*"):
            continue
        lower = stripped.lower()
        if lower.startswith(".subckt"):
            tokens = stripped.split()
            if len(tokens) < 2:
                raise NetlistError("не указано имя subckt", line=1)
            active = tokens[1]
            current_ports = tokens[2:]
            raw = []
            continue
        if lower.startswith(".ends"):
            if active is not None:
                subckt_map[active] = (current_ports, raw)
            active = None
            continue
        if lower.startswith(".include"):
            m = INCLUDE_RE.match(stripped)
            if m:
                project.model_manager.register_include(m.group(1))
            continue
        if lower.startswith((".tran", ".dc", ".ac", ".op", ".end", ".model", ".ic")):
            continue
        if active is not None:
            raw.append(stripped)
        else:
            top_body.append(stripped)

    diagnostics: list[Diagnostic] = []
    subckt_names = set(subckt_map)

    for name, (ports, body) in subckt_map.items():
        instances = [
            _element_to_instance(project, line, subckt_names)
            for line in body
            if ELEMENT_RE.match(line)
        ]
        cell = CellSchema(
            name=name,
            ports=_ports_from_names(ports),
            instances=instances,
            hierarchy_children=_children(instances, subckt_names),
        )
        project.cells[name] = cell

    top_instances = [
        _element_to_instance(project, line, subckt_names)
        for line in top_body
        if ELEMENT_RE.match(line)
    ]
    main_cell = CellSchema(
        name=main,
        instances=top_instances,
        hierarchy_children=_children(top_instances, subckt_names),
    )
    project.cells[main] = main_cell

    # Информирование о несуществующих include внутри неинстанцируемых subckt
    for name in subckt_names:
        for inc in _includes_in(project, name):
            resolved = _find_include(inc, list(include_paths))
            if resolved is None and name not in {i.master_cell for i in top_instances}:
                diagnostics.append(
                    Diagnostic(
                        code=DiagnosticCode.W_DC_DISCONTINUITY,
                        severity=Severity.WARNING,
                        message=f"include file not found: {inc}",
                        hint_ru=f"Файл .include {inc} не найден; модель будет недоступна (warning).",
                        file=inc,
                    )
                )
    return diagnostics


def _includes_in(project: ProjectDoc, cell_name: str) -> set[str]:
    out: set[str] = set()
    include_paths = project.model_manager.includes_for(cell_name)
    out.update(include_paths)
    return out


def _find_include(inc: str, include_paths: list[Path]) -> Path | None:
    from rcad.services.model_manager import _data_root

    candidate = Path(inc)
    if candidate.is_file():
        return candidate
    for base in include_paths + [_data_root() / "models"]:
        probe = base / Path(inc).name
        if probe.is_file():
            return probe
    return None


def _ports_from_names(names: list[str]) -> list:
    from rcad.schemas.cell import PortSchema

    return [PortSchema(name=n, direction="inout", x=0, y=0) for n in names]


def _children(instances: list[InstanceSchema], subckt_names: set[str]) -> list[str]:
    return sorted({i.master_cell for i in instances if i.master_cell in subckt_names})


def _element_to_instance(
    project: ProjectDoc,
    line: str,
    subckt_names: set[str],
) -> InstanceSchema:
    m = ELEMENT_RE.match(line)
    if not m:
        raise NetlistError(f"не распознана строка {line!r}")
    card, name, rest = m.group(1).upper(), m.group(2), m.group(3).strip()
    tokens = _tokenize(rest)
    params_text: list[str] = []
    nodes: list[str] = []
    body_start = False
    for tok in tokens:
        if "=" in tok and not tok.endswith("=") and not body_start:
            params_text.append(tok)
            body_start = True
        elif body_start:
            params_text.append(tok)
        else:
            nodes.append(tok)
    params = {k: parse_value(v) for k, v in (p.split("=", 1) for p in params_text)}

    if card == "X":
        # узлы, затем имя модели/subckt
        master = nodes.pop() if nodes else ""
        if master in subckt_names:
            pass  # ссылка на ячейку проекта
        else:
            entry = project.model_manager.entry(master)
            if entry is None:
                entry = project.model_manager.entry_by_subckt(master)
            master = entry.cell if entry is not None else master
        return InstanceSchema(
            name=card + name, master_cell=master, nodes=nodes, params=params
        )
    if card == "M":
        model = nodes.pop() if nodes else ""
        entry = project.model_manager.entry_by_subckt(model)
        master = entry.cell if entry is not None else ("mosfet_p" if "p" in model.lower() else "mosfet_n")
        return InstanceSchema(name=card + name, master_cell=master, nodes=nodes, params=params)
    if card in ("R", "C", "L"):
        # R1 n1 n2 100 — значение последним токеном (без "=")
        value_token = nodes.pop() if nodes and _looks_numeric(nodes[-1]) else None
        if value_token is not None:
            params[card] = parse_value(value_token)
        master = PRIMITIVE_MASTERS[card]
        return InstanceSchema(name=card + name, master_cell=master, nodes=nodes, params=params)
    master = PRIMITIVE_MASTERS.get(card, f"unknown_{card}")
    if card in ("V", "I") and not params:
        # источник с функцией: SIN(...)/PULSE(...) лежит в первом незанятом токене
        if nodes and _looks_function(nodes[-1]):
            params[nodes[-1].split("(")[0].upper()] = nodes[-1]
            nodes = nodes[:-1]
        elif len(nodes) > 2:
            params[card] = parse_value(nodes[-1])
            nodes = nodes[:-1]
    return InstanceSchema(name=card + name, master_cell=master, nodes=nodes, params=params)


def _looks_numeric(token: str) -> bool:
    return bool(re.fullmatch(r"[+-]?\d+\.?\d*([eE][+-]?\d+)?[a-zA-Z]*", token))


def _looks_function(token: str) -> bool:
    return "(" in token and token.rstrip().endswith(")")


def _tokenize(text: str) -> list[str]:
    """Разбиение "N1 N2 SIN(0 1 1) DC=0" с учётом скобочных групп."""
    tokens: list[str] = []
    current = ""
    depth = 0
    for ch in text:
        if ch == "(":
            current += ch
            depth += 1
        elif ch == ")":
            current += ch
            depth = max(0, depth - 1)
        elif ch.isspace() and depth == 0:
            if current:
                tokens.append(current)
                current = ""
        else:
            current += ch
    if current:
        tokens.append(current)
    return tokens


def _expand_continuations(text: str) -> list[str]:
    """Собрать продолжения строк `+ …` в одну физическую строку (S4)."""
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("+"):
            if out:
                out[-1] = out[-1] + " " + stripped[1:].strip()
            else:
                out.append(stripped[1:].strip())
        else:
            out.append(stripped)
    return out
