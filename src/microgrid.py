"""Discrete-time microgrid model.

Power balance at every step t (all terms >= 0, kW):
    pv_used[t] + grid_import[t] + discharge[t] = crit_served[t] + flex_served[t] + charge[t]

Battery dynamics (kWh):
    E[t+1] = E[t] + eta_c * charge[t] * dt - discharge[t] * dt / eta_d

Derived quantities:
    pv_curtailed[t]        = solar_avail[t] - pv_used[t]   (no export, so surplus is curtailed)
    unserved_critical[t]   = crit_demand[t] - crit_served[t]
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import BatteryParams
from .data import ScenarioInputs

FIELDS = ("pv_used", "grid_import", "charge", "discharge", "crit_served", "flex_served")


@dataclass
class Dispatch:
    pv_used: np.ndarray
    grid_import: np.ndarray
    charge: np.ndarray
    discharge: np.ndarray
    crit_served: np.ndarray
    flex_served: np.ndarray

    def __post_init__(self) -> None:
        for f in FIELDS:
            setattr(self, f, np.asarray(getattr(self, f), dtype=float))
        T = len(self.pv_used)
        if any(getattr(self, f).shape != (T,) for f in FIELDS):
            raise ValueError("all dispatch arrays must have the same length")

    @property
    def T(self) -> int:
        return len(self.pv_used)

    @classmethod
    def zeros(cls, T: int) -> "Dispatch":
        return cls(*(np.zeros(T) for _ in FIELDS))

    def to_dict(self) -> dict[str, list[float]]:
        return {f: [float(x) for x in getattr(self, f)] for f in FIELDS}


def battery_trajectory(charge: np.ndarray, discharge: np.ndarray,
                       battery: BatteryParams, dt_h: float) -> np.ndarray:
    """Stored energy E[0..T] (kWh), starting from battery.e_init."""
    delta = battery.eta_charge * charge * dt_h - discharge * dt_h / battery.eta_discharge
    return battery.e_init + np.concatenate(([0.0], np.cumsum(delta)))


def power_balance_residual(d: Dispatch) -> np.ndarray:
    """Supply minus demand at each step (kW); zero for a balanced dispatch."""
    return d.pv_used + d.grid_import + d.discharge - d.crit_served - d.flex_served - d.charge


def unserved_critical(d: Dispatch, inp: ScenarioInputs) -> np.ndarray:
    return inp.crit_demand_kw - d.crit_served


def pv_curtailed(d: Dispatch, inp: ScenarioInputs) -> np.ndarray:
    return inp.solar_avail_kw - d.pv_used


def flex_unserved_energy(d: Dispatch, inp: ScenarioInputs, dt_h: float) -> float:
    """Required flexible energy not delivered within the horizon (kWh, >= 0)."""
    return max(0.0, inp.flex_energy(dt_h) - float(d.flex_served.sum() * dt_h))
