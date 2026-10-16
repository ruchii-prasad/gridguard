import numpy as np
import pytest

from src.baseline import run_baseline
from src.config import BatteryParams, GridParams, OptimizerParams, SimParams
from src.data import ScenarioInputs, make_normal_day
from src.metrics import compute_metrics
from src.microgrid import battery_trajectory, unserved_critical
from src.optimizer import check_penalty_hierarchy, evaluate_objective, optimize
from src.validation import validate_dispatch
from tests.test_microgrid import BAT, GRID, SIM, tiny_inputs

OPT = OptimizerParams()


def test_tiny_case_lookahead_avoids_outage_shortfall():
    """Baseline (no look-ahead) drains the battery at hour 1 and sheds 1.97 kW at hour 2.
    The optimizer can import at hour 1 and top up at hour 0, so all critical load is served."""
    inp = tiny_inputs()
    res = optimize(inp, BAT, GRID, SIM, OPT)
    assert unserved_critical(res.dispatch, inp).sum() == pytest.approx(0, abs=1e-6)
    assert validate_dispatch(res.dispatch, inp, BAT, GRID, SIM).all_passed
    base = run_baseline(inp, BAT, GRID, SIM)
    assert unserved_critical(base, inp).sum() > 1.9


def test_unavoidable_shortfall_equals_physical_bound():
    """3 h outage, no solar, 4 kW critical, battery 5 kWh down to 1 kWh floor.
    Max deliverable = (5 - 1) * 0.9 = 3.6 kWh, so 12 - 3.6 = 8.4 kWh MUST go unserved."""
    inp = tiny_inputs()
    inp.solar_avail_kw[:] = 0
    inp.crit_demand_kw[:] = 4
    inp.flex_nominal_kw[:] = 0
    inp.flex_max_kw[:] = 0
    inp.grid_available[:] = 0
    res = optimize(inp, BAT, GRID, SIM, OPT)
    assert unserved_critical(res.dispatch, inp).sum() * SIM.dt_h == pytest.approx(8.4, abs=1e-5)
    E = battery_trajectory(res.dispatch.charge, res.dispatch.discharge, BAT, SIM.dt_h)
    assert E[-1] == pytest.approx(BAT.e_min, abs=1e-6)
    assert res.terminal_shortfall_kwh == pytest.approx(0, abs=1e-6)   # terminal target is 1 kWh here


def test_exclusivity_holds_under_negative_prices():
    """Negative prices reward wasting energy via simultaneous charge+discharge; binaries forbid it."""
    inp = tiny_inputs()
    inp.price_per_kwh[:] = -20
    res = optimize(inp, BAT, GRID, SIM, OptimizerParams(carbon_price_per_kg=0))
    d = res.dispatch
    assert np.minimum(d.charge, d.discharge).max() <= 1e-6
    assert validate_dispatch(d, inp, BAT, GRID, SIM).all_passed


def test_normal_day_optimizer_valid_and_reproducible():
    sim, bat, grid = SimParams(), BatteryParams(), GridParams()
    inp = make_normal_day(sim)
    a = optimize(inp, bat, grid, sim, OPT)
    b = optimize(make_normal_day(sim), bat, grid, sim, OPT)
    report = validate_dispatch(a.dispatch, inp, bat, grid, sim)
    assert report.all_passed, report.failed()
    assert a.objective == pytest.approx(b.objective, rel=1e-9)
    assert a.flex_unserved_kwh == pytest.approx(0, abs=1e-6)


def test_optimizer_objective_not_worse_than_baseline():
    """The baseline dispatch is a feasible point of the MILP, so the optimum can't be worse
    when both are scored with the same objective."""
    sim, bat, grid = SimParams(), BatteryParams(), GridParams()
    inp = make_normal_day(sim)
    res = optimize(inp, bat, grid, sim, OPT)
    base = run_baseline(inp, bat, grid, sim)
    j_base = evaluate_objective(base, inp, bat, sim, OPT)["total"]
    assert res.objective <= j_base + 1e-6
    assert res.objective_terms["total"] == pytest.approx(res.objective, rel=1e-6)


def test_storage_adjusted_comparison_charges_battery_drawdown():
    sim, bat, grid = SimParams(), BatteryParams(), GridParams()
    inp = make_normal_day(sim)
    m = compute_metrics(run_baseline(inp, bat, grid, sim), inp, bat, sim)
    drawn = m["battery_e_init_kwh"] - m["battery_e_final_kwh"]
    assert drawn > 0
    assert m["cost_storage_adjusted"] - m["cost"] == pytest.approx(
        drawn / bat.eta_charge * inp.price_per_kwh.mean())


def test_plan_unique_across_solver_paths(monkeypatch):
    """Regression: without the tie-break, presolve on/off returned equal-cost plans that
    differed by up to 50 kW, making results machine-dependent."""
    import scipy.optimize
    import src.optimizer as O
    sim, bat, grid = SimParams(), BatteryParams(), GridParams()
    inp = make_normal_day(sim)
    real = scipy.optimize.milp

    def solve(presolve):
        monkeypatch.setattr(O, "milp", lambda *a, **k: real(
            *a, **{**k, "options": {**k["options"], "presolve": presolve}}))
        return O.optimize(inp, bat, grid, sim, OPT).dispatch

    a, b = solve(True), solve(False)
    for f in ("pv_used", "grid_import", "charge", "discharge", "flex_served", "crit_served"):
        assert np.allclose(getattr(a, f), getattr(b, f), atol=1e-5), f


def test_default_penalty_hierarchy_holds():
    assert check_penalty_hierarchy(make_normal_day(), BatteryParams(), OPT) == []
    bad = OptimizerParams(voll_per_kwh=50)
    assert check_penalty_hierarchy(make_normal_day(), BatteryParams(), bad)
