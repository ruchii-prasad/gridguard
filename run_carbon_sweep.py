"""Sensitivity of optimal dispatch to the assumed shadow carbon price, on two days:
  normal               - sunny day, time-of-day tariff (price and carbon signals agree)
  monsoon_flat_tariff  - little sun, flat tariff (only the carbon price rewards clean hours)
Saves results/carbon_sweep.json. All inputs synthetic; results simulated.

Usage:  .venv/bin/python run_carbon_sweep.py
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from src.baseline import run_baseline
from src.config import BatteryParams, GridParams, OptimizerParams, SimParams
from src.metrics import compute_metrics
from src.optimizer import check_penalty_hierarchy, optimize
from src.scenarios import make_scenario

PRICES = [0.0, 2.0, 5.0, 10.0, 20.0]   # INR per kg CO2e
DAYS = ("normal", "monsoon_flat_tariff")


def main() -> None:
    sim, bat, grid = SimParams(), BatteryParams(), GridParams()
    out = {"note": "Synthetic inputs; simulated results.", "carbon_prices": PRICES, "days": {}}
    for day in DAYS:
        inp = make_scenario(day, sim).actual
        b = compute_metrics(run_baseline(inp, bat, grid, sim, "solar_following"), inp, bat, sim)
        print(f"\n{day}  (baseline + solar-following flex: ₹{b['cost_storage_adjusted']:,.0f}, "
              f"{b['emissions_storage_adjusted_kg']:.1f} kg)")
        print(f"{'INR/kg':>7s} {'cost INR':>10s} {'CO2e kg':>9s} {'vs baseline':>12s}")
        rows = []
        for p in PRICES:
            opt = replace(OptimizerParams(), carbon_price_per_kg=p)
            if problems := check_penalty_hierarchy(inp, bat, opt):
                raise SystemExit(f"penalty hierarchy violated at {p} INR/kg: {problems}")
            m = compute_metrics(optimize(inp, bat, grid, sim, opt).dispatch, inp, bat, sim)
            row = {"carbon_price_per_kg": p, "cost_storage_adjusted": m["cost_storage_adjusted"],
                   "emissions_storage_adjusted_kg": m["emissions_storage_adjusted_kg"],
                   "grid_import_kwh": m["grid_import_kwh"]}
            rows.append(row)
            d_pct = (row["emissions_storage_adjusted_kg"] / b["emissions_storage_adjusted_kg"] - 1) * 100
            print(f"{p:7.1f} {row['cost_storage_adjusted']:10,.0f} "
                  f"{row['emissions_storage_adjusted_kg']:9.1f} {d_pct:+11.1f}%")
        out["days"][day] = {"baseline_solar_flex": {"cost_storage_adjusted": b["cost_storage_adjusted"],
                                                    "emissions_storage_adjusted_kg": b["emissions_storage_adjusted_kg"]},
                            "optimizer": rows}
    path = Path(__file__).parent / "results" / "carbon_sweep.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"\nSaved {path}")


if __name__ == "__main__":
    main()
