"""Простая шина событий UI (необязательная): подписка/публикация строковых событий."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any


class EventHub:
    """Лёгкая шина: виджеты оповещают без прямых ссылок друг на друга.

    Используется для сценарных хуков (например, UI-смок) и не заменяет
    Qt-сигналы, которыми связаны компоненты MainWindow.
    """

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[Any], None]]] = defaultdict(list)

    def on(self, event: str, callback: Callable[[Any], None]) -> None:
        self._subs[event].append(callback)

    def emit(self, event: str, payload: Any = None) -> None:
        for callback in list(self._subs[event]):
            callback(payload)
