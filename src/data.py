"""Scenario input time series. All scenarios are SYNTHETIC simulations."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import SimParams


@dataclass
class ScenarioInputs:
    """Exogenous inputs for one horizon (each array has length T).

    flex_nominal_kw: when flexible loads would run if not rescheduled (baseline uses this).
    flex_max_kw:     upper bound on flexible power at each step; zero outside the allowed window.
    flex_energy_kwh: flexible energy that should be delivered within the horizon.
    grid_available:  1 if the grid can supply power at step t, 0 during an outage.
    """
    name: str
    solar_avail_kw: np.ndarray
    crit_demand_kw: np.ndarray
    flex_nominal_kw: np.ndarray
    flex_max_kw: np.ndarray
    price_per_kwh: np.ndarray
    carbon_kg_per_kwh: np.ndarray
    grid_available: np.ndarray
    flex_energy_kwh: float = field(default=-1.0)  # -1 => derive from nominal profile
    simulated: bool = True

    def __post_init__(self) -> None:
        arrays = ("solar_avail_kw", "crit_demand_kw", "flex_nominal_kw", "flex_max_kw",
                  "price_per_kwh", "carbon_kg_per_kwh", "grid_available")
        for a in arrays:
            setattr(self, a, np.asarray(getattr(self, a), dtype=float))
        T = len(self.solar_avail_kw)
        for a in arrays:
            arr = getattr(self, a)
            if arr.shape != (T,):
                raise ValueError(f"{a} must have shape ({T},), got {arr.shape}")
            if a != "price_per_kwh" and np.any(arr < 0):
                raise ValueError(f"{a} must be non-negative")
        if not np.all(np.isin(self.grid_available, (0.0, 1.0))):
            raise ValueError("grid_available must be 0/1")
        if np.any(self.flex_nominal_kw > self.flex_max_kw + 1e-9):
            raise ValueError("flex_nominal_kw must not exceed flex_max_kw")

    @property
    def T(self) -> int:
        return len(self.solar_avail_kw)

    def to_dict(self) -> dict:
        arrays = ("solar_avail_kw", "crit_demand_kw", "flex_nominal_kw", "flex_max_kw",
                  "price_per_kwh", "carbon_kg_per_kwh", "grid_available")
        d = {a: [float(x) for x in getattr(self, a)] for a in arrays}
        d.update(name=self.name, flex_energy_kwh=float(self.flex_energy_kwh), simulated=self.simulated)
        return d

    def flex_energy(self, dt_h: float) -> float:
        if self.flex_energy_kwh >= 0:
            return float(self.flex_energy_kwh)
        return float(self.flex_nominal_kw.sum() * dt_h)


def _hours(sim: SimParams) -> np.ndarray:
    return np.arange(sim.n_steps) * sim.dt_h


def make_normal_day(sim: SimParams = SimParams()) -> ScenarioInputs:
    """Deterministic synthetic 24 h profile for a small campus-style microgrid.

    Shapes are illustrative, not measured data.
    """
    h = _hours(sim)
    # Solar: half-sine between 06:00 and 18:00, 120 kW peak.
    solar = np.where((h >= 6) & (h < 18), 120.0 * np.sin(np.pi * (h - 6) / 12), 0.0)
    # Critical load: 40 kW base, +20 kW daytime, +15 kW evening.
    crit = 40.0 + 20.0 * ((h >= 9) & (h < 17)) + 15.0 * ((h >= 18) & (h < 22))
    # Flexible load (e.g. water pumping / EV charging): nominally 30 kW 18:00-22:00,
    # may be moved anywhere in 08:00-24:00 at up to 40 kW.
    flex_nom = np.where((h >= 18) & (h < 22), 30.0, 0.0)
    flex_max = np.where(h >= 8, 40.0, 0.0)
    # Time-of-day tariff (INR/kWh): off-peak / normal / evening peak.
    price = np.where(h < 6, 5.0, np.where((h >= 18) & (h < 22), 11.0, 7.5))
    # Grid carbon intensity (kg CO2e/kWh): lower midday, highest in the evening peak.
    carbon = 0.80 - 0.15 * np.sin(np.pi * np.clip(h - 6, 0, 12) / 12) + 0.08 * ((h >= 18) & (h < 22))
    return ScenarioInputs(
        name="normal",
        solar_avail_kw=solar,
        crit_demand_kw=crit,
        flex_nominal_kw=flex_nom,
        flex_max_kw=flex_max,
        price_per_kwh=price,
        carbon_kg_per_kwh=carbon,
        grid_available=np.ones(sim.n_steps),
    )
