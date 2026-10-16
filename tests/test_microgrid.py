import numpy as np
import pytest

from src.baseline import run_baseline
from src.config import BatteryParams, GridParams, SimParams
from src.data import ScenarioInputs, make_normal_day
from src.microgrid import Dispatch, battery_trajectory, power_balance_residual, unserved_critical
from src.validation import validate_dispatch

# Small system whose numbers are easy to verify by hand.
BAT = BatteryParams(capacity_kwh=10, p_charge_max_kw=5, p_discharge_max_kw=5,
                    eta_charge=0.9, eta_discharge=0.9, soc_init=0.5, soc_min=0.1,
                    soc_max=0.9, soc_reserve=0.3, soc_terminal_min=0.1)
GRID = GridParams(import_max_kw=10)
SIM = SimParams(dt_h=1.0, n_steps=3)


def tiny_inputs() -> ScenarioInputs:
    return ScenarioInputs(
        name="hand_calc",
        solar_avail_kw=[6, 0, 0],
        crit_demand_kw=[2, 4, 4],
        flex_nominal_kw=[1, 0, 0],
        flex_max_kw=[1, 0, 0],
        price_per_kwh=[5, 5, 5],
        carbon_kg_per_kwh=[0.7, 0.7, 0.7],
        grid_available=[1, 1, 0],   # outage in the last hour
    )


def test_battery_trajectory_hand_calc():
    # E1 = 5 + 0.9*3 = 7.7 ; E2 = 7.7 - 4/0.9 = 3.2556
    E = battery_trajectory(np.array([3.0, 0.0]), np.array([0.0, 4.0]), BAT, 1.0)
    assert E == pytest.approx([5.0, 7.7, 7.7 - 4 / 0.9])


def test_energy_conservation_identity():
    rng = np.random.default_rng(0)
    c, dch = rng.uniform(0, 5, 20), rng.uniform(0, 5, 20)
    E = battery_trajectory(c, dch, BAT, 0.25)
    expected = BAT.e_init + 0.9 * c.sum() * 0.25 - dch.sum() * 0.25 / 0.9
    assert E[-1] == pytest.approx(expected)


def test_baseline_hand_calc():
    """Hour 0: 6 kW solar, 3 kW load -> charge 3 kW, E=7.7.
    Hour 1: 4 kW deficit, grid up, floor = reserve 3 kWh -> discharge min(4, 5, (7.7-3)*0.9=4.23) = 4.
    Hour 2: outage, floor = e_min 1 kWh -> discharge (3.2556-1)*0.9 = 2.03 kW,
            unserved critical = 4 - 2.03 = 1.97 kW (physically unavoidable)."""
    inp = tiny_inputs()
    d = run_baseline(inp, BAT, GRID, SIM)
    e2 = 7.7 - 4 / 0.9
    dis2 = (e2 - 1.0) * 0.9
    assert d.charge == pytest.approx([3, 0, 0])
    assert d.discharge == pytest.approx([0, 4, dis2])
    assert d.grid_import == pytest.approx([0, 0, 0])
    assert unserved_critical(d, inp) == pytest.approx([0, 0, 4 - dis2])
    E = battery_trajectory(d.charge, d.discharge, BAT, 1.0)
    assert E[-1] == pytest.approx(1.0)   # drained to the physical floor, not below

    report = validate_dispatch(d, inp, BAT, GRID, SIM)
    assert report.all_passed, report.failed()


def test_baseline_imports_when_battery_at_reserve():
    inp = tiny_inputs()
    bat = BatteryParams(capacity_kwh=10, p_charge_max_kw=5, p_discharge_max_kw=5,
                        eta_charge=0.9, eta_discharge=0.9, soc_init=0.3, soc_min=0.1,
                        soc_max=0.9, soc_reserve=0.3, soc_terminal_min=0.1)
    inp.solar_avail_kw[:] = 0
    inp.grid_available[:] = 1
    d = run_baseline(inp, bat, GRID, SIM)
    assert d.discharge == pytest.approx([0, 0, 0])            # already at reserve
    assert d.grid_import == pytest.approx([3, 4, 4])
    assert unserved_critical(d, inp) == pytest.approx([0, 0, 0])


def test_grid_limit_sheds_flex_before_critical():
    inp = tiny_inputs()
    inp.solar_avail_kw[:] = 0
    inp.grid_available[:] = 1
    bat = BatteryParams(capacity_kwh=10, p_charge_max_kw=5, p_discharge_max_kw=5,
                        eta_charge=0.9, eta_discharge=0.9, soc_init=0.3, soc_min=0.1,
                        soc_max=0.9, soc_reserve=0.3, soc_terminal_min=0.1)
    d = run_baseline(inp, bat, GridParams(import_max_kw=2.5), SIM)
    assert d.crit_served[0] == pytest.approx(2.0)   # critical fully served
    assert d.flex_served[0] == pytest.approx(0.5)   # flexible partly shed


@pytest.mark.parametrize("field,value,check", [
    ("grid_import", [0, 20, 0], "grid_import_limit"),
    ("charge", [6, 0, 0], "charge_power_limit"),
    ("pv_used", [7, 0, 0], "solar_availability"),
])
def test_validator_catches_violations(field, value, check):
    inp = tiny_inputs()
    d = run_baseline(inp, BAT, GRID, SIM)
    setattr(d, field, np.array(value, dtype=float))
    names = {c.name for c in validate_dispatch(d, inp, BAT, GRID, SIM).failed()}
    assert check in names


def test_validator_catches_simultaneous_charge_discharge():
    inp = tiny_inputs()
    d = run_baseline(inp, BAT, GRID, SIM)
    d.charge[1] += 1.0
    d.discharge[1] += 1.0   # balance still holds, energy is just wasted
    assert power_balance_residual(d) == pytest.approx([0, 0, 0])
    names = {c.name for c in validate_dispatch(d, inp, BAT, GRID, SIM).failed()}
    assert "charge_discharge_exclusive" in names


def test_validator_catches_over_discharge_during_outage():
    inp = tiny_inputs()
    d = run_baseline(inp, BAT, GRID, SIM)
    d.discharge[2] = 4.0
    d.crit_served[2] = 4.0
    names = {c.name for c in validate_dispatch(d, inp, BAT, GRID, SIM).failed()}
    assert "battery_energy_min" in names


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        BatteryParams(soc_min=0.5, soc_reserve=0.3)
    with pytest.raises(ValueError):
        BatteryParams(eta_charge=1.2)


def test_normal_day_baseline_is_physically_valid_and_reproducible():
    sim = SimParams()
    bat, grid = BatteryParams(), GridParams()
    a = run_baseline(make_normal_day(sim), bat, grid, sim)
    b = run_baseline(make_normal_day(sim), bat, grid, sim)
    assert a.to_dict() == b.to_dict()
    report = validate_dispatch(a, make_normal_day(sim), bat, grid, sim, require_terminal=False)
    assert report.all_passed, report.failed()
