import numpy as np
import pytest

from src.baseline import run_baseline
from src.config import BatteryParams, GridParams, SimParams
from src.data import make_normal_day
from src.optimizer import optimize
from src.scenarios import CONTROLLERS, SCENARIO_NAMES, make_scenario, outage_scenario, run_scenario
from src.validation import validate_dispatch

SIM, BAT, GRID = SimParams(), BatteryParams(), GridParams()


@pytest.fixture(scope="module")
def results():
    return {n: run_scenario(make_scenario(n, SIM)) for n in SCENARIO_NAMES}


def test_scenarios_deterministic():
    for n in SCENARIO_NAMES:
        a, b = make_scenario(n, SIM), make_scenario(n, SIM)
        assert np.array_equal(a.actual.solar_avail_kw, b.actual.solar_avail_kw)
        assert np.array_equal(a.actual.grid_available, b.actual.grid_available)
        assert np.array_equal(a.actual.crit_demand_kw, b.actual.crit_demand_kw)


def test_forecast_matches_actual_before_disturbance():
    for n in ("solar_shock", "grid_outage", "demand_spike"):
        s = make_scenario(n, SIM)
        t = s.t_disturbance
        assert np.array_equal(s.forecast.solar_avail_kw[:t], s.actual.solar_avail_kw[:t])
        assert np.array_equal(s.forecast.grid_available[:t], s.actual.grid_available[:t])
        assert not (np.array_equal(s.forecast.solar_avail_kw, s.actual.solar_avail_kw)
                    and np.array_equal(s.forecast.grid_available, s.actual.grid_available)
                    and np.array_equal(s.forecast.crit_demand_kw, s.actual.crit_demand_kw))


def test_every_controller_physically_valid_in_every_scenario(results):
    for n, res in results.items():
        for c in CONTROLLERS:
            v = res.runs[c].validation
            assert v.physical_ok, (n, c, v.failed())


def test_optimizers_meet_all_targets(results):
    for n, res in results.items():
        for c in ("reoptimized", "oracle"):
            assert res.runs[c].validation.all_passed, (n, c, res.runs[c].validation.failed())


def test_oracle_is_lower_bound_on_score(results):
    """Oracle solves the actual-day MILP; every other dispatch is a feasible point of it."""
    for n, res in results.items():
        j_o = res.runs["oracle"].metrics["objective_J"]
        for c in CONTROLLERS:
            assert j_o <= res.runs[c].metrics["objective_J"] + 1e-4, (n, c)


def test_reoptimized_follows_plan_before_disturbance():
    s = make_scenario("solar_shock", SIM)
    plan = optimize(s.forecast, BAT, GRID, SIM).dispatch
    d = run_scenario(s).runs["reoptimized"].dispatch
    t = s.t_disturbance
    assert np.allclose(d.grid_import[:t], plan.grid_import[:t])
    assert np.allclose(d.charge[:t], plan.charge[:t])


def test_outage_shortfall_limited_by_discharge_power(results):
    """18:00-21:00: critical 55 kW, no solar, battery full but limited to 50 kW discharge.
    Unavoidable shortfall = (55 - 50) kW * 3 h = 15 kWh."""
    o = results["grid_outage"].runs["oracle"].metrics["critical_unserved_kwh"]
    assert o == pytest.approx(15.0, abs=1e-4)
    assert results["grid_outage"].runs["baseline"].metrics["critical_unserved_kwh"] > o


def test_advance_notice_helps_for_late_outage():
    res = run_scenario(outage_scenario(20, 3, SIM))
    assert res.runs["oracle"].metrics["critical_unserved_kwh"] < \
        res.runs["reoptimized"].metrics["critical_unserved_kwh"] - 1.0


def test_solar_following_baseline_delivers_flex_and_is_valid():
    inp = make_normal_day(SIM)
    d = run_baseline(inp, BAT, GRID, SIM, "solar_following")
    assert d.flex_served.sum() * SIM.dt_h == pytest.approx(inp.flex_energy(SIM.dt_h))
    assert validate_dispatch(d, inp, BAT, GRID, SIM, require_terminal=False).all_passed


def test_monsoon_carbon_price_reduces_emissions_without_cost_at_low_price():
    """Flat tariff + little sun: the carbon price is what moves grid use to cleaner hours."""
    from dataclasses import replace
    from src.config import OptimizerParams
    from src.metrics import compute_metrics
    spec = make_scenario("monsoon_flat_tariff", SIM)
    m = {p: compute_metrics(optimize(spec.actual, BAT, GRID, SIM,
                                     replace(OptimizerParams(), carbon_price_per_kg=p)).dispatch,
                            spec.actual, BAT, SIM) for p in (0.0, 2.0, 20.0)}
    assert m[2.0]["emissions_storage_adjusted_kg"] < m[0.0]["emissions_storage_adjusted_kg"] - 5
    assert m[2.0]["cost_storage_adjusted"] == pytest.approx(m[0.0]["cost_storage_adjusted"], abs=1.0)
    assert m[20.0]["emissions_storage_adjusted_kg"] < m[2.0]["emissions_storage_adjusted_kg"]
    assert m[20.0]["cost_storage_adjusted"] > m[2.0]["cost_storage_adjusted"]
