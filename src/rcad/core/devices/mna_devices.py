"""Модели приборов для MNA (rcad.core.devices.mna_devices).

Базовый класс DeviceModel и реализации приборов: R, C, L, V, I, M, X.
Каждый прибор знает, как поставить себя в MNA матрицу и обновить состояние.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from rcad.core.suffix import suffix_float


class DeviceModel:
    """Базовый класс прибора для MNA."""

    def __init__(self, params: dict, tstep: float) -> None:
        self.params = dict(params)
        self.tstep = tstep
        self._state: dict[str, float] = {}

    def stamp(self, ctx, name: str, nodes: list[str], initial_conditions: dict, solution: np.ndarray | None = None) -> None:
        """Поставить прибор в MNA матрицы (вызывается на каждой итерации Ньютона)."""
        raise NotImplementedError

    def get_state(self) -> dict[str, float]:
        """Вернуть внутренние переменные состояния для вывода."""
        return dict(self._state)

    def update_state(self, solution: np.ndarray, node_map: dict[str, int], t: float, dt: float | None = None) -> None:
        """Обновить состояние после сходимости Ньютона."""
        pass

    def get_output(self, port: str, solution: np.ndarray, node_map: dict[str, int]) -> float:
        """Вернуть значение выхода (id, vgs, и т.п.)."""
        return 0.0


# =====================================================================
# Линейные приборы
# =====================================================================

class Resistor(DeviceModel):
    def stamp(self, ctx, name, nodes, initial_conditions, solution=None) -> None:
        r = suffix_float(str(self.params.get("R", 1e3)))
        if r == 0:
            return
        g = 1.0 / r
        ctx.add_conductance(nodes[0], nodes[1], g)


class Capacitor(DeviceModel):
    def stamp(self, ctx, name, nodes, initial_conditions, solution=None) -> None:
        c = suffix_float(str(self.params.get("C", 1e-12)))
        v_prev = 0.0
        i_prev = 0.0
        v_key = f"{name}.v"
        i_key = f"{name}.i"
        if v_key in ctx.prev_states:
            v_prev = float(ctx.prev_states[v_key])
        if i_key in ctx.prev_states:
            i_prev = float(ctx.prev_states[i_key])
        else:
            n1, n2 = nodes[0], nodes[1]
            v1 = float(initial_conditions.get(n1, 0.0))
            v2 = float(initial_conditions.get(n2, 0.0))
            v_prev = v1 - v2
        if ctx.first_step:
            g_eq = c / ctx.tstep
            i_hist = g_eq * v_prev
        else:
            g_eq = 2.0 * c / ctx.tstep
            i_hist = g_eq * v_prev + i_prev
        ctx.add_capacitor_companion(nodes[0], nodes[1], c, v_prev, i_prev)
        self._state["v"] = v_prev
        self._state["i"] = i_prev
        self._state["g_eq"] = g_eq
        self._state["i_hist"] = i_hist

    def update_state(self, solution, node_map, t, dt=None) -> None:
        v = self._node_voltage(solution, node_map)
        g_eq = self._state.get("g_eq")
        i_hist = self._state.get("i_hist")
        if g_eq is None:
            c = suffix_float(str(self.params.get("C", 1e-12)))
            step = dt if dt is not None else self.tstep
            g_eq = 2.0 * c / step
            i_hist = g_eq * self._state.get("v", 0.0) + self._state.get("i", 0.0)
        i = g_eq * v - i_hist
        self._state["v"] = v
        self._state["i"] = i

    def _node_voltage(self, solution, node_map):
        if not hasattr(self, 'nodes') or not self.nodes:
            return 0.0
        n1, n2 = self.nodes[0], self.nodes[1]
        v1 = solution[node_map[n1]] if n1 in node_map else 0.0
        v2 = solution[node_map[n2]] if n2 in node_map else 0.0
        return v1 - v2


class Inductor(DeviceModel):
    def stamp(self, ctx, name, nodes, initial_conditions, solution=None) -> None:
        l = suffix_float(str(self.params.get("L", 1e-6)))
        i_prev = 0.0
        v_prev = 0.0
        i_key = f"{name}.i"
        v_key = f"{name}.v"
        if i_key in ctx.prev_states:
            i_prev = float(ctx.prev_states[i_key])
        if v_key in ctx.prev_states:
            v_prev = float(ctx.prev_states[v_key])
        ctx.add_inductor_companion(nodes[0], nodes[1], l, i_prev, v_prev)
        self._state["i"] = i_prev
        self._state["v"] = v_prev


# =====================================================================
# Источники
# =====================================================================

class VoltageSource(DeviceModel):
    def __init__(self, params, tstep) -> None:
        super().__init__(params, tstep)
        self.dc = 0.0
        self.func_type = None
        self.func_params = ()
        self._parse_source()

    def _parse_source(self) -> None:
        for key, value in self.params.items():
            k = key.upper()
            if k == "DC":
                self.dc = suffix_float(str(value))
            elif k in ("SIN", "PULSE", "EXP", "SFFM", "PWL", "AM"):
                self.func_type = k
                self.func_params = value if isinstance(value, str) else str(value)

    def _value_at(self, t: float) -> float:
        if self.func_type is None:
            return self.dc
        if self.func_type == "SIN":
            return self._sin(t)
        if self.func_type == "PULSE":
            return self._pulse(t)
        return self.dc

    def _sin(self, t: float) -> float:
        # SIN(offset amplitude freq delay damping phase)
        p = self._parse_numbers(self.func_params)
        voff = p[0] if len(p) > 0 else 0.0
        vamp = p[1] if len(p) > 1 else 0.0
        freq = p[2] if len(p) > 2 else 0.0
        delay = p[3] if len(p) > 3 else 0.0
        df = p[4] if len(p) > 4 else 0.0
        phase = p[5] if len(p) > 5 else 0.0
        if t < delay:
            return voff
        td = t - delay
        return voff + vamp * math.exp(-df * td) * math.sin(2 * math.pi * freq * td + math.radians(phase))

    def _pulse(self, t: float) -> float:
        # PULSE(v1 v2 td tr tf pw per)
        p = self._parse_numbers(self.func_params)
        v1 = p[0] if len(p) > 0 else 0.0
        v2 = p[1] if len(p) > 1 else 0.0
        td = p[2] if len(p) > 2 else 0.0
        tr = p[3] if len(p) > 3 else 0.0
        tf = p[4] if len(p) > 4 else 0.0
        pw = p[5] if len(p) > 5 else 0.0
        per = p[6] if len(p) > 6 else 0.0
        if per <= 0:
            return v1
        tt = t % per
        if tt < td:
            return v1
        tt -= td
        if tt < tr:
            return v1 + (v2 - v1) * tt / tr
        tt -= tr
        if tt < pw:
            return v2
        tt -= pw
        if tt < tf:
            return v2 + (v1 - v2) * tt / tf
        return v1

    @staticmethod
    def _parse_numbers(text: str) -> list[float]:
        nums: list[float] = []
        for tok in str(text).split():
            try:
                nums.append(suffix_float(tok))
            except ValueError:
                nums.append(0.0)
        return nums

    def stamp(self, ctx, name, nodes, initial_conditions, solution=None) -> None:
        # Текущее значение источника
        t = getattr(ctx, 'current_time', 0.0)
        value = self._value_at(t)
        ctx.add_vsource(name, nodes[0], nodes[1], value)

    def get_output(self, port, solution, node_map):
        if port.lower() == "i":
            return self._current(solution, node_map)
        return 0.0

    def _current(self, solution, node_map):
        return 0.0  # будет заполнено решателем из решения


class CurrentSource(DeviceModel):
    def __init__(self, params, tstep) -> None:
        super().__init__(params, tstep)
        self.dc = 0.0
        self.func_type = None
        self.func_params = ""
        for key, value in self.params.items():
            k = key.upper()
            if k == "DC":
                self.dc = suffix_float(str(value))
            elif k in ("PULSE", "SIN", "EXP", "SFFM", "PWL", "AM"):
                self.func_type = k
                self.func_params = value if isinstance(value, str) else str(value)

    def _value_at(self, t: float) -> float:
        if self.func_type is None:
            return self.dc
        vs = VoltageSource({}, self.tstep)
        vs.func_type = self.func_type
        vs.func_params = self.func_params
        vs.dc = self.dc
        return vs._value_at(t)

    def stamp(self, ctx, name, nodes, initial_conditions, solution=None) -> None:
        t = getattr(ctx, 'current_time', 0.0)
        value = self._value_at(t)
        # Ток входит в первый узел, выходит из второго
        ctx.add_current(nodes[0], value)
        ctx.add_current(nodes[1], -value)


# =====================================================================
# MOSFET (Shichman-Hodges)
# =====================================================================

class MOSFET(DeviceModel):
    def __init__(self, params, tstep) -> None:
        super().__init__(params, tstep)
        self.W = suffix_float(str(self.params.get("W", 1e-6)))
        self.L = suffix_float(str(self.params.get("L", 1e-6)))
        self.VTO = suffix_float(str(self.params.get("VTO", 0.5)))
        self.KP = suffix_float(str(self.params.get("KP", 1e-4)))
        self.GAMMA = suffix_float(str(self.params.get("GAMMA", 0.0)))
        self.PHI = suffix_float(str(self.params.get("PHI", 0.0)))
        self.LAMBDA = suffix_float(str(self.params.get("LAMBDA", 0.0)))
        self.is_p = self.params.get("_is_p", False)
        self._vds = 0.0
        self._vgs = 0.0
        self._vbs = 0.0
        self._id = 0.0
        self._gm = 0.0
        self._gds = 0.0
        self._gmbs = 0.0

    def _currents(self, vgs: float, vds: float, vbs: float) -> tuple[float, float, float, float]:
        """Возвращает (Id, gm, gds, gmbs) для заданных напряжений."""
        if self.is_p:
            vgs = -vgs
            vds = -vds
            vbs = -vbs

        vth = self.VTO + self.GAMMA * (math.sqrt(max(self.PHI + vbs, 0.0)) - math.sqrt(max(self.PHI, 0.0)))
        vov = vgs - vth

        if vov <= 0:
            return 0.0, 0.0, 0.0, 0.0

        if vds < vov:
            # Линейная область
            id_ = self.KP * (self.W / self.L) * (vov * vds - vds * vds / 2.0) * (1.0 + self.LAMBDA * vds)
            gm = self.KP * (self.W / self.L) * vds * (1.0 + self.LAMBDA * vds)
            gds = self.KP * (self.W / self.L) * (vov - vds) * (1.0 + self.LAMBDA * vds) + self.KP * (self.W / self.L) * (vov * vds - vds * vds / 2.0) * self.LAMBDA
            gmbs = self.KP * (self.W / self.L) * (vov * vds - vds * vds / 2.0) * (1.0 + self.LAMBDA * vds) * self.GAMMA / (2.0 * math.sqrt(max(self.PHI + vbs, 1e-12)))
        else:
            # Насыщение
            id_ = 0.5 * self.KP * (self.W / self.L) * vov * vov * (1.0 + self.LAMBDA * vds)
            gm = self.KP * (self.W / self.L) * vov * (1.0 + self.LAMBDA * vds)
            gds = 0.5 * self.KP * (self.W / self.L) * vov * vov * self.LAMBDA
            gmbs = 0.5 * self.KP * (self.W / self.L) * vov * vov * (1.0 + self.LAMBDA * vds) * self.GAMMA / (2.0 * math.sqrt(max(self.PHI + vbs, 1e-12)))

        return id_, gm, gds, gmbs

    def stamp(self, ctx, name, nodes, initial_conditions, solution=None) -> None:
        # nodes: [d, g, s, b]
        nd, ng, ns, nb = nodes[0], nodes[1], nodes[2], nodes[3]
        id_node = ctx.node_index(nd)
        ig_node = ctx.node_index(ng)
        is_node = ctx.node_index(ns)
        ib_node = ctx.node_index(nb)

        # Текущие напряжения из решения
        vd = solution[id_node] if solution is not None and id_node is not None else 0.0
        vg = solution[ig_node] if solution is not None and ig_node is not None else 0.0
        vs_ = solution[is_node] if solution is not None and is_node is not None else 0.0
        vb = solution[ib_node] if solution is not None and ib_node is not None else 0.0

        vgs = vg - vs_
        vds = vd - vs_
        vbs = vb - vs_

        id_, gm, gds, gmbs = self._currents(vgs, vds, vbs)
        self._id = id_
        self._vds = vds
        self._vgs = vgs
        self._vbs = vbs
        self._gm = gm
        self._gds = gds
        self._gmbs = gmbs

        # Линеаризация вокруг текущей точки:
        # Id = f(vgs, vds, vbs)
        # dId = gm*d(vgs) + gds*d(vds) + gmbs*d(vbs)
        #     = gm*(dvg - dvs) + gds*(dvd - dvs) + gmbs*(dvb - dvs)
        #     = gm*dvg - gm*dvs + gds*dvd - gds*dvs + gmbs*dvb - gmbs*dvs
        #     = gm*dvg + gds*dvd + gmbs*dvb - (gm + gds + gmbs)*dvs

        # Ток из дренажа в исток: Id leaves d, enters s
        # Линеаризованный ток: Id_eq = Id + gm*(vg-vg0) + gds*(vd-vd0) + gmbs*(vb-vb0) - (gm+gds+gmbs)*(vs-vs0)
        # В MNA: источник тока I_eq = Id - gm*vg - gds*vd - gmbs*vb + (gm+gds+gmbs)*vs
        # Распределён между узлами d, g, s, b

        # currents leaving node:
        # d: Id leaves d
        # g: 0 (gate current = 0)
        # s: -Id enters s (Id leaves s is negative)
        # b: 0 (bulk current = 0 in this model)

        # Linearized: I_d_leaving = Id0 + gm*(vg-vg0) + gds*(vd-vd0) - (gm+gds)* (vs-vs0) ... actually let me use full

        # Conductance matrix stamp for Id(vgs, vds, vbs):
        # dId/dvg = gm, dId/dvd = gds, dId/dvs = -(gm + gds), dId/dvb = gmbs
        # Current source equivalent: I_eq = Id - gm*vg - gds*vd + (gm+gds)*vs - gmbs*vb

        # Conductance terms (current leaving positive node = G * voltage)
        # Node d: +gds*vd - gm*vg + (gm+gds)*vs - gmbs*vb ... wait

        # Let me use the standard approach:
        # I_drain = Id0 + gm*(vg - vg0) + gds*(vd - vd0) + gmbs*(vb - vb0) - (gm+gds)*(vs - vs0)
        # = Id0 - gm*vg0 - gds*vd0 - gmbs*vb0 + (gm+gds)*vs0 + gm*vg + gds*vd + gmbs*vb - (gm+gds)*vs

        I_eq = id_ - gm * vg - gds * vd + (gm + gds) * vs_ + gmbs * vb

        # Stamp conductance:
        # Current leaving drain: I_d = gm*vg + gds*vd - (gm+gds)*vs - gmbs*vb + I_eq
        # So G terms: row d: +gds at vd, -gm at vg, +(gm+gds) at vs, -gmbs at vb
        # Row s: opposite (current entering s = -current leaving d)

        if id_node is not None:
            self._add_g(ctx, id_node, id_node, gds)
            self._add_g(ctx, id_node, ig_node, -gm)
            self._add_g(ctx, id_node, is_node, gm + gds)
            self._add_g(ctx, id_node, ib_node, -gmbs)
            ctx.b[id_node] -= I_eq  # current source equivalent (entering node d)
        if is_node is not None:
            self._add_g(ctx, is_node, id_node, -gds)
            self._add_g(ctx, is_node, ig_node, gm)
            self._add_g(ctx, is_node, is_node, -(gm + gds))
            self._add_g(ctx, is_node, ib_node, gmbs)
            ctx.b[is_node] += I_eq

        # Gate and bulk currents are zero

    def _add_g(self, ctx, n1, n2, g):
        if n1 is None or n2 is None:
            return
        if n1 == n2:
            ctx.G[n1, n1] += g
        else:
            ctx.G[n1, n1] += g
            ctx.G[n2, n2] += g
            ctx.G[n1, n2] -= g
            ctx.G[n2, n1] -= g

    def get_output(self, port, solution, node_map):
        if port.lower() == "id":
            return self._id
        if port.lower() == "vgs":
            return self._vgs
        if port.lower() == "vds":
            return self._vds
        return 0.0

    def get_state(self):
        return {"id": self._id, "vgs": self._vgs, "vds": self._vds, "vbs": self._vbs}


# =====================================================================
# Yakopcic Memristor (X device)
# =====================================================================

class YakopcicMemristor(DeviceModel):
    def __init__(self, params, tstep) -> None:
        super().__init__(params, tstep)
        self.a1 = float(self.params.get("a1", 0.17))
        self.a2 = float(self.params.get("a2", 0.17))
        self.b = float(self.params.get("b", 0.05))
        self.Vp = float(self.params.get("Vp", 0.65))
        self.Vn = float(self.params.get("Vn", 0.56))
        self.Ap = float(self.params.get("Ap", 4000.0))
        self.An = float(self.params.get("An", 4000.0))
        self.xp = float(self.params.get("xp", 0.3))
        self.xn = float(self.params.get("xn", 0.3))
        self.alphap = float(self.params.get("alphap", 3.0))
        self.alphan = float(self.params.get("alphan", 3.0))
        self.xo = float(self.params.get("xo", 0.1))
        self.eta = float(self.params.get("eta", 1.0))
        self.x = self.xo
        self._v = 0.0

    def _current(self, v: float) -> float:
        if v >= 0:
            return self.a1 * self.x * math.sinh(self.b * v)
        return self.a2 * self.x * math.sinh(self.b * v)

    def _conductance(self, v: float) -> float:
        if v >= 0:
            return self.a1 * self.x * self.b * math.cosh(self.b * v)
        return self.a2 * self.x * self.b * math.cosh(self.b * v)

    def stamp(self, ctx, name, nodes, initial_conditions, solution=None) -> None:
        n1, n2 = nodes[0], nodes[1]
        i1 = ctx.node_index(n1)
        i2 = ctx.node_index(n2)

        v = 0.0
        if solution is not None:
            v1 = solution[i1] if i1 is not None else 0.0
            v2 = solution[i2] if i2 is not None else 0.0
            v = v1 - v2
        self._v = v

        g = self._conductance(v)
        i_val = self._current(v)
        I_eq = i_val - g * v  # I = g*v + I_eq → I_eq = I - g*v

        ctx.add_conductance(n1, n2, g)
        if i1 is not None:
            ctx.b[i1] -= I_eq  # current leaving n1 through memristor
        if i2 is not None:
            ctx.b[i2] += I_eq

    def update_state(self, solution, node_map, t, dt=None):
        dt = self.tstep if dt is None else dt
        v = self._v
        x = self.x
        dx = 0.0
        if v >= self.Vp:
            dx = dt * self.Ap * (1.0 - (x - self.xp) ** 2) * self.eta
        elif v <= -self.Vn:
            dx = -dt * self.An * (1.0 - (x + self.xn) ** 2) * self.eta
        x_new = max(0.0, min(1.0, x + dx))
        self.x = x_new
        self._state["x"] = x_new

    def get_output(self, port, solution, node_map):
        if port.lower() == "x":
            return self.x
        if port.lower() == "i":
            return self._current(self._v)
        return 0.0

    def get_state(self):
        return {"x": self.x}


# =====================================================================
# GEM Memtransistor
# =====================================================================

class GEMPMemtransistor(DeviceModel):
    def __init__(self, params, tstep) -> None:
        super().__init__(params, tstep)
        self.w_on = float(self.params.get("w_on", 1.0))
        self.w_off = float(self.params.get("w_off", 0.0))
        self.k_on = float(self.params.get("k_on", 1e-4))
        self.k_off = float(self.params.get("k_off", 1e-4))
        self.alpha_on = float(self.params.get("alpha_on", 4.0))
        self.alpha_off = float(self.params.get("alpha_off", 4.0))
        self.s_on = float(self.params.get("s_on", 2.0))
        self.s_off = float(self.params.get("s_off", 2.0))
        self.v_on = float(self.params.get("v_on", 1.0))
        self.v_off = float(self.params.get("v_off", -1.0))
        self.r_on = float(self.params.get("r_on", 1e3))
        self.r_off = float(self.params.get("r_off", 100e3))
        self.mu = float(self.params.get("mu", 1e-3))
        self.w = float(self.params.get("w_init", 0.5))
        self._vg = 0.0
        self._vds = 0.0

    def _resistance(self, w: float) -> float:
        if w <= 0:
            return self.r_off
        if w >= 1:
            return self.r_on
        return (1 - w) * self.r_off + w * self.r_on

    def _conductance(self, w: float) -> float:
        r = self._resistance(w)
        return 1.0 / r if r != 0 else 0.0

    def _dw(self, vgs: float, dt: float) -> float:
        if vgs > self.v_on:
            return (dt * self.k_on * (1.0 - (self.w - self.w_on) ** 2) * self.alpha_on /
                    (1.0 + self.w * self.s_on))
        if vgs < self.v_off:
            return (dt * self.k_off * (1.0 - (self.w + self.w_off) ** 2) * self.alpha_off /
                    (1.0 + (1.0 - self.w) * self.s_off))
        return 0.0

    def stamp(self, ctx, name, nodes, initial_conditions, solution=None) -> None:
        # nodes: [d, g, s]
        nd, ng, ns = nodes[0], nodes[1], nodes[2]
        id_node = ctx.node_index(nd)
        ig_node = ctx.node_index(ng)
        is_node = ctx.node_index(ns)

        vd = solution[id_node] if id_node is not None else 0.0
        vg = solution[ig_node] if ig_node is not None else 0.0
        vs_ = solution[is_node] if is_node is not None else 0.0

        vgs = vg - vs_
        vds = vd - vs_
        self._vg = vgs
        self._vds = vds

        g = self._conductance(self.w)
        i_val = g * vds
        I_eq = i_val - g * vds

        ctx.add_conductance(nd, ns, g)
        if id_node is not None:
            ctx.b[id_node] -= I_eq
        if is_node is not None:
            ctx.b[is_node] += I_eq
        # Gate: zero current

    def update_state(self, solution, node_map, t, dt=None):
        dt = self.tstep if dt is None else dt
        dw = self._dw(self._vg, dt)
        self.w = max(0.0, min(1.0, self.w + dw))
        self._state["w"] = self.w

    def get_output(self, port, solution, node_map):
        if port.lower() == "w":
            return self.w
        if port.lower() == "ids":
            g = self._conductance(self.w)
            return g * self._vds
        return 0.0

    def get_state(self):
        return {"w": self.w}


# =====================================================================
# Neuristor N1
# =====================================================================

class NeuristorN1(DeviceModel):
    def __init__(self, params, tstep) -> None:
        super().__init__(params, tstep)
        self.R_on = suffix_float(str(self.params.get("R_on", 5e3)))
        self.R_off = suffix_float(str(self.params.get("R_off", 500e3)))
        self.V_set = float(self.params.get("V_set", 1.2))
        self.V_hold = float(self.params.get("V_hold", 0.4))
        self.t_delay = suffix_float(str(self.params.get("t_delay", 10e-9)))
        self.t_relax = suffix_float(str(self.params.get("t_relax", 50e-9)))
        self.C_par = suffix_float(str(self.params.get("C_par", 2e-12)))
        self.R = self.R_off
        self._v_mem = 0.0
        self._fired = False

    def stamp(self, ctx, name, nodes, initial_conditions, solution=None) -> None:
        n1, n2 = nodes[0], nodes[1]
        i1 = ctx.node_index(n1)
        i2 = ctx.node_index(n2)

        v = 0.0
        if solution is not None:
            v1 = solution[i1] if i1 is not None else 0.0
            v2 = solution[i2] if i2 is not None else 0.0
            v = v1 - v2

        g = 1.0 / self.R
        i_val = g * v
        I_eq = i_val - g * v

        ctx.add_conductance(n1, n2, g)
        if i1 is not None:
            ctx.b[i1] -= I_eq
        if i2 is not None:
            ctx.b[i2] += I_eq

        # Паразитная ёмкость между узлами
        if self.C_par > 0:
            ctx.add_capacitor_companion(n1, n2, self.C_par, self._v_mem, 0.0)

    def update_state(self, solution, node_map, t, dt=None):
        dt = self.tstep if dt is None else dt
        i1 = node_map.get(self.nodes[0]) if hasattr(self, 'nodes') and self.nodes else None
        # Schmitt switching
        if abs(self._v_mem) >= self.V_set and not self._fired:
            self.R = self.R_on
            self._v_mem = self.V_hold
            self._fired = True
        elif self._fired:
            self.R = self.R_on
        else:
            self.R = self.R_off
        self._state["R"] = self.R

    def get_output(self, port, solution, node_map):
        if port.lower() == "i":
            return self._v / self.R if self.R != 0 else 0.0
        return 0.0

    def get_state(self):
        return {"R": self.R, "v_mem": self._v_mem}


# =====================================================================
# Neuristor N2
# =====================================================================

class NeuristorN2(DeviceModel):
    def __init__(self, params, tstep) -> None:
        super().__init__(params, tstep)
        self.R_on = suffix_float(str(self.params.get("R_on", 5e3)))
        self.R_off = suffix_float(str(self.params.get("R_off", 500e3)))
        self.V_set = float(self.params.get("V_set", 1.2))
        self.V_hold = float(self.params.get("V_hold", 0.4))
        self.tau_set = suffix_float(str(self.params.get("tau_set", 1e-9)))
        self.tau_relax = suffix_float(str(self.params.get("tau_relax", 5e-9)))
        self.s_init = float(self.params.get("s_init", 0.0))
        self.sigma = float(self.params.get("sigma", 1.0))
        self.R = self.R_off
        self._s = self.s_init

    def stamp(self, ctx, name, nodes, initial_conditions, solution=None) -> None:
        n1, n2 = nodes[0], nodes[1]
        i1 = ctx.node_index(n1)
        i2 = ctx.node_index(n2)

        v = 0.0
        if solution is not None:
            v1 = solution[i1] if i1 is not None else 0.0
            v2 = solution[i2] if i2 is not None else 0.0
            v = v1 - v2

        g = 1.0 / self.R
        i_val = g * v
        I_eq = i_val - g * v

        ctx.add_conductance(n1, n2, g)
        if i1 is not None:
            ctx.b[i1] -= I_eq
        if i2 is not None:
            ctx.b[i2] += I_eq

    def update_state(self, solution, node_map, t, dt=None):
        dt = self.tstep if dt is None else dt
        # N2: tau-based switching
        v_th = self.V_set if self._s >= 0 else -self.V_set
        if abs(self._s) >= self.V_set:
            self.R = self.R_on
            self._s = self.V_hold
        else:
            self.R = self.R_off
        self._state["R"] = self.R
        self._state["s"] = self._s

    def get_output(self, port, solution, node_map):
        if port.lower() == "i":
            return 0.0
        return 0.0

    def get_state(self):
        return {"R": self.R, "s": self._s}


# =====================================================================
# Реестр приборов
# =====================================================================

_DEVICE_REGISTRY: dict[str, type[DeviceModel]] = {
    "R": Resistor,
    "C": Capacitor,
    "L": Inductor,
    "V": VoltageSource,
    "I": CurrentSource,
    "M": MOSFET,
    "X": YakopcicMemristor,  # по умолчанию для X — уточняется через модель
}


def device_for(card: str, model: str | None, params: dict, tstep: float, model_params: dict | None = None) -> DeviceModel:
    """Создать DeviceModel для прибора.

    card — SPICE-карта (R, C, L, V, I, M, X).
    model — имя модели (для M: .model имя, для X: subckt имя).
    model_params — параметры из .model (перекрываются element params).
    """
    if model_params:
        merged = dict(model_params)
        merged.update(params)
        params = merged
    if card == "M":
        dev = MOSFET(params, tstep)
        if model and "pmos" in model.lower():
            dev.is_p = True
        if model and "mosfet_p" in model.lower():
            dev.is_p = True
        return dev
    if card == "X":
        if model:
            m = model.lower()
            if "memristor" in m or "yakopcic" in m:
                return YakopcicMemristor(params, tstep)
            if "gem" in m or "memtransistor" in m:
                return GEMPMemtransistor(params, tstep)
            if "neuristor_n1" in m or "n1" in m:
                return NeuristorN1(params, tstep)
            if "neuristor_n2" in m or "n2" in m:
                return NeuristorN2(params, tstep)
        return YakopcicMemristor(params, tstep)
    cls = _DEVICE_REGISTRY.get(card)
    if cls is None:
        raise ValueError(f"неподдерживаемая карта прибора: {card}")
    return cls(params, tstep)

