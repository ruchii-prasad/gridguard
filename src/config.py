"""Configuration parameters for GridGuard.

Units and sign convention (used everywhere in the project):
- Power: kW. Every power variable is non-negative; its direction is in its name
  (grid_import, charge, discharge). There is no grid export in this model.
- Energy: kWh. Time step dt: hours.
- Battery state: E[t] is stored energy (kWh) at the START of interval t,
  so E has length T + 1 and E[T] is the terminal state.
- Price: currency/kWh (default INR). Carbon intensity: kg CO2e/kWh.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class BatteryParams:
    capacity_kwh: float = 200.0
    p_charge_max_kw: float = 50.0
    p_discharge_max_kw: float = 50.0
    eta_charge: float = 0.95
    eta_discharge: float = 0.95
    soc_init: float = 0.50
    soc_min: float = 0.10       # hard physical floor (all times)
    soc_max: float = 0.95       # hard physical ceiling
    soc_reserve: float = 0.30   # outage reserve: no discharge below this while grid is available
    soc_terminal_min: float = 0.50  # end-of-horizon requirement (enforced by the optimizer)

    def __post_init__(self) -> None:
        if self.capacity_kwh <= 0:
            raise ValueError("capacity_kwh must be positive")
        if self.p_charge_max_kw < 0 or self.p_discharge_max_kw < 0:
            raise ValueError("power limits must be non-negative")
        for name in ("eta_charge", "eta_discharge"):
            v = getattr(self, name)
            if not 0 < v <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        if not 0 <= self.soc_min <= self.soc_reserve <= self.soc_max <= 1:
            raise ValueError("require 0 <= soc_min <= soc_reserve <= soc_max <= 1")
        if not self.soc_min <= self.soc_init <= self.soc_max:
            raise ValueError("soc_init must lie within [soc_min, soc_max]")
        if not self.soc_min <= self.soc_terminal_min <= self.soc_max:
            raise ValueError("soc_terminal_min must lie within [soc_min, soc_max]")

    @property
    def e_min(self) -> float:
        return self.soc_min * self.capacity_kwh

    @property
    def e_max(self) -> float:
        return self.soc_max * self.capacity_kwh

    @property
    def e_reserve(self) -> float:
        return self.soc_reserve * self.capacity_kwh

    @property
    def e_init(self) -> float:
        return self.soc_init * self.capacity_kwh

    @property
    def e_terminal_min(self) -> float:
        return self.soc_terminal_min * self.capacity_kwh


@dataclass(frozen=True)
class GridParams:
    import_max_kw: float = 150.0

    def __post_init__(self) -> None:
        if self.import_max_kw < 0:
            raise ValueError("import_max_kw must be non-negative")


@dataclass(frozen=True)
class SimParams:
    dt_h: float = 0.25    # 15-minute intervals
    n_steps: int = 96     # 24 hours
    tol: float = 1e-6     # numerical tolerance for constraint checks (kW / kWh)

    def __post_init__(self) -> None:
        if self.dt_h <= 0 or self.n_steps <= 0:
            raise ValueError("dt_h and n_steps must be positive")


@dataclass(frozen=True)
class OptimizerParams:
    """Objective weights. All are in currency per physical unit, so J is in currency.

    Penalty hierarchy (checked by optimizer.check_penalty_hierarchy):
        voll  >>  flex_unserved_penalty  >  terminal_shortfall_penalty  >  energy + carbon cost
    so the solver sheds flexible load before critical load, and drains the battery below
    its end-of-day target before shedding flexible load.
    """
    carbon_price_per_kg: float = 2.0          # assumed shadow carbon price (INR/kg CO2e); sweep it
    voll_per_kwh: float = 1000.0              # value of lost load for critical demand (INR/kWh)
    flex_unserved_penalty_per_kwh: float = 100.0
    terminal_shortfall_penalty_per_kwh: float = 50.0
    degradation_per_kwh: float = 0.5          # per kWh of charge + discharge throughput
    time_limit_s: float = 30.0
    mip_rel_gap: float = 1e-7
    tie_break: bool = True        # lexicographic stage 2: max stored energy among cost-optimal plans
    # Currency. Stage 2 chooses only among plans within this of the minimum J. At VOLL = 1000/kWh
    # this allows at most 1e-7 kWh of extra unserved critical load (validator tolerance: 1e-6).
    # Values below ~1e-5 fall under HiGHS's feasibility tolerance and give infeasible points.
    tie_break_tol: float = 1e-4


def config_dict(battery: BatteryParams, grid: GridParams, sim: SimParams,
                opt: OptimizerParams | None = None) -> dict:
    d = {"battery": asdict(battery), "grid": asdict(grid), "sim": asdict(sim)}
    if opt is not None:
        d["optimizer"] = asdict(opt)
    return d
