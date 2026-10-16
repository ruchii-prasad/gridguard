#!/usr/bin/env bash
# One command: set up/refresh the environment, run tests and every demo.
# Usage: bash run_all.sh            (dashboard afterwards: .venv/bin/streamlit run app.py)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo ">> Creating virtual environment"
  python3 -m venv .venv
fi
echo ">> Installing/checking dependencies"
.venv/bin/pip install -q -r requirements.txt

echo ">> Tests";              .venv/bin/python -m pytest -q
echo; echo ">> Scenarios";    .venv/bin/python run_demo.py
echo; echo ">> Outage sweep"; .venv/bin/python run_outage_sweep.py
echo; echo ">> Carbon sweep"; .venv/bin/python run_carbon_sweep.py
echo; echo ">> Tamper demo";  .venv/bin/python run_tamper_demo.py
echo; echo ">> Done. Open the dashboard with:  .venv/bin/streamlit run app.py"
