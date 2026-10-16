"""MILP dispatch optimizer (SciPy `milp`, HiGHS backend; no extra solver install).

Decision variables per step t (T steps):
    pv[t], g[t], c[t], dch[t], cs[t], fs[t] >= 0   (kW)    see microgrid.py
    E[t+1]                                         (kWh)   stored energy after step t
    u[t] in {0, 1}                                         1 = charge mode, 0 = discharge mode
plus two scalar slacks (kWh): fu (flexible energy not delivered), ts (terminal shortfall).

Constraints:
    balance        pv + g + dch - cs - fs - c = 0
    dynamics       E[t+1] - E[t] - eta_c*dt*c + dt/eta_d*dch = 0,   E[0] = E_init
    exclusivity    c <= Pc_max * u,   dch <= Pd_max * (1 - u)          (binary => exact)
    reserve        grid up at t:  E[t+1] + (E_res - E_min) * u >= E_res
                   i.e. in discharge mode the battery may not end below the reserve; in charge
                   mode (which includes idling) only the physical floor applies, so the problem
                   stays feasible after an outage leaves the battery below reserve.
    flex energy    sum(fs)*dt + fu = E_flex
    terminal       E[T] + ts >= E_terminal
    bounds         pv <= solar, g <= G_max*avail, cs <= crit, fs <= flex_max, E_min <= E <= E_max

Objective (currency):
    J = sum_t dt*(price + carbon_price*carbon)*g          energy cost + priced emissions
      + voll * sum_t dt*(crit - cs)                       unserved critical load
      + flex_penalty * fu + terminal_penalty * ts
      + degradation * sum_t dt*(c + dch)

Every load and the terminal target are soft (with ranked penalties), and idling is always
allowed, so the MILP is feasible by construction. Physical infeasibility therefore never
disappears silently: it appears as reported unserved critical energy.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from .config import BatteryParams, GridParams, OptimizerParams, SimParams
from .data import ScenarioInputs
from .microgrid import Dispatch, battery_trajectory

BLOCKS = ("pv", "g", "c", "dch", "cs", "fs", "E", "u")


class OptimizationError(RuntimeError):
    pass


@dataclass
class OptimizationResult:
    dispatch: Dispatch
    status: str
    objective: float
    objective_terms: dict[str, float]
    solve_time_s: float
    mip_gap: float | None
    flex_unserved_kwh: float
    terminal_shortfall_kwh: float


def _check(res, stage: str) -> None:
    if res.x is None:
        raise OptimizationError(f"{stage}: no solution (status {res.status}): {res.message}")
    if res.status != 0:
        raise OptimizationError(f"{stage}: optimality not proven (status {res.status}): {res.message}")


def check_penalty_hierarchy(inp: ScenarioInputs, battery: BatteryParams,
                            opt: OptimizerParams) -> list[str]:
    """Return a list of violated ordering conditions (empty list = hierarchy holds).

    Conservative conditions: each tier must outweigh the most it could save in the tier below,
    including round-trip losses (1 kWh in the battery delivers at most eta_d kWh, and costs up to
    1/eta_c kWh of grid energy to replace).
    """
    max_energy_cost = float(np.max(inp.price_per_kwh + opt.carbon_price_per_kg * inp.carbon_kg_per_kwh))
    max_energy_cost = max(max_energy_cost, 0.0) + 2 * opt.degradation_per_kwh
    problems = []
    if opt.terminal_shortfall_penalty_per_kwh <= max_energy_cost / battery.eta_charge:
        problems.append("terminal penalty must exceed max grid cost per stored kWh")
    if opt.flex_unserved_penalty_per_kwh <= opt.terminal_shortfall_penalty_per_kwh / battery.eta_discharge:
        problems.append("flexible-load penalty must exceed terminal penalty per delivered kWh")
    if opt.voll_per_kwh <= opt.flex_unserved_penalty_per_kwh:
        problems.append("VOLL must exceed flexible-load penalty")
    return problems


def evaluate_objective(d: Dispatch, inp: ScenarioInputs, battery: BatteryParams,
                       sim: SimParams, opt: OptimizerParams) -> dict[str, float]:
    """Evaluate the optimizer's objective J for ANY dispatch (e.g. the baseline's)."""
    dt = sim.dt_h
    E = battery_trajectory(d.charge, d.discharge, battery, dt)
    terms = {
        "energy_cost": float(np.sum(dt * inp.price_per_kwh * d.grid_import)),
        "carbon_cost": float(np.sum(dt * opt.carbon_price_per_kg * inp.carbon_kg_per_kwh * d.grid_import)),
        "unserved_critical_penalty": float(opt.voll_per_kwh * np.sum(dt * (inp.crit_demand_kw - d.crit_served))),
        "unserved_flex_penalty": opt.flex_unserved_penalty_per_kwh
        * max(0.0, inp.flex_energy(dt) - float(d.flex_served.sum() * dt)),
        "terminal_shortfall_penalty": opt.terminal_shortfall_penalty_per_kwh
        * max(0.0, battery.e_terminal_min - float(E[-1])),
        "degradation_cost": float(opt.degradation_per_kwh * np.sum(dt * (d.charge + d.discharge))),
    }
    terms["total"] = sum(terms.values())
    return terms


def optimize(inp: ScenarioInputs, battery: BatteryParams, grid: GridParams,
             sim: SimParams, opt: OptimizerParams = OptimizerParams()) -> OptimizationResult:
    T, dt = inp.T, sim.dt_h
    nb = len(BLOCKS)
    n = nb * T + 2                       # + fu, ts
    FU, TS = nb * T, nb * T + 1

    def ix(block: str, t: int) -> int:
        return BLOCKS.index(block) * T + t

    # ---- objective ----
    cost = np.zeros(n)
    for t in range(T):
        cost[ix("g", t)] = dt * (inp.price_per_kwh[t] + opt.carbon_price_per_kg * inp.carbon_kg_per_kwh[t])
        cost[ix("cs", t)] = -opt.voll_per_kwh * dt   # constant voll*crit*dt added back below
        cost[ix("c", t)] = opt.degradation_per_kwh * dt
        cost[ix("dch", t)] = opt.degradation_per_kwh * dt
    cost[FU] = opt.flex_unserved_penalty_per_kwh
    cost[TS] = opt.terminal_shortfall_penalty_per_kwh
    const = opt.voll_per_kwh * dt * float(inp.crit_demand_kw.sum())

    # ---- bounds ----
    lb, ub = np.zeros(n), np.full(n, np.inf)
    for t in range(T):
        ub[ix("pv", t)] = inp.solar_avail_kw[t]
        ub[ix("g", t)] = grid.import_max_kw * inp.grid_available[t]
        ub[ix("c", t)] = battery.p_charge_max_kw
        ub[ix("dch", t)] = battery.p_discharge_max_kw
        ub[ix("cs", t)] = inp.crit_demand_kw[t]
        ub[ix("fs", t)] = inp.flex_max_kw[t]
        lb[ix("E", t)], ub[ix("E", t)] = battery.e_min, battery.e_max
        ub[ix("u", t)] = 1.0
    integrality = np.zeros(n)
    integrality[[ix("u", t) for t in range(T)]] = 1

    # ---- linear constraints ----
    rows = 4 * T + 2 + int(inp.grid_available.sum())
    A = lil_matrix((rows, n))
    lo, hi = np.zeros(rows), np.zeros(rows)
    r = 0
    for t in range(T):
        # power balance
        for b, s in (("pv", 1), ("g", 1), ("dch", 1), ("cs", -1), ("fs", -1), ("c", -1)):
            A[r, ix(b, t)] = s
        r += 1
        # battery dynamics (E[0] is the constant e_init)
        A[r, ix("E", t)] = 1.0
        A[r, ix("c", t)] = -battery.eta_charge * dt
        A[r, ix("dch", t)] = dt / battery.eta_discharge
        if t == 0:
            lo[r] = hi[r] = battery.e_init
        else:
            A[r, ix("E", t - 1)] = -1.0
        r += 1
        # exclusivity: c - Pc*u <= 0 ; dch + Pd*u <= Pd
        A[r, ix("c", t)], A[r, ix("u", t)] = 1.0, -battery.p_charge_max_kw
        lo[r], hi[r] = -np.inf, 0.0
        r += 1
        A[r, ix("dch", t)], A[r, ix("u", t)] = 1.0, battery.p_discharge_max_kw
        lo[r], hi[r] = -np.inf, battery.p_discharge_max_kw
        r += 1
        # reserve (grid-up steps only)
        if inp.grid_available[t] > 0.5:
            A[r, ix("E", t)], A[r, ix("u", t)] = 1.0, battery.e_reserve - battery.e_min
            lo[r], hi[r] = battery.e_reserve, np.inf
            r += 1
    # flexible energy
    for t in range(T):
        A[r, ix("fs", t)] = dt
    A[r, FU] = 1.0
    lo[r] = hi[r] = inp.flex_energy(dt)
    r += 1
    # terminal energy
    A[r, ix("E", T - 1)], A[r, TS] = 1.0, 1.0
    lo[r], hi[r] = battery.e_terminal_min, np.inf
    r += 1
    assert r == rows

    t0 = time.perf_counter()
    base_cons = LinearConstraint(A.tocsr(), lo, hi)
    options = {"time_limit": opt.time_limit_s, "mip_rel_gap": opt.mip_rel_gap}
    res = milp(cost, integrality=integrality, bounds=Bounds(lb, ub),
               constraints=base_cons, options=options)
    _check(res, "stage 1 (minimize J)")

    if opt.tie_break:
        # Stage 2 (lexicographic tie-break): many dispatches reach the same minimum J, and
        # different solver builds return different ones. Among plans within tie_break_tol of
        # the minimum, choose the one that (a) keeps the most stored energy over the horizon
        # (kWh*h) and (b) completes flexible load earlier (0.1 per kWh*h of delay). This makes the
        # plan reproducible across machines and favors resilience to later disturbances.
        j_cap = LinearConstraint(cost.reshape(1, -1), -np.inf, res.fun + opt.tie_break_tol)
        cost2 = np.zeros(n)
        for t in range(T):
            cost2[ix("E", t)] = -dt
            cost2[ix("fs", t)] = 0.1 * dt * (t * dt)
        res2 = milp(cost2, integrality=integrality, bounds=Bounds(lb, ub),
                    constraints=[base_cons, j_cap], options=options)
        _check(res2, "stage 2 (tie-break)")
        res = res2
    solve_time = time.perf_counter() - t0

    x = res.x
    get = lambda b: np.clip(x[BLOCKS.index(b) * T:(BLOCKS.index(b) + 1) * T], 0.0, None)
    d = Dispatch(pv_used=get("pv"), grid_import=get("g"), charge=get("c"), discharge=get("dch"),
                 crit_served=get("cs"), flex_served=get("fs"))
    # Remove sub-tolerance solver noise on exclusivity (|value| < 1e-9 by construction of u).
    u = np.round(get("u"))
    d.charge = np.where(u > 0.5, d.charge, 0.0)
    d.discharge = np.where(u > 0.5, 0.0, d.discharge)

    return OptimizationResult(
        dispatch=d,
        status="optimal",
        objective=float(cost @ x + const),
        objective_terms=evaluate_objective(d, inp, battery, sim, opt),
        solve_time_s=solve_time,
        mip_gap=getattr(res, "mip_gap", None),
        flex_unserved_kwh=float(x[FU]),
        terminal_shortfall_kwh=float(x[TS]),
    )
