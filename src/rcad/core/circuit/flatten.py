"""Развертывание иерархии .subckt в плоский список элементов (rcad.core.circuit).

`flatten_netlist()` возвращает FlatCircuit с иерархическими именами узлов
(например X1.X2.mid). Узел "0" остаётся глобальной землёй.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rcad.core.netlist import Element, ModelDef, ParsedNetlist, parse
from rcad.services.model_manager import _data_root


@dataclass
class FlatCircuit:
    name: str
    nodes: list[str] = field(default_factory=list)
    elements: list[Element] = field(default_factory=list)
    models: dict[str, ModelDef] = field(default_factory=dict)
    directives: list[str] = field(default_factory=list)
    initial_conditions: dict[str, float] = field(default_factory=dict)
    includes: list[str] = field(default_factory=list)

    @property
    def node_names(self) -> list[str]:
        return list(self.nodes)


def _resolve_include(path: str) -> str | None:
    candidate = Path(path)
    if candidate.is_file():
        return path
    for base in (_data_root() / "models",):
        probe = base / Path(path).name
        if probe.is_file():
            return str(probe)
    return None


def _load_lib(include: str) -> ParsedNetlist:
    resolved = _resolve_include(include)
    if resolved is None:
        return ParsedNetlist(
            top_name="", top_elements=[], top_models={}, top_includes=[],
            subckts={}, directives=[], initial_conditions={}, includes=[],
        )
    text = Path(resolved).read_text(encoding="utf-8-sig")
    return parse(text)


def flatten_netlist(text: str) -> FlatCircuit:
    """Развернуть нетлист: подставить вложенные .subckt, разрешить .include."""
    parsed = parse(text)

    all_models: dict[str, ModelDef] = dict(parsed.top_models)
    includes = list(parsed.top_includes)
    subckts: dict = dict(parsed.subckts)
    # X-карточки разворачиваются только для inline-подсхем проекта (T2);
    # подсхемы из .include-библиотек остаются элементами X (prиборы).
    inline_subckts: set[str] = set(parsed.subckts)

    for inc in parsed.top_includes:
        lib = _load_lib(inc)
        all_models.update(lib.top_models)
        includes.extend(lib.includes)
        for sname, sdef in lib.subckts.items():
            if sname not in subckts:
                subckts[sname] = sdef

    node_set: set[str] = {"0"}
    node_list: list[str] = ["0"]
    elements: list[Element] = []

    def add_node(name: str) -> None:
        if name not in node_set:
            node_set.add(name)
            node_list.append(name)

    def resolve_node(n: str, prefix: str, port_map: dict[str, str]) -> str:
        if n == "0":
            return "0"
        if n in port_map:
            return port_map[n]
        if prefix:
            g = prefix + n
            add_node(g)
            return g
        add_node(n)
        return n

    def process(elts: list, prefix: str, port_map: dict[str, str]) -> None:
        from rcad.core.netlist import SubcktDef

        for el in elts:
            if el.card == "X" and el.model and el.model in inline_subckts:
                sc: SubcktDef = subckts[el.model]
                new_prefix = prefix + el.name + "."
                sub_port_map: dict[str, str] = {}
                for idx, port in enumerate(sc.ports):
                    if idx < len(el.nodes):
                        g = resolve_node(el.nodes[idx], prefix, port_map)
                        # Иерархическое имя узла экземпляра (например X1.X2.mid)
                        inst_node = el.nodes[idx]
                        if inst_node != "0":
                            add_node(new_prefix + inst_node)
                    else:
                        g = new_prefix + port
                        add_node(g)
                    sub_port_map[port] = g
                process(sc.elements, new_prefix, sub_port_map)
            else:
                new_nodes = [resolve_node(n, prefix, port_map) for n in el.nodes]
                ename = (prefix + el.name) if prefix else el.name
                elements.append(
                    Element(
                        card=el.card,
                        name=ename,
                        nodes=new_nodes,
                        params=dict(el.params),
                        model=el.model,
                    )
                )

    process(parsed.top_elements, "", {})

    return FlatCircuit(
        name=parsed.top_name,
        nodes=node_list,
        elements=elements,
        models=all_models,
        directives=list(parsed.directives),
        initial_conditions=dict(parsed.initial_conditions),
        includes=list(dict.fromkeys(includes)),
    )
