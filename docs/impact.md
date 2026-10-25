# GridGuard — Climate impact, adoption and scalability

**Everything below comes from simulation with synthetic inputs. These are indicative projections,
not measured impact.**

## 1. Climate impact

GridGuard cuts emissions in two ways, and reports them separately:

- **Volume:** using more of the site's own solar instead of curtailing it. On the normal day,
  compared with a basic self-consumption controller, curtailed solar falls from 202 to 82 kWh
  and storage-adjusted CO₂e falls 21.4 % (500 → 393 kg). Most of that gain comes from moving
  flexible load into midday solar. A well-designed rule can capture much of it too, so we report
  the stronger baseline as the main comparison.
- **Timing:** buying grid energy when the grid is cleaner. On a low-sun day with a flat tariff,
  where a cost-only controller has no reason to care, the carbon price cuts CO₂e by 4.1 %
  (850 → 815 kg) at no extra cost: 31 kg from timing and 3 kg from volume. A higher carbon price
  buys more: −7.1 % at ₹20/kg for +0.9 % cost.

**Resilience is a climate-adaptation benefit too.** Keeping critical loads running through outages
(clinics, water pumps, cold chains) matters more as heat waves and storms stress grids. In the
evening outage, GridGuard cuts critical energy lost by 57 % (34.6 → 15.0 kWh). Across outage
start times it reduces losses by up to 89 % (112 → 12 kWh). With advance notice of scheduled
load-shedding, it eliminates them for early-morning outages.

**Honest trade-off:** in the outage scenario, emissions rise 4.7 %, because GridGuard keeps the
battery fuller beforehand. We show this rather than hide it.

### Illustrative scale-up (assumption-based)

If one 200 kWh-battery site saves about 34 kg CO₂e on a low-sun flat-tariff day, and such days
were, say, 100 per year, that is about 3.4 t CO₂e per site per year from timing alone. Across 100
sites it would be about 340 t. **These figures depend entirely on the assumed carbon-intensity
shape and day count.** They show how the result scales, not a forecast. Real grid-intensity data
(for example from a national grid operator or an emissions-data API) would replace the synthetic
profile.

## 2. Target users

- Campus, hospital and industrial microgrids with solar plus storage
- Rural and island mini-grids with weak or scheduled-outage grid connections
- Mini-grid developers and funders who need verifiable performance reports
- Carbon-credit and renewable-certificate verifiers who need tamper-evident operating records

## 3. Ease of adoption

- **Pure software, no new hardware.** It runs on a laptop; SciPy and HiGHS ship with Python.
- **Every parameter in one file** (`src/config.py`): battery, grid limit, tariffs, penalties.
- **Data in, schedule out.** Replace the synthetic profiles with site forecasts, tariff tables and a
  grid-intensity feed; the optimizer, validator and ledger are unchanged.
- **The audit trail is optional and free.** Verifying an anchor needs no wallet.

## 4. Scalability and sustainability roadmap

| Stage | Next step |
|---|---|
| Data | Real solar forecasts, smart-meter loads, live grid carbon intensity |
| Control | Rolling re-optimization every 15 min (model-predictive control); forecast uncertainty |
| Fleet | One optimizer per site, all sites' ledger heads batched into one Merkle root, one anchor transaction per day |
| Chain | Move from testnet to a low-fee L2; multi-party (operator, auditor) co-signed anchors |
| Integrity at source | Signed meter data, so records are verifiable from measurement to report |
| Physics | Inverter limits, ramp rates, battery ageing, multi-bus networks |

The MILP is small (about 800 variables for a day at 15-minute steps) and solves in seconds, so one
server can schedule many sites.
