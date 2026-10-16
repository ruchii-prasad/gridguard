"""Final validation report: physics, energy closure and reproducibility for every scenario and
controller. Writes results/validation_report.json and prints a summary.

Usage:  .venv/bin/python run_validation.py
"""
from __future__ import annotations

import json
import platform
from pathlib import Path

import numpy as np
import scipy

from src.config import BatteryParams, GridParams, OptimizerParams, SimParams
from src.microgrid import FIELDS, battery_trajectory
from src.scenarios import CONTROLLERS, SCENARIO_NAMES, make_scenario, run_scenario

SIM, BAT, GRID, OPT = SimParams(), BatteryParams(), GridParams(), OptimizerParams()


def audit(run, spec) -> dict:
    d, dt = run.dispatch, SIM.dt_h
    supply = float((d.pv_used + d.grid_import + d.discharge).sum() * dt)
    use = float((d.crit_served + d.flex_served + d.charge).sum() * dt)
    E = battery_trajectory(d.charge, d.discharge, BAT, dt)
    stored = float(BAT.eta_charge * d.charge.sum() * dt - d.discharge.sum() * dt / BAT.eta_discharge)
    phys = [c for c in run.validation.checks if c.kind == "physical"]
    return {
        "physical_checks_passed": f"{sum(c.passed for c in phys)}/{len(phys)}",
        "worst_physical_violation": max(c.worst_violation for c in phys),
        "terminal_target_met": all(c.passed for c in run.validation.checks if c.kind == "target"),
        "energy_in_kwh": supply, "energy_out_kwh": use,
        "energy_closure_error_kwh": abs(supply - use),
        "battery_identity_error_kwh": abs((E[-1] - E[0]) - stored),
        "battery_losses_kwh": float(((1 - BAT.eta_charge) * d.charge
                                     + (1 / BAT.eta_discharge - 1) * d.discharge).sum() * dt),
        "solve_time_s": run.solve_time_s,
    }


def main() -> None:
    report = {"environment": {"python": platform.python_version(), "numpy": np.__version__,
                              "scipy": scipy.__version__, "platform": platform.platform()},
              "scenarios": {}}
    worst_closure = worst_phys = worst_repro = 0.0
    all_phys = True
    print(f"{'scenario':13s} {'controller':20s} {'physics':>8s} {'target':>7s} "
          f"{'closure kWh':>12s} {'repro kW':>9s} {'solve s':>8s}")
    for name in SCENARIO_NAMES:
        a = run_scenario(make_scenario(name, SIM), BAT, GRID, SIM, OPT)
        b = run_scenario(make_scenario(name, SIM), BAT, GRID, SIM, OPT)   # independent re-run
        report["scenarios"][name] = {}
        for c in CONTROLLERS:
            r = audit(a.runs[c], a.spec)
            r["rerun_max_dispatch_diff_kw"] = max(
                float(np.abs(getattr(a.runs[c].dispatch, f) - getattr(b.runs[c].dispatch, f)).max())
                for f in FIELDS)
            report["scenarios"][name][c] = r
            all_phys &= a.runs[c].validation.physical_ok
            worst_closure = max(worst_closure, r["energy_closure_error_kwh"], r["battery_identity_error_kwh"])
            worst_phys = max(worst_phys, r["worst_physical_violation"])
            worst_repro = max(worst_repro, r["rerun_max_dispatch_diff_kw"])
            print(f"{name:13s} {c:20s} {r['physical_checks_passed']:>8s} "
                  f"{'met' if r['terminal_target_met'] else 'missed':>7s} "
                  f"{r['energy_closure_error_kwh']:12.1e} {r['rerun_max_dispatch_diff_kw']:9.1e} "
                  f"{r['solve_time_s']:8.2f}")
    report["summary"] = {"all_physical_checks_pass": all_phys,
                         "worst_physical_violation": worst_phys,
                         "worst_energy_closure_error_kwh": worst_closure,
                         "worst_rerun_dispatch_diff_kw": worst_repro}
    out = Path(__file__).parent / "results" / "validation_report.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nAll physical checks pass: {all_phys}. Worst violation {worst_phys:.1e}, "
          f"worst energy closure error {worst_closure:.1e} kWh, worst re-run difference {worst_repro:.1e} kW.")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
