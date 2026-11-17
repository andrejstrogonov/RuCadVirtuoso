"""Device models with IV curves, pulse response, and spiking logic.

ТЗ п. 9.1–9.4, FR-DEV-001. Модели включают:
- Базовый класс Device с абстрактными методами для IV-характеристик,
  импульсной реакции (evaluate_pulses) и спайкинг-логики (update_spiking_state).
- Конкретные реализации: Memristor, Neuristor, MOSFET.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class IVCurveProvider(Protocol):
    """Протокол для устройств с IV-характеристиками."""

    def iv_curve(self, voltage: float, params: dict | None = None) -> float:
        """Calculate current for a given voltage."""
        ...


@runtime_checkable
class PulseResponseProvider(Protocol):
    """Протокол для устройств с импульсной реакцией."""

    def evaluate_pulses(
        self,
        pulses: list[tuple[float, float, float]],
        params: dict | None = None,
    ) -> list[float]:
        """
        Evaluate device response to a sequence of pulses.

        Args:
            pulses: List of (start_time, end_time, amplitude) tuples.
            params: Optional device-specific parameters.

        Returns:
            List of state variable values after each pulse.
        """
        ...


@runtime_checkable
class SpikingStateProvider(Protocol):
    """Протокол для нейристорных устройств со спайкинг-состоянием."""

    def update_spiking_state(
        self,
        voltage: float,
        dt: float,
        params: dict | None = None,
    ) -> tuple[float, bool]:
        """
        Update spiking state and return spike flag.

        Args:
            voltage: Current voltage across the device.
            dt: Time step.
            params: Optional device-specific parameters.

        Returns:
            Tuple of (membrane_potential, spike_occurred).
        """
        ...


@dataclass
class StateVariable:
    """State variable tracking for time-varying devices."""

    value: float
    min_val: float = 0.0
    max_val: float = 1.0
    _history: list[float] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._history = [self.value]

    def update(self, new_value: float) -> None:
        """Update state variable with clamping and history tracking."""
        self.value = max(self.min_val, min(self.max_val, new_value))
        self._history.append(self.value)

    @property
    def history(self) -> list[float]:
        return list(self._history)


class Device(ABC):
    """Базовый класс для всех моделей устройств.

    Определяет контракт для:
    - Статических IV-характеристик (iv_curve)
    - Импульсной реакции (evaluate_pulses)
    - Спайкинг-логики (update_spiking_state)
    - Управления состоянием (state, reset_state)
    """

    def __init__(self, params: dict | None = None) -> None:
        self.params = params or {}
        self._state = StateVariable(value=0.0)

    # --- IV Curve ---

    @abstractmethod
    def iv_curve(self, voltage: float) -> float:
        """Calculate current at a given voltage (static IV curve)."""
        ...

    @abstractmethod
    def iv_curve_batch(self, voltages: list[float]) -> list[float]:
        """Calculate currents for a batch of voltages."""
        ...

    # --- Pulse Response ---

    @abstractmethod
    def evaluate_pulses(
        self,
        pulses: list[tuple[float, float, float]],
    ) -> list[float]:
        """
        Evaluate device response to a sequence of pulses.

        Args:
            pulses: List of (start_time, end_time, amplitude) tuples.

        Returns:
            List of state variable values after each pulse.
        """
        ...

    # --- Spiking Logic ---

    @abstractmethod
    def update_spiking_state(
        self,
        voltage: float,
        dt: float,
    ) -> tuple[float, bool]:
        """
        Update spiking state and return spike flag.

        Args:
            voltage: Current voltage across the device.
            dt: Time step.

        Returns:
            Tuple of (membrane_potential, spike_occurred).
        """
        ...

    # --- State Management ---

    @property
    def state(self) -> float:
        """Current state variable value."""
        return self._state.value

    def reset_state(self) -> None:
        """Reset state variable to initial value."""
        self._state.value = 0.0
        self._state._history = [0.0]

    def get_history(self) -> list[float]:
        """Return state variable history."""
        return self._state.history
class Resistor(Device):
    """Simple resistor model."""

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self._R = float(self.params.get("R", 1e3))

    def iv_curve(self, voltage: float) -> float:
        """Calculate current at a given voltage."""
        return voltage / self._R if self._R != 0 else 0.0

    def iv_curve_batch(self, voltages: list[float]) -> list[float]:
        """Calculate currents for a batch of voltages."""
        return [self.iv_curve(v) for v in voltages]

    def evaluate_pulses(self, pulses: list[tuple[float, float, float]]) -> list[float]:
        """Evaluate resistor response to a sequence of pulses."""
        results = []
        for t_start, t_end, amplitude in pulses:
            results.append(self.iv_curve(amplitude))
        return results

    def update_spiking_state(self, voltage: float, dt: float) -> tuple[float, bool]:
        """Resistor does not spike; return current state."""
        return self.iv_curve(voltage), False


class Capacitor(Device):
    """Simple capacitor model."""

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self._C = float(self.params.get("C", 1e-12))
        self._V = 0.0

    def iv_curve(self, voltage: float) -> float:
        """Calculate current at a given voltage."""
        self._V = voltage
        return 0.0

    def iv_curve_batch(self, voltages: list[float]) -> list[float]:
        """Calculate currents for a batch of voltages."""
        return [0.0] * len(voltages)

    def evaluate_pulses(self, pulses: list[tuple[float, float, float]]) -> list[float]:
        """Evaluate capacitor response to a sequence of pulses."""
        results = []
        for t_start, t_end, amplitude in pulses:
            self._V = amplitude
            results.append(self._V)
        return results

    def update_spiking_state(self, voltage: float, dt: float) -> tuple[float, bool]:
        """Capacitor does not spike; return current state."""
        self._V = voltage
        return self._V, False
class MOSFET(Device):
    """MOSFET model (SPICE-level).

    Parameters:
        W, L: Channel dimensions
        VTO: Threshold voltage
        KP: Transconductance
        GAMMA: Body effect coefficient
        PHI: Surface potential
        LAMBDA: Channel length modulation
        TOX: Oxide thickness
        CGSO, CGDO, CGBO: Overlap capacitances
        RD, RS: Drain/Source resistances
    """

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self._W = float(self.params.get("W", 1e-6))
        self._L = float(self.params.get("L", 1e-6))
        self._VTO = float(self.params.get("VTO", 0.5))
        self._KP = float(self.params.get("KP", 1e-4))
        self._GAMMA = float(self.params.get("GAMMA", 0.5))
        self._PHI = float(self.params.get("PHI", 0.5))
        self._LAMBDA = float(self.params.get("LAMBDA", 0.02))
        self._TOX = float(self.params.get("TOX", 1e-8))
        self._CGSO = float(self.params.get("CGSO", 0.0))
        self._CGDO = float(self.params.get("CGDO", 0.0))
        self._CGBO = float(self.params.get("CGBO", 0.0))
        self._RD = float(self.params.get("RD", 0))
        self._RS = float(self.params.get("RS", 0))

    def iv_curve(self, voltage: float) -> float:
        """Calculate current at a given drain voltage (gate assumed ON)."""
        VGS = 1.0
        VDS = voltage
        if VDS <= 0:
            return 0.0
        Veff = VGS - self._VTO
        if VDS <= Veff:
            Id = self._KP * (self._W / self._L) * (Veff * VDS - VDS ** 2 / 2) * (1 + self._LAMBDA * VDS)
        else:
            Id = self._KP * (self._W / self._L) * Veff ** 2 / 2 * (1 + self._LAMBDA * VDS)
        return Id

    def iv_curve_batch(self, voltages: list[float]) -> list[float]:
        """Calculate currents for a batch of voltages."""
        return [self.iv_curve(v) for v in voltages]

    def evaluate_pulses(self, pulses: list[tuple[float, float, float]]) -> list[float]:
        """Evaluate MOSFET response to a sequence of pulses."""
        results = []
        for t_start, t_end, amplitude in pulses:
            results.append(self.iv_curve(amplitude))
        return results

    def update_spiking_state(self, voltage: float, dt: float) -> tuple[float, bool]:
        """MOSFET does not spike; return current state."""
        return self.iv_curve(voltage), False
class Neuristor(Device):
    """Neuristor model with spiking behavior (LIF neuron emulation).

    Parameters:
        R_on: On-state resistance
        R_off: Off-state resistance
        V_set: Set voltage threshold
        V_hold: Hold voltage
        t_delay: Delay time
        t_relax: Relaxation time
        C_par: Parasitic capacitance
    """

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self._R_on = float(self.params.get("R_on", 5e3))
        self._R_off = float(self.params.get("R_off", 5e5))
        self._V_set = float(self.params.get("V_set", 1.2))
        self._V_hold = float(self.params.get("V_hold", 0.4))
        self._t_delay = float(self.params.get("t_delay", 1e-8))
        self._t_relax = float(self.params.get("t_relax", 5e-8))
        self._C_par = float(self.params.get("C_par", 2e-12))
        self._V_mem = 0.0

    def iv_curve(self, voltage: float) -> float:
        """Calculate current at a given voltage."""
        R = self._R_on if abs(self._V_mem) >= self._V_set else self._R_off
        return voltage / R if R != 0 else 0.0

    def iv_curve_batch(self, voltages: list[float]) -> list[float]:
        """Calculate currents for a batch of voltages."""
        return [self.iv_curve(v) for v in voltages]

    def evaluate_pulses(self, pulses: list[tuple[float, float, float]]) -> list[float]:
        """Evaluate neuristor response to a sequence of pulses."""
        results = []
        for t_start, t_end, amplitude in pulses:
            dt = t_end - t_start
            current = self.iv_curve(amplitude)
            self._V_mem += (current * dt) / self._C_par
            spike = abs(self._V_mem) >= self._V_set
            if spike:
                self._V_mem = self._V_hold
            elif not spike:
                self._V_mem *= (1 - dt / self._t_delay)
            self._state.update(self._V_mem)
            results.append(self._V_mem)
        return results

    def update_spiking_state(self, voltage: float, dt: float) -> tuple[float, bool]:
        """Update spiking state (Leaky Integrate-and-Fire behavior)."""
        R = self._R_on if self._V_mem >= self._V_set else self._R_off
        I_in = voltage / R if R != 0 else 0.0
        dV_mem = (I_in / self._C_par - self._V_mem / self._t_delay) * dt
        self._V_mem += dV_mem
        spike_occurred = self._V_mem >= self._V_set
        if spike_occurred:
            self._V_mem = self._V_hold
        return self._V_mem, spike_occurred
class MemtransistorGEM(Device):
    """Gate-tunable Epitaxy Memtransistor (GEM) model.

    Parameters:
        w_on, w_off: On/off conductance states
        k_on, k_off: Switching rates
        alpha_on, alpha_off: Exponential coefficients
        s_on, s_off: Saturation levels
        beta_on, beta_off: Threshold parameters
        v_on, v_off: Voltage thresholds
        r_on, r_off: On/off resistances
        mu: Mobility
        w_init: Initial state
    """

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self._w_on = float(self.params.get("w_on", 1.0))
        self._w_off = float(self.params.get("w_off", 0.0))
        self._k_on = float(self.params.get("k_on", 1e6))
        self._k_off = float(self.params.get("k_off", 1e6))
        self._alpha_on = float(self.params.get("alpha_on", 1e9))
        self._alpha_off = float(self.params.get("alpha_off", 1e9))
        self._s_on = float(self.params.get("s_on", 1e6))
        self._s_off = float(self.params.get("s_off", 1e6))
        self._beta_on = float(self.params.get("beta_on", 0.0))
        self._beta_off = float(self.params.get("beta_off", 0.0))
        self._v_on = float(self.params.get("v_on", 0.5))
        self._v_off = float(self.params.get("v_off", 0.5))
        self._r_on = float(self.params.get("r_on", 1e3))
        self._r_off = float(self.params.get("r_off", 1e6))
        self._mu = float(self.params.get("mu", 1.0))
        self._w_init = float(self.params.get("w_init", 0.0))
        self._state.value = self._w_init

    def iv_curve(self, voltage: float) -> float:
        """Calculate current at a given voltage."""
        w = self._state.value
        R = self._r(w)
        return voltage / R if R != 0 else 0.0

    def iv_curve_batch(self, voltages: list[float]) -> list[float]:
        """Calculate currents for a batch of voltages."""
        return [self.iv_curve(v) for v in voltages]

    def _r(self, w: float) -> float:
        """Calculate effective resistance."""
        if w == 0.0:
            return self._r_off
        if w == 1.0:
            return self._r_on
        return (1 - w) * self._r_off + w * self._r_on

    def evaluate_pulses(self, pulses: list[tuple[float, float, float]]) -> list[float]:
        """Evaluate GEM response to a sequence of pulses."""
        results = []
        for t_start, t_end, amplitude in pulses:
            dw = self._dw(amplitude, t_end - t_start)
            new_w = self._state.value + dw
            self._state.update(new_w)
            results.append(self._state.value)
        return results

    def _dw(self, voltage: float, dt: float) -> float:
        """Calculate state change."""
        if voltage > self._v_on:
            return (
                dt
                * self._k_on
                * (1 - (self._state.value - self._w_on) ** 2)
                * self._alpha_on
                / (1 + self._state.value * self._s_on)
            )
        elif voltage < -self._v_off:
            return (
                dt
                * self._k_off
                * (1 - (self._state.value + self._w_off) ** 2)
                * self._alpha_off
                / (1 + (1 - self._state.value) * self._s_off)
            )
        return 0.0

    def update_spiking_state(self, voltage: float, dt: float) -> tuple[float, bool]:
        """GEM does not spike; return current state."""
        return self._state.value, False

class Memristor(Device):
    """Memristor model (Yakopcic / Strukov variants).

    Parameters:
        a1, a2: Width parameters for set/reset
        b: Conductance slope
        Vp: Positive switching voltage
        Vn: Negative switching voltage
        Ap, An: Switching magnitude parameters
        xp, xn: Boundary parameters
        alphap, alphan: Exponential coefficients
        xo: Initial state
        eta: Symmetry parameter
    """

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self._a1 = float(self.params.get("a1", 0.17))
        self._a2 = float(self.params.get("a2", 0.17))
        self._b = float(self.params.get("b", 0.05))
        self._Vp = float(self.params.get("Vp", 0.65))
        self._Vn = float(self.params.get("Vn", 0.56))
        self._Ap = float(self.params.get("Ap", 4000))
        self._An = float(self.params.get("An", 4000))
        self._xp = float(self.params.get("xp", 0.3))
        self._xn = float(self.params.get("xn", 0.3))
        self._alphap = float(self.params.get("alphap", 3))
        self._alphan = float(self.params.get("alphan", 3))
        self._xo = float(self.params.get("xo", 0.1))
        self._eta = float(self.params.get("eta", 1))
        self._state.value = self._xo

    def iv_curve(self, voltage: float) -> float:
        """Calculate current at a given voltage using Yakopcic model."""
        w = self._state.value
        R = self._r(voltage, w)
        return voltage / R if R != 0 else 0.0

    def iv_curve_batch(self, voltages: list[float]) -> list[float]:
        """Calculate currents for a batch of voltages."""
        return [self.iv_curve(v) for v in voltages]

    def _r(self, voltage: float, w: float) -> float:
        """Calculate resistance."""
        if w == 0.0:
            return self._r_off()
        if w == 1.0:
            return self._r_on()
        R = (1 - w) * self._r_off() + w * self._r_on()
        return R

    def _r_on(self) -> float:
        return 1e3  # 1kOhm default

    def _r_off(self) -> float:
        return 1e6  # 1MOhm default

    def evaluate_pulses(self, pulses: list[tuple[float, float, float]]) -> list[float]:
        """Evaluate memristor response to a sequence of pulses."""
        results = []
        for t_start, t_end, amplitude in pulses:
            dt = t_end - t_start
            current = self.iv_curve(amplitude)
            dw = self._dw(dt, current, amplitude)
            new_w = self._state.value + dw
            self._state.update(new_w)
            results.append(self._state.value)
        return results

    def _dw(self, dt: float, current: float, voltage: float) -> float:
        """Calculate state change."""
        if voltage > 0:
            return self._set(dt, current, voltage)
        return self._reset(dt, current, voltage)

    def _set(self, dt: float, current: float, voltage: float) -> float:
        return dt * current * self._a1 * (1 - (self._state.value - self._xp) ** 2)

    def _reset(self, dt: float, current: float, voltage: float) -> float:
        return dt * current * self._a2 * (1 - (self._state.value + self._xn) ** 2)

    def update_spiking_state(self, voltage: float, dt: float) -> tuple[float, bool]:
        """Memristor does not spike; return current state without change."""
        return self._state.value, False

