# GridGuard — Methodology

All inputs are synthetic; all results are simulated estimates.

## 1. Microgrid model (`src/microgrid.py`)

Discrete time, Δt = 0.25 h, T = 96 steps (24 h). Every power variable is ≥ 0 kW and its
direction is in its name. There is no grid export, so unused solar is curtailed.

| Symbol | Meaning | Unit |
|---|---|---|
| `pv[t]` | solar used (≤ available solar) | kW |
| `g[t]` | grid import (≤ limit × grid available) | kW |
| `c[t]`, `d[t]` | battery charge / discharge | kW |
| `cs[t]`, `fs[t]` | critical / flexible load served | kW |
| `E[t]` | stored energy at the **start** of step t (T + 1 values) | kWh |

**Power balance:** `pv + g + d = cs + fs + c` at every step.

**Battery dynamics:** `E[t+1] = E[t] + η_c·c[t]·Δt − d[t]·Δt/η_d`, with `E[0]` the initial
state and `E_min ≤ E ≤ E_max`.

**Outage reserve:** while the grid is available, the battery may not discharge below the reserve
level (30 %). During an outage it may go down to the physical minimum (10 %).

**Flexible load:** a daily energy requirement, deliverable at up to its power limit inside an
allowed window.

## 2. Optimizer (`src/optimizer.py`)

**Solver:** SciPy `milp` (HiGHS). It ships with SciPy, so there is nothing extra to install on
macOS, Linux or Windows.

**Charge/discharge exclusivity:** one binary `u[t]` per step, with `c ≤ P_c·u` and
`d ≤ P_d·(1 − u)`. This is exact, not a relaxation. A test with negative prices, which would
reward simultaneous charging and discharging, confirms the binaries prevent it.

**Reserve, linearized with the same binary:** on grid-up steps, `E[t+1] + (E_res − E_min)·u ≥ E_res`.
In discharge mode (u = 0) the battery must stay above the reserve. In charge or idle mode only
the physical floor applies, so the problem stays feasible after an outage drains the battery.

**Objective (₹):**
```
J = Σ Δt·(price + carbon_price·intensity)·g        energy cost + priced emissions
  + VOLL · Σ Δt·(crit − cs)                         unserved critical load
  + flex_penalty · flex_unserved_kWh
  + terminal_penalty · end_of_day_shortfall_kWh
  + degradation · Σ Δt·(c + d)
```
Every load and the end-of-day target are *soft* with ranked penalties, so the MILP is always
feasible. Physical impossibility shows up as reported unserved energy, never as a silent failure.

**Penalty hierarchy:** VOLL ₹1000/kWh > flexible ₹100 > end-of-day ₹50 > maximum energy cost.
`check_penalty_hierarchy()` verifies the ordering, including round-trip battery losses, so the
solver always sheds flexible load before critical load, and drains the battery below its target
before shedding flexible load.

**Lexicographic tie-break (stage 2):** many schedules reach exactly the same minimum cost, and
different solver builds returned different ones, which made results machine-dependent. Among
plans within ₹10⁻⁴ of the minimum, stage 2 keeps the most stored energy over the day and finishes
flexible load earliest. This makes the plan unique and favors resilience.

**Polish LP:** HiGHS returns binaries within its integrality tolerance (e.g. 0.99999996). The
binaries are rounded and fixed, and the remaining LP is re-solved, so the continuous dispatch is
exactly consistent with them (worst constraint violation about 10⁻¹³).

Solve time is about 0.2–5 s per 96-step day on a laptop.

## 3. Controllers compared (`src/baseline.py`, `src/scenarios.py`)

| Controller | Description |
|---|---|
| Baseline | Solar self-consumption: solar → load → battery; battery covers deficits down to the reserve; then grid. Flexible load runs at its nominal time. No grid charging. |
| Baseline + solar-following flex | Same, but flexible load runs whenever there is solar surplus, forced on late if needed to finish. A deliberately strong rule-based competitor. |
| GridGuard (re-optimized) | Day-ahead MILP on the forecast, executed until a disturbance is observed, then re-optimized for the rest of the day from the actual battery state. |
| Oracle | MILP with perfect foresight of the actual day. A lower bound on cost, not a deployable controller. |

All four use identical physical limits, and the same independent validator checks all four.

## 4. Fair comparison (`src/metrics.py`)

A controller that ends the day with an emptier battery has borrowed energy. *Storage-adjusted*
metrics charge the net drawdown at the cost and carbon of replacing it from the grid:
```
adj_cost      = cost      + (E_0 − E_T)/η_c · mean(price)
adj_emissions = emissions + (E_0 − E_T)/η_c · mean(intensity)
```

## 5. Carbon accounting (`src/carbon.py`)

Emissions are counted when energy is imported: `C = Σ g[t]·Δt·intensity[t]` (kg CO₂e). Grid
energy that charges the battery is counted at import time. Discharge is neither free nor
double-counted. Solar counts as zero operational emissions.

**Decomposition** of an emissions change into a *volume* effect (less grid energy) and a *timing*
effect (cleaner hours), with `I = C/G` the average import intensity:
```
C_base − C_new = (G_base − G_new)·I_base  +  G_new·(I_base − I_new)
```
This identity is exact and tested.

## 6. Audit ledger and blockchain anchor (`src/ledger.py`, `contracts/`, `src/chain.py`)

Each record holds the run ID, timestamp, scenario, a SHA-256 hash of the inputs, the full
configuration, the dispatch, the metrics, the validation results and the previous record's hash.
Its own hash is SHA-256 over canonical JSON (sorted keys, no whitespace, NaN rejected). Records
are stored off-chain as JSON Lines.

`GridGuardAnchor.sol` (Solidity 0.8.28, pinned and reproducibly compiled) stores, per publisher
address and ledger ID (the hash of the first record), an append-only list of
`(headHash, nRecords, timestamp, block)`. The record count can never decrease, so truncation
cannot be hidden. Verification is read-only: it checks the local chain, then checks that record
`nRecords−1` still has the anchored hash. Records added after an anchor are allowed.

## 7. Scenarios (`src/scenarios.py`)

| Scenario | Change from the normal day |
|---|---|
| Normal | Forecast = actual |
| Solar shock | Solar at 20 % of forecast, 12:00–15:00 |
| Grid outage | Grid unavailable 18:00–21:00, unannounced |
| Demand spike | Critical demand +60 kW, 19:00–21:00 |
| Monsoon flat tariff | Solar at 30 %, flat ₹8/kWh, grid cleaner 09:00–16:00 (illustrative); a different day, not a disturbance |
| Outage sweep | 3 h unannounced outage starting at each even hour |

All scenarios are deterministic.
