import numpy as np
import pytest

from src.carbon import decompose_emissions_change, grid_emissions_kg
from src.config import BatteryParams, SimParams
from src.data import make_normal_day
from src.metrics import compute_metrics
from src.microgrid import Dispatch
from tests.test_microgrid import tiny_inputs


def test_emissions_hand_calc():
    inp = tiny_inputs()
    inp.carbon_kg_per_kwh[:] = [0.5, 0.8, 0.9]
    d = Dispatch.zeros(3)
    d.grid_import[:] = [10, 4, 0]
    assert grid_emissions_kg(d, inp, 1.0) == pytest.approx(10 * 0.5 + 4 * 0.8)


def test_grid_charging_is_counted_and_discharge_is_not_free():
    """Import 10 kWh at 0.5 kg/kWh into the battery, discharge it later: emissions are the
    10 kWh * 0.5 at import time; the discharge step adds nothing and is not credited."""
    inp = tiny_inputs()
    inp.carbon_kg_per_kwh[:] = [0.5, 0.9, 0.9]
    d = Dispatch.zeros(3)
    d.grid_import[0], d.charge[0] = 10, 10
    d.discharge[1] = 5
    assert grid_emissions_kg(d, inp, 1.0) == pytest.approx(5.0)


def test_decomposition_is_exact():
    r = decompose_emissions_change(g_base=500, c_base=420, g_new=450, c_new=360)
    assert r["volume_effect_kg"] + r["timing_effect_kg"] == pytest.approx(r["total_reduction_kg"])
    assert r["volume_effect_kg"] == pytest.approx(50 * 420 / 500)


def test_pure_timing_shift():
    """Same grid energy, cleaner hours: the whole reduction is a timing effect."""
    r = decompose_emissions_change(g_base=100, c_base=80, g_new=100, c_new=70)
    assert r["volume_effect_kg"] == pytest.approx(0)
    assert r["timing_effect_kg"] == pytest.approx(10)


def test_storage_adjusted_grid_energy():
    sim, bat = SimParams(), BatteryParams()
    inp = make_normal_day(sim)
    d = Dispatch.zeros(sim.n_steps)
    d.discharge[:] = 0
    d.charge[0] = 10.0      # 10 kW for 15 min from (fictional) grid
    d.grid_import[0] = 10.0
    m = compute_metrics(d, inp, bat, sim)
    # Battery gained 0.95 * 2.5 kWh; credit = 2.375 / 0.95 = 2.5 kWh of grid energy.
    assert m["grid_import_storage_adjusted_kwh"] == pytest.approx(2.5 - 2.5)
