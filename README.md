# GridGuard

Resilience-first microgrid dispatch optimizer with a tamper-evident audit ledger.
Entry for the IEEE ClimateChain Global Hackathon 2026 (Renewable Energy & Grid Management track).

> **All inputs are synthetic and all results are simulated estimates, not measured real-world impact.**

GridGuard schedules solar, a battery, grid imports, critical loads and flexible loads with a
mixed-integer linear program (SciPy / HiGHS). It re-optimizes after disturbances (solar shock,
grid outage, demand spike), compares itself against two rule-based baselines and a
perfect-foresight bound, and records every dispatch in a SHA-256 hash-chained ledger.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
bash run_all.sh                    # tests + all scenarios + sweeps + tamper demo
.venv/bin/streamlit run app.py     # dashboard
```

Full documentation (methodology, assumptions, limitations, security assessment) is in progress.
