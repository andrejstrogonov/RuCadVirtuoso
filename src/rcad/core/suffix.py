"""SPICE-суффиксы и парсинг чисел (дублирует логику schemas.analysis для ядра).

Суффиксы: T, G, MEG, K, M, U, N, P, F. Строки-выражения (SIN, PULSE) возвращаются как есть.
"""

from __future__ import annotations

import re

_SUFFIX = {
    "T": 1e12, "G": 1e9, "MEG": 1e6, "K": 1e3, "M": 1e-3,
    "U": 1e-6, "N": 1e-9, "P": 1e-12, "F": 1e-15,
}

_NUM_RE = re.compile(r"^([+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?)([a-zA-Z]*)$")


def parse_number(text: str) -> float | str:
    """Разобрать SPICE-число с суффиксом.

    Число → float; строка-выражение (SIN(...), PULSE(...), "") → как есть.
    """
    text = text.strip()
    if not text:
        return ""
    m = _NUM_RE.match(text)
    if not m:
        return text
    value = float(m.group(1))
    suffix = m.group(4)
    if suffix and suffix.upper() in _SUFFIX:
        return value * _SUFFIX[suffix.upper()]
    if suffix:
        return text
    return value


def parse_source_value(text: str) -> str:
    """Вернуть строковое представление значения источника (DC/SIN/PULSE как есть)."""
    return text.strip()


def suffix_float(text: str) -> float:
    """Число с суффиксом в float (без возврата строк)."""
    result = parse_number(text)
    if isinstance(result, str):
        raise ValueError(f"нечисловое значение {text!r}")
    return result
