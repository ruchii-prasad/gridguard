"""Run metrics and a fair baseline-vs-optimizer comparison.

Fairness: two controllers that end the day with different stored energy are not directly
comparable (one has "borrowed" energy from the battery). Storage-adjusted metrics charge the
net energy drawn from the battery, (E_init - E_T), at the cost and carbon of replacing it from the
grid at the horizon-average price and intensity, grossed up for charging losses:
    adj_cost      = cost      + (E_init - E_T) / eta_c * mean(price)
    adj_emissions = emissions + (E_init - E_T) / eta_c * mean(carbon)
(If a controller ends with MORE energy than it started with, the adjustment is a credit.)
"""
from __future__ import annotations

import numpy as np

from .carbon import grid_cost, grid_emissions_kg
from .config import BatteryParams, SimParams
from .data import ScenarioInputs
from .microgrid import Dispatch, battery_trajectory, flex_unserved_energy, pv_curtailed, unserved_critical


def compute_metrics(d: Dispatch, inp: ScenarioInputs, battery: BatteryParams,
                    sim: SimParams) -> dict[str, float]:
    dt = sim.dt_h
    E = battery_trajectory(d.charge, d.discharge, battery, dt)
    cost = grid_cost(d, inp, dt)
    emis = grid_emissions_kg(d, inp, dt)
    drawn = float(E[0] - E[-1])
    replace_kwh = drawn / battery.eta_charge
    load = float((d.crit_served + d.flex_served).sum() * dt)
    pv_used = float(d.pv_used.sum() * dt)
    return {
        "load_served_kwh": load,
        "critical_served_kwh": float(d.crit_served.sum() * dt),
        "critical_unserved_kwh": float(unserved_critical(d, inp).sum() * dt),
        "flex_served_kwh": float(d.flex_served.sum() * dt),
        "flex_unserved_kwh": flex_unserved_energy(d, inp, dt),
        "grid_import_kwh": float(d.grid_import.sum() * dt),
        "peak_grid_import_kw": float(d.grid_import.max()),
        "pv_available_kwh": float(inp.solar_avail_kw.sum() * dt),
        "pv_used_kwh": pv_used,
        "pv_curtailed_kwh": float(pv_curtailed(d, inp).sum() * dt),
        "battery_throughput_kwh": float((d.charge + d.discharge).sum() * dt),
        "battery_e_init_kwh": float(E[0]),
        "battery_e_final_kwh": float(E[-1]),
        "battery_e_min_kwh": float(E.min()),
        "cost": cost,
        "emissions_kg": emis,
        "grid_import_storage_adjusted_kwh": float(d.grid_import.sum() * dt) + replace_kwh,
        "cost_storage_adjusted": cost + replace_kwh * float(inp.price_per_kwh.mean()),
        "emissions_storage_adjusted_kg": emis + replace_kwh * float(inp.carbon_kg_per_kwh.mean()),
        "avg_import_carbon_kg_per_kwh": emis / max(float(d.grid_import.sum() * dt), 1e-9),
    }


def compare(baseline: dict[str, float], optimized: dict[str, float]) -> dict[str, dict[str, float]]:
    out = {}
    for k in baseline:
        b, o = baseline[k], optimized[k]
        out[k] = {"baseline": b, "optimized": o, "delta": o - b,
                  "pct": (o - b) / abs(b) * 100 if abs(b) > 1e-9 else float("nan")}
    return out
