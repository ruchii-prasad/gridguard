"""Deterministic SYNTHETIC disturbance scenarios and the controllers compared on them.

Each scenario has a forecast (what is known day-ahead) and the actual inputs. A disturbance
starts at step t_d; before t_d forecast and actual are identical.

Controllers:
    baseline             rule-based, flexible load at nominal times           (reacts per step)
    baseline_solar_flex  rule-based, flexible load follows solar surplus      (reacts per step)
    reoptimized          optimizer plans day-ahead on the FORECAST, executes the plan until the
                         disturbance is observed at t_d, then re-optimizes the rest of the day
                         from the actual battery state with the actual inputs (one MPC step)
    oracle               optimizer with perfect foresight of the actual inputs: a lower bound,
                         e.g. a load-shedding schedule announced in advance
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from .baseline import run_baseline
from .config import BatteryParams, GridParams, OptimizerParams, SimParams
from .data import ScenarioInputs, make_normal_day
from .metrics import compute_metrics
from .microgrid import FIELDS, Dispatch, battery_trajectory
from .optimizer import evaluate_objective, optimize
from .validation import ValidationReport, validate_dispatch

SCENARIO_NAMES = ("normal", "solar_shock", "grid_outage", "demand_spike", "monsoon_flat_tariff")
CONTROLLERS = ("baseline", "baseline_solar_flex", "reoptimized", "oracle")


@dataclass
class ScenarioSpec:
    name: str
    description: str
    forecast: ScenarioInputs
    actual: ScenarioInputs
    t_disturbance: int | None


@dataclass
class ControllerRun:
    dispatch: Dispatch
    metrics: dict[str, float]
    validation: ValidationReport
    solve_time_s: float = 0.0


@dataclass
class ScenarioResult:
    spec: ScenarioSpec
    runs: dict[str, ControllerRun] = field(default_factory=dict)


def _copy(inp: ScenarioInputs, name: str) -> ScenarioInputs:
    return ScenarioInputs(name=name, solar_avail_kw=inp.solar_avail_kw.copy(),
                          crit_demand_kw=inp.crit_demand_kw.copy(),
                          flex_nominal_kw=inp.flex_nominal_kw.copy(),
                          flex_max_kw=inp.flex_max_kw.copy(),
                          price_per_kwh=inp.price_per_kwh.copy(),
                          carbon_kg_per_kwh=inp.carbon_kg_per_kwh.copy(),
                          grid_available=inp.grid_available.copy(),
                          flex_energy_kwh=inp.flex_energy_kwh)


def make_scenario(name: str, sim: SimParams = SimParams()) -> ScenarioSpec:
    forecast = make_normal_day(sim)
    steps = lambda h0, h1: slice(int(round(h0 / sim.dt_h)), int(round(h1 / sim.dt_h)))
    actual = _copy(forecast, name)
    if name == "normal":
        return ScenarioSpec(name, "Normal operation: forecast = actual.", forecast, actual, None)
    if name == "monsoon_flat_tariff":
        # A different DAY, not a disturbance: forecast = actual. Little sun leaves the battery room
        # to shift grid energy, and a flat tariff gives a cost-only controller no reason to avoid
        # dirty hours, so the carbon price is what drives the timing. Carbon shape is illustrative.
        h = np.arange(sim.n_steps) * sim.dt_h
        day = _copy(forecast, name)
        day.solar_avail_kw *= 0.3
        day.price_per_kwh[:] = 8.0
        day.carbon_kg_per_kwh[:] = np.where((h >= 9) & (h < 16), 0.62,
                                            np.where((h >= 18) & (h < 23), 0.92, 0.85))
        return ScenarioSpec(name, "Monsoon day: 30% of normal solar, flat ₹8/kWh tariff, grid "
                            "cleaner at midday (illustrative carbon shape). Forecast = actual.",
                            day, _copy(day, name), None)
    if name == "solar_shock":
        s = steps(12, 15)
        actual.solar_avail_kw[s] *= 0.2
        desc = "Solar drops to 20% of forecast 12:00-15:00 (e.g. dust storm / heavy cloud)."
    elif name == "grid_outage":
        s = steps(18, 21)
        actual.grid_available[s] = 0.0
        desc = "Unannounced grid outage 18:00-21:00 during the evening peak."
    elif name == "demand_spike":
        s = steps(19, 21)
        actual.crit_demand_kw[s] += 60.0
        desc = "Critical demand +60 kW 19:00-21:00 (e.g. emergency cooling / pumping)."
    else:
        raise ValueError(f"unknown scenario {name!r}; choose from {SCENARIO_NAMES}")
    return ScenarioSpec(name, desc, forecast, actual, s.start)


def _tail(inp: ScenarioInputs, start: int, flex_energy_kwh: float) -> ScenarioInputs:
    return ScenarioInputs(
        name=f"{inp.name}[{start}:]",
        solar_avail_kw=inp.solar_avail_kw[start:], crit_demand_kw=inp.crit_demand_kw[start:],
        flex_nominal_kw=inp.flex_nominal_kw[start:], flex_max_kw=inp.flex_max_kw[start:],
        price_per_kwh=inp.price_per_kwh[start:], carbon_kg_per_kwh=inp.carbon_kg_per_kwh[start:],
        grid_available=inp.grid_available[start:], flex_energy_kwh=max(0.0, flex_energy_kwh))


def reoptimize(spec: ScenarioSpec, battery: BatteryParams, grid: GridParams, sim: SimParams,
               opt: OptimizerParams) -> tuple[Dispatch, float]:
    """Day-ahead plan on the forecast, then re-optimization from t_d on the actual inputs."""
    plan = optimize(spec.forecast, battery, grid, sim, opt)
    t_d = spec.t_disturbance
    if t_d is None:
        return plan.dispatch, plan.solve_time_s
    for a in ("solar_avail_kw", "crit_demand_kw", "grid_available", "price_per_kwh"):
        if not np.allclose(getattr(spec.forecast, a)[:t_d], getattr(spec.actual, a)[:t_d]):
            raise ValueError("forecast and actual must agree before the disturbance")
    pre = plan.dispatch
    E = battery_trajectory(pre.charge, pre.discharge, battery, sim.dt_h)
    e_td = float(np.clip(E[t_d], battery.e_min, battery.e_max))
    flex_done = float(pre.flex_served[:t_d].sum() * sim.dt_h)
    tail_inp = _tail(spec.actual, t_d, spec.actual.flex_energy(sim.dt_h) - flex_done)
    tail_bat = replace(battery, soc_init=e_td / battery.capacity_kwh)
    tail = optimize(tail_inp, tail_bat, grid, replace(sim, n_steps=spec.actual.T - t_d), opt)
    stitched = Dispatch(*(np.concatenate((getattr(pre, f)[:t_d], getattr(tail.dispatch, f)))
                          for f in FIELDS))
    return stitched, plan.solve_time_s + tail.solve_time_s


def run_scenario(spec: ScenarioSpec, battery: BatteryParams = BatteryParams(),
                 grid: GridParams = GridParams(), sim: SimParams = SimParams(),
                 opt: OptimizerParams = OptimizerParams()) -> ScenarioResult:
    out = ScenarioResult(spec)
    act = spec.actual

    def record(name: str, d: Dispatch, solve: float = 0.0) -> None:
        m = compute_metrics(d, act, battery, sim)
        # Same scoring for every controller: the optimizer's objective J, which prices lost load.
        m["objective_J"] = evaluate_objective(d, act, battery, sim, opt)["total"]
        out.runs[name] = ControllerRun(d, m, validate_dispatch(d, act, battery, grid, sim), solve)

    record("baseline", run_baseline(act, battery, grid, sim, "nominal"))
    record("baseline_solar_flex", run_baseline(act, battery, grid, sim, "solar_following"))
    d, s = reoptimize(spec, battery, grid, sim, opt)
    record("reoptimized", d, s)
    if spec.t_disturbance is None:
        out.runs["oracle"] = out.runs["reoptimized"]
    else:
        o = optimize(act, battery, grid, sim, opt)
        record("oracle", o.dispatch, o.solve_time_s)
    return out


def outage_scenario(start_h: float, duration_h: float, sim: SimParams = SimParams()) -> ScenarioSpec:
    """Unannounced outage of given start and duration on the normal day."""
    spec = make_scenario("normal", sim)
    t0 = int(round(start_h / sim.dt_h))
    t1 = min(sim.n_steps, t0 + int(round(duration_h / sim.dt_h)))
    actual = _copy(spec.forecast, f"outage_{start_h:g}h_{duration_h:g}h")
    actual.grid_available[t0:t1] = 0.0
    return ScenarioSpec(actual.name, f"Unannounced {duration_h:g} h outage from {start_h:g}:00.",
                        spec.forecast, actual, t0)
