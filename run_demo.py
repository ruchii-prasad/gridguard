"""Run every scenario, print a comparison table, and save results/benchmark.json.

All inputs are SYNTHETIC; all results are SIMULATED estimates, not measured impact.
Usage:  .venv/bin/python run_demo.py
"""
from __future__ import annotations

import hashlib
import json
import platform
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import scipy

from src.carbon import decompose_emissions_change
from src.config import BatteryParams, GridParams, OptimizerParams, SimParams, config_dict
from src.ledger import Ledger, LocalFileAnchor, dispatch_payload
from src.scenarios import CONTROLLERS, SCENARIO_NAMES, make_scenario, run_scenario

RESULTS = Path(__file__).parent / "results"

ROWS = [
    ("cost_storage_adjusted", "Cost, storage-adj (INR)", "{:,.0f}"),
    ("emissions_storage_adjusted_kg", "CO2e, storage-adj (kg)", "{:,.0f}"),
    ("grid_import_kwh", "Grid import (kWh)", "{:,.0f}"),
    ("pv_curtailed_kwh", "Solar curtailed (kWh)", "{:,.0f}"),
    ("critical_unserved_kwh", "Critical unserved (kWh)", "{:,.1f}"),
    ("flex_unserved_kwh", "Flexible unserved (kWh)", "{:,.1f}"),
    ("battery_e_final_kwh", "Battery at 24:00 (kWh)", "{:,.0f}"),
]
SHORT = {"baseline": "Baseline", "baseline_solar_flex": "Base+SolarFlex",
         "reoptimized": "Re-optimized", "oracle": "Oracle"}


def main() -> None:
    battery, grid, sim, opt = BatteryParams(), GridParams(), SimParams(), OptimizerParams()
    bench = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Synthetic inputs; simulated results. Not measured real-world impact.",
        "environment": {"python": platform.python_version(), "numpy": np.__version__,
                        "scipy": scipy.__version__},
        "config": config_dict(battery, grid, sim, opt),
        "scenarios": {},
    }
    cfg = config_dict(battery, grid, sim, opt)
    ledger = Ledger(RESULTS / "ledger.jsonl")
    run_id = uuid.uuid4().hex
    for name in SCENARIO_NAMES:
        res = run_scenario(make_scenario(name, sim), battery, grid, sim, opt)
        print(f"\n=== {name}: {res.spec.description}")
        print(f"{'':26s}" + "".join(f"{SHORT[c]:>16s}" for c in CONTROLLERS))
        for key, label, fmt in ROWS:
            print(f"{label:26s}" + "".join(f"{fmt.format(res.runs[c].metrics[key]):>16s}"
                                           for c in CONTROLLERS))
        status = []
        for c in CONTROLLERS:
            v = res.runs[c].validation
            status.append("OK" if v.all_passed else ("target missed" if v.physical_ok else "PHYS FAIL"))
        print(f"{'Constraint checks':26s}" + "".join(f"{s:>16s}" for s in status))

        # Emissions change vs the STRONGER baseline, split into volume and timing effects.
        b, o = res.runs["baseline_solar_flex"].metrics, res.runs["reoptimized"].metrics
        dec = decompose_emissions_change(b["grid_import_storage_adjusted_kwh"],
                                         b["emissions_storage_adjusted_kg"],
                                         o["grid_import_storage_adjusted_kwh"],
                                         o["emissions_storage_adjusted_kg"])
        print(f"CO2e change, Re-optimized vs Base+SolarFlex: {-dec['total_reduction_kg']:+.1f} kg "
              f"(volume {-dec['volume_effect_kg']:+.1f}, timing {-dec['timing_effect_kg']:+.1f})")

        # Append one tamper-evident record per controller to the audit ledger.
        for c, r in res.runs.items():
            ledger.append(dispatch_payload(c, res.spec.actual.to_dict(), cfg, r.dispatch.to_dict(),
                                           r.metrics, r.validation.to_dict()),
                          scenario_id=name, run_id=run_id)

        bench["scenarios"][name] = {
            "description": res.spec.description,
            "t_disturbance_step": res.spec.t_disturbance,
            "emissions_decomposition_vs_solar_flex_baseline": dec,
            "controllers": {c: {"metrics": r.metrics, "validation": r.validation.to_dict(),
                                "solve_time_s": r.solve_time_s} for c, r in res.runs.items()},
        }
    # Fingerprint of headline metrics (rounded to 0.1) to compare results across machines.
    summary = {s: {c: {k: round(v["metrics"][k], 1) for k, _, _ in ROWS}
                   for c, v in sc["controllers"].items()} for s, sc in bench["scenarios"].items()}
    fp = hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest()[:12]
    bench["results_fingerprint"] = fp
    print(f"\nResults fingerprint: {fp}  (identical on any machine that reproduces these numbers)")
    out = RESULTS / "benchmark.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(bench, indent=2, sort_keys=True))
    print(f"\nSaved {out}")

    v = ledger.verify()
    receipt = LocalFileAnchor(RESULTS / "ledger_anchor.json").publish(v.head_hash, v.n_records)
    print(f"Audit ledger: {v.n_records} records, chain {'VALID' if v.ok else 'INVALID: ' + v.reason}, "
          f"head {v.head_hash[:16]}... (anchored locally at {receipt['published_utc']})")


if __name__ == "__main__":
    main()
