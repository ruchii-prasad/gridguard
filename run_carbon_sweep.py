"""Sensitivity of the optimal dispatch to the assumed shadow carbon price (normal day, oracle).
Saves results/carbon_sweep.json. All inputs synthetic; results simulated.

Usage:  .venv/bin/python run_carbon_sweep.py
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from src.config import BatteryParams, GridParams, OptimizerParams, SimParams
from src.data import make_normal_day
from src.metrics import compute_metrics
from src.optimizer import check_penalty_hierarchy, optimize

PRICES = [0.0, 2.0, 5.0, 10.0, 20.0]   # INR per kg CO2e


def main() -> None:
    sim, bat, grid = SimParams(), BatteryParams(), GridParams()
    inp = make_normal_day(sim)
    rows = []
    print("Carbon-price sensitivity, normal day (SIMULATED)")
    print(f"{'INR/kg':>7s} {'cost INR':>10s} {'CO2e kg':>9s} {'grid kWh':>9s} {'avg kg/kWh':>11s}")
    for p in PRICES:
        opt = replace(OptimizerParams(), carbon_price_per_kg=p)
        problems = check_penalty_hierarchy(inp, bat, opt)
        if problems:
            raise SystemExit(f"penalty hierarchy violated at {p} INR/kg: {problems}")
        m = compute_metrics(optimize(inp, bat, grid, sim, opt).dispatch, inp, bat, sim)
        row = {"carbon_price_per_kg": p, "cost_storage_adjusted": m["cost_storage_adjusted"],
               "emissions_storage_adjusted_kg": m["emissions_storage_adjusted_kg"],
               "grid_import_kwh": m["grid_import_kwh"],
               "avg_import_carbon_kg_per_kwh": m["avg_import_carbon_kg_per_kwh"]}
        rows.append(row)
        print(f"{p:7.1f} {row['cost_storage_adjusted']:10,.0f} {row['emissions_storage_adjusted_kg']:9.1f} "
              f"{row['grid_import_kwh']:9.1f} {row['avg_import_carbon_kg_per_kwh']:11.3f}")
    out = Path(__file__).parent / "results" / "carbon_sweep.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"note": "Synthetic inputs; simulated results.", "rows": rows}, indent=2))
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
