"""Independent constraint checker. Used for BOTH the baseline and the optimizer, so neither
controller is trusted to have respected the physics on its own."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .config import BatteryParams, GridParams, SimParams
from .data import ScenarioInputs
from .microgrid import Dispatch, FIELDS, battery_trajectory, power_balance_residual


@dataclass
class Check:
    name: str
    passed: bool
    worst_violation: float   # in the check's own units (kW or kWh); 0 when satisfied
    detail: str = ""
    kind: str = "physical"   # "physical" = must never fail; "target" = operating goal (may be missed)


@dataclass
class ValidationReport:
    checks: list[Check]

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def physical_ok(self) -> bool:
        return all(c.passed for c in self.checks if c.kind == "physical")

    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> dict:
        return {"all_passed": self.all_passed, "checks": [asdict(c) for c in self.checks]}


def _upper(name: str, value: np.ndarray, limit: np.ndarray | float, tol: float, unit: str) -> Check:
    excess = np.asarray(value) - limit
    worst = float(max(0.0, np.max(excess)))
    return Check(name, worst <= tol, worst, f"max excess {worst:.3g} {unit}")


def validate_dispatch(d: Dispatch, inp: ScenarioInputs, battery: BatteryParams,
                      grid: GridParams, sim: SimParams,
                      require_terminal: bool = True) -> ValidationReport:
    tol = sim.tol
    if d.T != inp.T:
        raise ValueError("dispatch and inputs have different horizons")
    E = battery_trajectory(d.charge, d.discharge, battery, sim.dt_h)
    checks: list[Check] = []

    neg = min(float(np.min(getattr(d, f))) for f in FIELDS)
    checks.append(Check("non_negativity", neg >= -tol, max(0.0, -neg), "all powers >= 0"))

    res = np.abs(power_balance_residual(d))
    checks.append(Check("power_balance", float(res.max()) <= tol, float(res.max()),
                        f"max |residual| {res.max():.3g} kW"))

    checks.append(_upper("solar_availability", d.pv_used, inp.solar_avail_kw, tol, "kW"))
    checks.append(_upper("grid_import_limit", d.grid_import,
                         grid.import_max_kw * inp.grid_available, tol, "kW"))
    checks.append(_upper("charge_power_limit", d.charge, battery.p_charge_max_kw, tol, "kW"))
    checks.append(_upper("discharge_power_limit", d.discharge, battery.p_discharge_max_kw, tol, "kW"))

    overlap = np.minimum(d.charge, d.discharge)
    checks.append(Check("charge_discharge_exclusive", float(overlap.max()) <= tol,
                        float(overlap.max()), "min(charge, discharge) at each step"))

    checks.append(_upper("battery_energy_max", E, battery.e_max, tol, "kWh"))
    below = float(max(0.0, np.max(battery.e_min - E)))
    checks.append(Check("battery_energy_min", below <= tol, below, f"max shortfall {below:.3g} kWh"))

    # Reserve rule: while the grid is available, the battery must not discharge into the reserve band.
    discharging = (d.discharge > tol) & (inp.grid_available > 0.5)
    reserve_breach = np.where(discharging, battery.e_reserve - E[1:], 0.0)
    worst_r = float(max(0.0, reserve_breach.max()))
    checks.append(Check("reserve_respected_when_grid_up", worst_r <= tol, worst_r,
                        "no discharge below reserve while grid is available"))

    checks.append(_upper("critical_served_le_demand", d.crit_served, inp.crit_demand_kw, tol, "kW"))
    checks.append(_upper("flex_power_limit", d.flex_served, inp.flex_max_kw, tol, "kW"))
    flex_delivered = float(d.flex_served.sum() * sim.dt_h)
    checks.append(_upper("flex_energy_not_exceeded", flex_delivered, inp.flex_energy(sim.dt_h),
                         tol, "kWh"))

    if require_terminal:
        short = float(max(0.0, battery.e_terminal_min - E[-1]))
        checks.append(Check("terminal_energy", short <= tol, short,
                            f"E[T]={E[-1]:.2f} kWh vs required {battery.e_terminal_min:.2f} kWh",
                            kind="target"))
    return ValidationReport(checks)
