# GridGuard — Validation, assumptions and limitations

All inputs are **synthetic** and all results are **simulated estimates**. Nothing here is a
measurement of real-world energy, cost or emissions.

Every number below was produced by the scripts in this repository and can be regenerated with
`bash run_all.sh`. Raw outputs are in `results/`.

## 1. What was validated

| Check | How | Result |
|---|---|---|
| Unit and integration tests | `pytest` (73 tests) | 73 passed |
| Fresh install | New virtual environment built only from `requirements.txt`, using exactly the files in the GitHub repository, then `run_all.sh` | All tests and demos pass; identical results fingerprint |
| Cross-machine reproducibility | `run_demo.py` on Linux (Python 3.13, SciPy 1.18.1) and macOS (MacBook Air) | Same fingerprint `2bc9036c5c59` on both |
| Run-to-run reproducibility | `run_validation.py` runs every scenario twice | Max dispatch difference 0.0 kW |
| Physical feasibility, all scenarios × all controllers | Independent validator, 13 physical checks | 16/16 runs pass; worst violation 2.8 × 10⁻¹⁴ |
| Daily energy closure | Σ(solar + grid + discharge) = Σ(load + charge), and the battery energy identity | Worst error 6.4 × 10⁻¹⁴ kWh |
| Randomized stress test | 25 seeded random microgrids in the suite, plus a 300-case ad-hoc run: random solar, loads, outages, prices, battery size/limits/efficiencies, grid limit (incl. zero) | 0 failures; worst physical violation 1.1 × 10⁻¹³ |
| Optimality sanity | For every scenario and random case, the optimizer's objective ≤ each baseline's objective (baselines are feasible points of the same MILP); oracle ≤ every controller | Holds in all cases |
| Hand calculations | 3-step battery/outage example, 3-hour unavoidable-shortfall case (8.4 kWh), outage power limit (15 kWh) | Match to 10⁻⁵ |
| Tamper evidence | `run_tamper_demo.py` on a copy of the ledger | Edits, re-hashed edits and deletions detected (deletion only against the anchored head; see §4) |

### The validator's 14 checks

Physical (must never fail): non-negativity, power balance, solar availability, grid import limit
(zero during outages), charge power limit, discharge power limit, charge/discharge exclusivity,
battery energy ≤ max, battery energy ≥ min, outage reserve respected while the grid is up,
critical served ≤ critical demand, flexible power ≤ its limit, flexible energy not exceeded.

Target (operating goal, may be missed): end-of-day battery energy ≥ target. The rule-based
baselines do not pursue this target, so they report "target missed"; the comparison corrects for
it with storage-adjusted metrics (§3).

## 2. Issues found and fixed during validation

Recorded because they affected results and show what the tests are for.

1. **Machine-dependent plans.** Many dispatch schedules reach exactly the same minimum cost, and
   the solver could return any of them: two solver settings on the same machine gave equal-cost
   plans up to 50 kW apart, and macOS and Linux produced different re-optimized results (e.g.
   solar-shock cost ₹5,181 vs ₹5,221). Fixed with a lexicographic second stage: among
   plans within ₹10⁻⁴ of the minimum, keep the most stored energy and finish flexible load
   earlier. Regression test: `test_plan_unique_across_solver_paths`.
2. **Solver tolerance leaking into the dispatch.** HiGHS returns binaries such as 0.99999996,
   which left micro-kW of allowed simultaneous charge/discharge; an earlier clean-up step then
   unbalanced some steps by ~2 × 10⁻⁶ kW. Found by the randomized tests (2 of 25 cases). Fixed by
   rounding the binaries, fixing them, and re-solving the remaining LP. Worst violation went from
   2 × 10⁻⁶ to 10⁻¹³.
3. **Tie-break tolerance too loose.** At ₹0.01 the tie-break could trade 10⁻⁵ kWh of critical
   load for stored energy. Tightened to ₹10⁻⁴ (at most 10⁻⁷ kWh, below the validator tolerance);
   values below ~10⁻⁵ fall under the solver's own feasibility tolerance.

## 3. Modelling assumptions

| Item | Value | Note |
|---|---|---|
| Time step / horizon | 15 min / 24 h (96 steps) | Configurable in `src/config.py` |
| Battery | 200 kWh, 50 kW charge, 50 kW discharge | Synthetic campus-scale system |
| Efficiencies | 95 % charge, 95 % discharge | Constant; no temperature or rate dependence |
| State-of-charge limits | 10 % min, 95 % max | |
| Outage reserve | 30 % — no discharge below this while the grid is up | Policy choice, configurable |
| End-of-day target | 50 % (= starting level) | Soft target, penalised if missed |
| Grid import limit | 150 kW; no export | Surplus solar is curtailed |
| Solar | Half-sine, 06:00–18:00, 120 kW peak | Synthetic, not a measured profile |
| Loads | Critical 40–60 kW; flexible 120 kWh/day, nominally 18:00–22:00, movable 08:00–24:00 at ≤ 40 kW | Synthetic |
| Tariff | ₹5 (00–06), ₹7.5 (day), ₹11 (18–22) per kWh | Illustrative time-of-day tariff |
| Grid carbon intensity | 0.65–0.88 kg CO₂e/kWh | Illustrative shape, not a sourced dataset |
| Carbon price | ₹2/kg CO₂e | **Assumed**; sweep 0–20 shows dispatch is insensitive here (§4) |
| Penalties | Lost critical load ₹1000/kWh > unserved flexible ₹100 > end-of-day shortfall ₹50 > energy cost | Ordering checked by `check_penalty_hierarchy` |
| Degradation | ₹0.5 per kWh of battery throughput | Linear proxy, not a cycle-ageing model |
| Fair comparison | Storage-adjusted cost/emissions charge each controller for battery energy drawn down by end of day, at mean price and intensity, grossed up for charging losses | See `src/metrics.py` |

## 4. Limitations (stated plainly)

- **Synthetic data.** Profiles are illustrative shapes. Absolute numbers (₹, kg) describe this
  synthetic system only and are not projections for any real site.
- **Perfect forecasts within each plan.** The re-optimized controller plans on a forecast and
  re-plans once when a disturbance is observed; it does not model forecast error, rolling
  re-planning every step, or uncertainty.
- **Carbon signal is inactive in these scenarios.** Price and carbon intensity point the same way
  in the synthetic day and the battery fills with solar by noon, so the carbon price (0–20 ₹/kg)
  does not change dispatch. Emissions reductions here come from using more solar and from
  timing, not from carbon-price trade-offs.
- **Resilience gains depend on timing.** The outage sweep shows large gains for some outage start
  times and none for others; an outage at 00:00 cannot be helped by any controller.
- **Simplified physics.** Single-bus energy model: no voltage, frequency, reactive power, line
  losses, inverter clipping curves, ramp rates or battery ageing.
- **Ledger trust model.** The SHA-256 chain proves records have not changed since they were
  written; it does not prove the inputs were true. Whoever controls the file can rewrite the
  whole chain or truncate it; that is detected only against a head hash published somewhere the
  writer cannot alter. The current anchor is a local file (a stand-in with no real protection).
  It is not a blockchain: no decentralised consensus or replication.
- **Hosted demo storage.** On Streamlit Community Cloud the ledger file is temporary and resets
  when the app restarts.
