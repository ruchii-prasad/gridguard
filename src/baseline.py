"""Rule-based baseline controllers (greedy, no look-ahead, no grid charging).

Per step:
1. Solar serves critical load first, then the flexible load chosen by the flex policy.
2. Surplus solar charges the battery (power and energy-headroom limits); the rest is curtailed.
3. A deficit is covered by the battery first, down to the reserve while the grid is up
   (down to the physical minimum during an outage), then by grid import up to its limit.
4. If supply is still short, flexible load is shed before critical load.

Flex policies:
- "nominal": flexible load runs at its nominal times (no rescheduling). This is the standard
  solar self-consumption battery controller.
- "solar_following": a STRONGER rule-based baseline. Flexible load runs whenever there is
  solar surplus (after critical load) within its allowed window, and is forced on as late as
  possible if the remaining energy would otherwise not fit before the window closes.

Both obey exactly the same physical limits as the optimizer.
"""
from __future__ import annotations

import numpy as np

from .config import BatteryParams, GridParams, SimParams
from .data import ScenarioInputs
from .microgrid import Dispatch

FLEX_POLICIES = ("nominal", "solar_following")


def _flex_target(policy: str, inp: ScenarioInputs, t: int, remaining_kwh: float,
                 cap_after_kwh: float, dt: float) -> float:
    if policy == "nominal":
        return float(inp.flex_nominal_kw[t])
    surplus = max(0.0, inp.solar_avail_kw[t] - inp.crit_demand_kw[t])
    forced = max(0.0, remaining_kwh - cap_after_kwh) / dt
    return float(min(inp.flex_max_kw[t], max(remaining_kwh, 0.0) / dt, max(surplus, forced)))


def run_baseline(inp: ScenarioInputs, battery: BatteryParams, grid: GridParams,
                 sim: SimParams, flex_policy: str = "nominal") -> Dispatch:
    if flex_policy not in FLEX_POLICIES:
        raise ValueError(f"flex_policy must be one of {FLEX_POLICIES}")
    T, dt = inp.T, sim.dt_h
    d = Dispatch.zeros(T)
    E = battery.e_init
    remaining = inp.flex_energy(dt)
    # Flexible energy that could still be delivered strictly after step t.
    cap_after = np.concatenate((np.cumsum((inp.flex_max_kw * dt)[::-1])[::-1][1:], [0.0]))
    for t in range(T):
        solar = inp.solar_avail_kw[t]
        crit = inp.crit_demand_kw[t]
        flex = _flex_target(flex_policy, inp, t, remaining, cap_after[t], dt)
        demand = crit + flex
        grid_up = inp.grid_available[t] > 0.5

        if solar >= demand:
            surplus = solar - demand
            headroom_kw = max(0.0, (battery.e_max - E) / (battery.eta_charge * dt))
            charge = min(surplus, battery.p_charge_max_kw, headroom_kw)
            d.charge[t] = charge
            d.pv_used[t] = demand + charge
            d.crit_served[t], d.flex_served[t] = crit, flex
            E += battery.eta_charge * charge * dt
        else:
            deficit = demand - solar
            floor = battery.e_reserve if grid_up else battery.e_min
            avail_kw = max(0.0, (E - floor) * battery.eta_discharge / dt)
            discharge = min(deficit, battery.p_discharge_max_kw, avail_kw)
            deficit -= discharge
            imp = min(deficit, grid.import_max_kw) if grid_up else 0.0
            supply = solar + discharge + imp
            crit_served = min(crit, supply)
            flex_served = min(flex, supply - crit_served)
            d.pv_used[t], d.discharge[t], d.grid_import[t] = solar, discharge, imp
            d.crit_served[t], d.flex_served[t] = crit_served, flex_served
            E -= discharge * dt / battery.eta_discharge
        remaining -= d.flex_served[t] * dt
    return d
