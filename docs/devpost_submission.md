# Devpost submission text: copy each section into the matching field

## Project name
GridGuard

## Tagline (short description)
Resilience-first microgrid dispatch optimizer with tamper-evident, blockchain-anchored decisions.

## Track
Renewable Energy & Grid Management

## Links
- Live demo: https://gridguard-microgrid.streamlit.app (free hosting: if it shows "app has gone to sleep", click "Yes, get this app back up!" and wait ~1 minute)
- Code: https://github.com/ruchii-prasad/gridguard
- Video: *(paste your YouTube or Vimeo link)*

## Built with
python, scipy, highs, mixed-integer-linear-programming, numpy, streamlit, plotly, solidity, ethereum, sepolia, web3.py, sha-256, pytest

---

## Inspiration
Solar-and-battery microgrids run campuses, clinics and villages, often on weak grids with
frequent or scheduled outages. Most of their battery controllers follow fixed rules. They waste
midday solar, empty the battery just before an outage, and leave no trustworthy record of what
they did. Funders and carbon-credit verifiers have to take reported performance on trust.

## What it does
GridGuard schedules solar, a battery, grid imports, critical loads and flexible loads every 15
minutes, using a mixed-integer linear program. It minimizes cost plus priced emissions under a
strict priority order: critical load, then flexible load, then end-of-day battery level, then cost.
It plans day-ahead and re-optimizes when a solar drop, grid outage or demand spike happens. When
physics makes a shortfall unavoidable, it reports the exact amount rather than hiding it. Every
decision is written to a SHA-256 hash-chained audit ledger, whose head hash can be anchored in a
Solidity smart contract on Ethereum Sepolia, so anyone can detect rewritten or truncated records
without a wallet.

**Simulated results (synthetic inputs), compared with a strong rule-based controller:**
- Evening grid outage: critical energy lost falls from 34.6 to 15.0 kWh (−57 %). The remaining
  15 kWh is physically unavoidable (55 kW load, 50 kW battery limit).
- Outage sweep: up to −89 % critical energy lost (112 → 12 kWh); 0 kWh for early-morning outages
  when they are announced in advance.
- Solar shock: −8.7 % cost, −3.7 % CO₂e. Normal day: −5.2 % cost.
- Monsoon day on a flat tariff: −4.1 % CO₂e at no extra cost, by shifting grid use to cleaner hours.
- Against a basic self-consumption controller: −30.8 % cost and −21.4 % CO₂e on a normal day.

## How we built it
- **Physics model:** discrete-time power balance and battery dynamics with efficiencies, power and
  energy limits, and an outage reserve.
- **Optimizer:** SciPy `milp` with HiGHS. Binary variables make charge/discharge exclusivity exact
  and enforce the outage reserve. Ranked penalties keep the problem feasible while guaranteeing
  priorities. A lexicographic second stage makes the optimal plan unique across machines, and a
  polish LP removes solver-tolerance noise.
- **Fair evaluation:** two rule-based baselines (one deliberately strong), a perfect-foresight
  oracle, storage-adjusted metrics, and an independent validator with 14 checks applied to every
  controller.
- **Carbon accounting:** emissions counted at import time, including grid energy that charges the
  battery, split exactly into a volume effect and a timing effect.
- **Integrity:** canonical-JSON SHA-256 hash chain, plus a `GridGuardAnchor` contract (Solidity
  0.8.28) that stores per-publisher, append-only head hashes whose record count can never shrink.
- **Dashboard:** Streamlit and Plotly, deployed on Streamlit Community Cloud.

## Challenges we ran into
- **Machine-dependent answers.** Many schedules tie at exactly the same cost, and the solver
  returned different ones on macOS and Linux. We added a lexicographic tie-break (prefer stored
  energy, then finish flexible load earlier), and now a results fingerprint matches on both.
- **Solver tolerance.** Randomized tests found binaries returned as 0.99999996, which leaked
  micro-kW into the dispatch. Fixing the rounded binaries and re-solving an LP cut violations to
  10⁻¹³.
- **Honesty about carbon.** Our first carbon-price sweep was flat. Instead of tuning numbers, we
  found the realistic case where carbon pricing matters (low sun, flat tariff) and report both.

## Accomplishments that we're proud of
- 81 automated tests, 25 randomized microgrids in the suite and a 300-case stress test with zero
  physics violations.
- Results that reproduce exactly across machines.
- An audit trail that catches the attack a local hash chain cannot: a full rewrite with every hash
  recomputed.
- Reporting trade-offs openly. Resilience costs 4.7 % more emissions in the outage case, and we
  show it.

## What we learned
Comparing against a strawman makes any optimizer look good. A strong baseline shows where
optimization really helps: look-ahead resilience and disturbance response, more than everyday
savings. Tamper evidence also needs an external anchor; a hash chain alone proves less than it
seems.

## What's next for GridGuard
Real solar forecasts, meter data and live grid-intensity feeds. Rolling 15-minute re-optimization
under forecast uncertainty. Merkle-batched anchors for fleets of sites on a low-fee L2. Signed
meter data, so records are verifiable from measurement to report.

## Disclosure
All inputs are synthetic and all results are simulated estimates, not measured real-world impact.
Built with AI assistance (Claude) for code and documentation; the design decisions, testing and
validation are documented in the repository.
