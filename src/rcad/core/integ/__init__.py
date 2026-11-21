"""Трапецеидальная интеграция для TRAN (rcad.core.integ).

Управляет шагами времени, точками разрыва источников и отслеживанием отказов шага.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TRANIntegrator:
    tstart: float
    tstop: float
    tstep: float
    tmax: float | None = None
    first_step_fraction: float = 0.01

    def __post_init__(self) -> None:
        if self.tmax is None:
            self.tmax = (self.tstop - self.tstart) / 100.0
        self.current_t = self.tstart
        self.step_rejections = 0
        self.time_points: list[float] = [self.tstart]
        self._breakpoints: list[float] = []
        self._first_step_done = False

    def add_breakpoint(self, t: float) -> None:
        """Добавить точку разрыва (фронт impulses), на которую нужно попасть точно."""
        if self.tstart <= t <= self.tstop:
            self._breakpoints.append(t)
        self._breakpoints.sort()

    def next_step(self) -> float | None:
        """Вернуть следующий шаг времени или None если конец."""
        if self.current_t >= self.tstop - 1e-15:
            return None
        # Первый шаг делаем короче для точности начальных условий
        if not self._first_step_done:
            self._first_step_done = True
            h = min(self.tstep, self.tmax) * self.first_step_fraction
        else:
            h = min(self.tstep, self.tmax)
        remaining = self.tstop - self.current_t
        h = min(h, remaining)

        # Проверяем точки разрыва
        for bp in self._breakpoints:
            if self.current_t < bp - 1e-15 and self.current_t + h > bp + 1e-15:
                h = bp - self.current_t
                break

        return h

    def advance(self, h: float) -> None:
        self.current_t += h
        self.time_points.append(self.current_t)

    def reject_step(self) -> None:
        self.step_rejections += 1

    @property
    def times(self) -> list[float]:
        return list(self.time_points)
