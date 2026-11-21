"""Разбор SPICE-netlist текста (rcad.core.netlist).

Предоставляет parse() — разбор текста нетлиста в иерархическое представление
с обнаружен cycles .subckt, и flatten() — развертывание иерархии в плоский
список элементов с иерархическими именами узлов.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Self

from rcad.core.suffix import parse_number
from rcad.diagnostics import NetlistError

_ELEMENT_RE = re.compile(r"^\s*([RCLVIEGFHDQBMX])([A-Za-z0-9_$]+)\s+(.*)$")
_DIRECTIVE_RE = re.compile(r"^\s*\.\w+")
_INCLUDE_RE = re.compile(r'^\s*\.include\s+"([^"]+)"\s*$', re.IGNORECASE)
_SUBCKT_RE = re.compile(r"^\s*\.subckt\s+(\S+)(.*)$", re.IGNORECASE)
_ENDS_RE = re.compile(r"^\s*\.ends", re.IGNORECASE)
_MODEL_RE = re.compile(r"^\s*\.model\s+(\S+)\s+(\S+)(.*)$", re.IGNORECASE)
_IC_RE = re.compile(r"^\s*\.ic\s+(.*)$", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    """Разбиение строки с учётом скобочных групп (SIN(0 1 1), PULSE(...))."""
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


def _expand_continuations(lines: list[str]) -> list[str]:
    """Собрать continuation-строки (+ …) в одну."""
    out: list[str] = []
    for line in lines:
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


@dataclass
class ModelDef:
    name: str
    type: str
    params: dict[str, float | str] = field(default_factory=dict)


@dataclass
class Element:
    card: str
    name: str
    nodes: list[str]
    params: dict[str, float | str]
    model: str | None = None  # для M/X: имя модели


@dataclass
class SubcktDef:
    name: str
    ports: list[str]
    elements: list[Element] = field(default_factory=list)
    models: dict[str, ModelDef] = field(default_factory=dict)
    includes: list[str] = field(default_factory=list)


@dataclass
class ParsedNetlist:
    top_name: str
    top_elements: list[Element]
    top_models: dict[str, ModelDef]
    top_includes: list[str]
    subckts: dict[str, SubcktDef]
    directives: list[str] = field(default_factory=list)
    initial_conditions: dict[str, float] = field(default_factory=dict)
    includes: list[str] = field(default_factory=list)


def parse(text: str) -> ParsedNetlist:
    """Разбор текста нетлиста.

    Выбрасывает NetlistError при циклических ссылках .subckt, некорректных
    строках элементов или отсутствующих имен.
    """
    lines = _expand_continuations(text.splitlines())

    top_body: list[str] = []
    subckt_map: dict[str, tuple[list[str], list[str]]] = {}
    active: str | None = None
    current_ports: list[str] = []

    directives: list[str] = []
    initial_conditions: dict[str, float] = {}
    top_models: dict[str, ModelDef] = {}
    top_includes: list[str] = []

    for raw_line in lines:
        if not raw_line or raw_line.startswith("*"):
            continue
        lower = raw_line.lower()

        m = _INCLUDE_RE.match(raw_line)
        if m:
            (top_includes if active is None else []).append(m.group(1))
            continue

        if lower.startswith(".subckt"):
            tokens = raw_line.split()
            if len(tokens) < 2:
                raise NetlistError("не указано имя .subckt")
            active = tokens[1]
            current_ports = tokens[2:]
            subckt_map[active] = (current_ports, [])
            continue
        if lower.startswith(".ends"):
            if active is not None:
                active = None
            continue
        if active is not None:
            subckt_map[active][1].append(raw_line)
            continue

        # top-level
        if lower.startswith((".tran", ".dc", ".ac", ".op", ".end")):
            directives.append(raw_line.strip())
            continue
        mm = _MODEL_RE.match(raw_line)
        if mm:
            name, rtype, rest = mm.group(1), mm.group(2), mm.group(3)
            params: dict[str, float | str] = {}
            for tok in _tokenize(rest):
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    params[k.strip()] = parse_number(v.strip())
            top_models[name] = ModelDef(name=name, type=rtype, params=params)
            continue
        im = _IC_RE.match(raw_line)
        if im:
            for pair in _tokenize(im.group(1)):
                if "=" in pair:
                    node, val = pair.split("=", 1)
                    node = node.strip()
                    # Strip V(...) wrapper: V(out) -> out
                    if node.startswith("V(") and node.endswith(")"):
                        node = node[2:-1]
                    initial_conditions[node] = parse_number(val.strip())  # type: ignore[arg-type]
            continue
        top_body.append(raw_line)

    # Build subckt defs
    subckts: dict[str, SubcktDef] = {}
    for name, (ports, body) in subckt_map.items():
        elements: list[Element] = []
        models: dict[str, ModelDef] = {}
        includes: list[str] = []
        for line in body:
            if not line or line.startswith("*"):
                continue
            l = line.lower()
            if l.startswith(".include"):
                im = _INCLUDE_RE.match(line)
                if im:
                    includes.append(im.group(1))
                continue
            if l.startswith((".tran", ".dc", ".ac", ".op", ".end", ".model", ".ic")):
                if l.startswith(".model"):
                    mm = _MODEL_RE.match(line)
                    if mm:
                        mname, rtype, rest = mm.group(1), mm.group(2), mm.group(3)
                        params: dict[str, float | str] = {}
                        for tok in _tokenize(rest):
                            if "=" in tok:
                                k, v = tok.split("=", 1)
                                params[k.strip()] = parse_number(v.strip())
                        models[mname] = ModelDef(name=mname, type=rtype, params=params)
                continue
            em = _ELEMENT_RE.match(line)
            if em:
                elements.append(_build_element(em))
        subckts[name] = SubcktDef(name=name, ports=ports, elements=elements, models=models, includes=includes)

    # Top-level elements
    top_elements: list[Element] = []
    for line in top_body:
        if not line or line.startswith("*"):
            continue
        em = _ELEMENT_RE.match(line)
        if em:
            top_elements.append(_build_element(em))

    # Cycle detection via DFS on subckt references
    _detect_cycles(subckts, top_elements)

    return ParsedNetlist(
        top_name="top",
        top_elements=top_elements,
        top_models=top_models,
        top_includes=top_includes,
        subckts=subckts,
        directives=directives,
        initial_conditions=initial_conditions,
        includes=list(top_includes),
    )


_SOURCE_KEYWORDS = {"DC", "AC", "SIN", "PULSE", "EXP", "SFFM", "PWL", "AM"}


def _looks_numeric(token: str) -> bool:
    return bool(re.fullmatch(r"[+-]?\d+\.?\d*([eE][+-]?\d+)?[a-zA-Z]*", token))


def _looks_function(token: str) -> bool:
    return "(" in token and token.rstrip().endswith(")")


def _parse_source_params(tokens: list[str], params: dict) -> None:
    """Разобрать параметры источника из оставшихся токов."""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        upper = tok.upper()
        if _looks_function(tok):
            key = tok.split("(")[0].upper()
            params[key] = tok
            i += 1
        elif upper in ("DC", "AC") and i + 1 < len(tokens):
            params[upper] = tokens[i + 1]
            i += 2
        else:
            i += 1


def _parse_key_value_params(tokens: list[str], params: dict) -> None:
    """Разобрать параметры вида key=value из списка токенов."""
    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            params[k.strip()] = v.strip()


def _build_element(em: re.Match) -> Element:
    card = em.group(1).upper()
    name = card + em.group(2)  # полное имя: V1, R1, и т.п.
    rest = em.group(3).strip()
    tokens = _tokenize(rest)
    nodes: list[str] = []
    params: dict[str, float | str] = {}
    model: str | None = None

    if card == "M":
        # Mname drain gate source bulk modelname W=... L=...
        if len(tokens) >= 4:
            nodes = tokens[:4]
        if len(tokens) > 4:
            model = tokens[4]
            _parse_key_value_params(tokens[5:], params)
    elif card == "X":
        # Xname node1 node2 ... subcktname param=...
        # Имя подсхемы — последний токен без '='
        model_idx = None
        for i in range(len(tokens) - 1, -1, -1):
            if "=" not in tokens[i]:
                model_idx = i
                break
        if model_idx is not None:
            model = tokens[model_idx]
            nodes = tokens[:model_idx]
            _parse_key_value_params(tokens[model_idx + 1 :], params)
        else:
            nodes = tokens
    elif card in ("R", "C", "L"):
        # последний числовой токен — значение
        if tokens and _looks_numeric(tokens[-1]):
            params[card] = parse_number(tokens[-1])
            nodes = tokens[:-1]
        else:
            nodes = tokens
    elif card in ("V", "I"):
        # первые два токена — узлы, остальные — параметры источника
        nodes = tokens[:2] if len(tokens) >= 2 else tokens
        _parse_source_params(tokens[2:], params)
    else:
        nodes = tokens

    return Element(card=card, name=name, nodes=nodes, params=params, model=model)


def _detect_cycles(subckts: dict[str, SubcktDef], top_elements: list[Element]) -> None:
    """Обнаружение циклических ссылок .subckt (DFS, белый-серый-черный)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {name: WHITE for name in subckts}

    def refs(subckt_name: str) -> list[str]:
        out: list[str] = []
        sc = subckts.get(subckt_name)
        if sc is None:
            return out
        for el in sc.elements:
            if el.card == "X" and el.model in subckts:
                out.append(el.model)
        return out

    def dfs(name: str, path: list[str]) -> None:
        color[name] = GRAY
        path.append(name)
        for ref in refs(name):
            if color.get(ref, WHITE) == GRAY:
                cycle = " → ".join(path + [ref])
                raise NetlistError(f"циклический subckt: {cycle}")
            if color.get(ref, WHITE) == WHITE:
                dfs(ref, path)
        path.pop()
        color[name] = BLACK

    for name in subckts:
        if color[name] == WHITE:
            dfs(name, [])

    # Also check top-level X references to subckts
    for el in top_elements:
        if el.card == "X" and el.model in subckts:
            if color[el.model] == GRAY:
                raise NetlistError(f"циклический subckt: {el.model}")
