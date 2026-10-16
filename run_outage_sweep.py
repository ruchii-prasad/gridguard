"""Resilience sweep: unannounced 3 h outage starting at each even hour of the synthetic day.
Reports critical energy unserved (kWh) per controller. Saves results/outage_sweep.json.

Usage:  .venv/bin/python run_outage_sweep.py
"""
from __future__ import annotations

import json
from pathlib import Path

from src.scenarios import CONTROLLERS, outage_scenario, run_scenario

DURATION_H = 3.0


def main() -> None:
    rows = []
    print(f"Critical unserved (kWh), unannounced {DURATION_H:g} h outage (SIMULATED)")
    print("start  " + "".join(f"{c:>21s}" for c in CONTROLLERS))
    for h0 in range(0, 22, 2):
        res = run_scenario(outage_scenario(h0, DURATION_H))
        vals = {c: res.runs[c].metrics["critical_unserved_kwh"] for c in CONTROLLERS}
        rows.append({"start_h": h0, "duration_h": DURATION_H, "critical_unserved_kwh": vals})
        print(f"{h0:02d}:00  " + "".join(f"{vals[c]:21.1f}" for c in CONTROLLERS))
    out = Path(__file__).parent / "results" / "outage_sweep.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"note": "Synthetic inputs; simulated results.", "rows": rows}, indent=2))
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
