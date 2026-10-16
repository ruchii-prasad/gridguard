"""Randomized property tests: many random microgrids (seeded, so reproducible).

For every random case the optimizer must
  1. return a dispatch that passes every PHYSICAL check of the independent validator,
  2. score no worse than either rule-based baseline on its own objective
     (both baselines are feasible points of the MILP),
  3. close the daily energy balance and the battery energy identity exactly.
"""
import numpy as np
import pytest

from src.baseline import run_baseline
from src.config import BatteryParams, GridParams, OptimizerParams, SimParams
from src.data import ScenarioInputs
from src.microgrid import battery_trajectory
from src.optimizer import evaluate_objective, optimize
from src.validation import validate_dispatch

N_CASES = 25
SIM = SimParams(dt_h=1.0, n_steps=24)
OPT = OptimizerParams()


def random_case(seed: int):
    rng = np.random.default_rng(seed)
    T, h = SIM.n_steps, np.arange(SIM.n_steps)
    peak = rng.uniform(0, 150)
    solar = np.where((h >= 6) & (h < 18), peak * np.sin(np.pi * (h - 6) / 12), 0.0)
    solar *= rng.uniform(0.3, 1.0, T)                          # cloud noise
    crit = rng.uniform(5, 70, T)
    flex_max = np.where(rng.random(T) < 0.7, rng.uniform(0, 40, T), 0.0)
    flex_nom = flex_max * rng.uniform(0, 1, T) * (rng.random(T) < 0.5)
    grid_up = np.ones(T)
    if rng.random() < 0.6:                                     # random outage block
        s = rng.integers(0, T - 1)
        grid_up[s:s + rng.integers(1, 8)] = 0.0
    inp = ScenarioInputs(f"rand{seed}", solar, crit, flex_nom, flex_max,
                         rng.uniform(3, 12, T), rng.uniform(0.5, 0.95, T), grid_up)
    smin = rng.uniform(0.0, 0.2)
    smax = rng.uniform(0.8, 1.0)
    sres = rng.uniform(smin, 0.5)
    bat = BatteryParams(capacity_kwh=rng.uniform(20, 300),
                        p_charge_max_kw=rng.uniform(0, 100), p_discharge_max_kw=rng.uniform(0, 100),
                        eta_charge=rng.uniform(0.85, 0.99), eta_discharge=rng.uniform(0.85, 0.99),
                        soc_init=rng.uniform(smin, smax), soc_min=smin, soc_max=smax,
                        soc_reserve=sres, soc_terminal_min=rng.uniform(smin, smax))
    grid = GridParams(import_max_kw=rng.choice([0.0, rng.uniform(20, 200)]))
    return inp, bat, grid


@pytest.mark.parametrize("seed", range(N_CASES))
def test_random_microgrid(seed):
    inp, bat, grid = random_case(seed)
    res = optimize(inp, bat, grid, SIM, OPT)
    d = res.dispatch

    report = validate_dispatch(d, inp, bat, grid, SIM)
    assert report.physical_ok, (seed, report.failed())

    for policy in ("nominal", "solar_following"):
        base = run_baseline(inp, bat, grid, SIM, policy)
        assert validate_dispatch(base, inp, bat, grid, SIM).physical_ok, (seed, policy)
        j_base = evaluate_objective(base, inp, bat, SIM, OPT)["total"]
        assert res.objective <= j_base + 1e-3, (seed, policy, res.objective, j_base)

    dt = SIM.dt_h
    supply = (d.pv_used + d.grid_import + d.discharge).sum() * dt
    use = (d.crit_served + d.flex_served + d.charge).sum() * dt
    assert supply == pytest.approx(use, abs=1e-5)
    E = battery_trajectory(d.charge, d.discharge, bat, dt)
    assert E[-1] - E[0] == pytest.approx(
        bat.eta_charge * d.charge.sum() * dt - d.discharge.sum() * dt / bat.eta_discharge, abs=1e-6)
