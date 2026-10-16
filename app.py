"""GridGuard dashboard.  Run:  .venv/bin/streamlit run app.py

Every number on this page is computed live by the tested model in src/ from SYNTHETIC inputs.
Results are simulated estimates, not measured real-world impact.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.carbon import decompose_emissions_change
from src.config import BatteryParams, GridParams, OptimizerParams, SimParams, config_dict
from src.ledger import Ledger, LocalFileAnchor, canonical_json, dispatch_payload, record_hash
from src.microgrid import battery_trajectory
from src.scenarios import CONTROLLERS, SCENARIO_NAMES, make_scenario, outage_scenario, run_scenario

RESULTS = Path(__file__).parent / "results"
LEDGER_PATH = RESULTS / "ledger.jsonl"
ANCHOR_PATH = RESULTS / "ledger_anchor.json"
CHAIN_DEPLOYMENT = Path(__file__).parent / "contracts" / "deployment.json"
CHAIN_SNAPSHOT = RESULTS / "anchored_ledger.jsonl"
CHAIN_RECEIPT = RESULTS / "chain_anchor_receipt.json"

LABEL = {"baseline": "Baseline (rule, nominal flex)", "baseline_solar_flex": "Baseline + solar-following flex",
         "reoptimized": "GridGuard (re-optimized)", "oracle": "Oracle (perfect foresight)"}
# Categorical slots 1-4 of the reference palette, in fixed order; oracle also dashed.
COLOR = {"baseline": "#2a78d6", "baseline_solar_flex": "#eb6834",
         "reoptimized": "#1baf7a", "oracle": "#eda100"}
DASH = {"baseline": "solid", "baseline_solar_flex": "solid", "reoptimized": "solid", "oracle": "dash"}
SUPPLY = {"pv_used": ("Solar used", "#2a78d6"), "discharge": ("Battery discharge", "#eb6834"),
          "grid_import": ("Grid import", "#1baf7a")}
SCENARIO_LABEL = {"normal": "Normal operation", "solar_shock": "Solar shock",
                  "grid_outage": "Grid outage", "demand_spike": "Demand spike",
                  "monsoon_flat_tariff": "Monsoon day, flat tariff"}

SIM, BAT, GRID, OPT = SimParams(), BatteryParams(), GridParams(), OptimizerParams()
HOURS = np.arange(SIM.n_steps) * SIM.dt_h

st.set_page_config(page_title="GridGuard", layout="wide")


@st.cache_resource(show_spinner="Optimizing dispatch...")
def solve(name: str):
    return run_scenario(make_scenario(name, SIM), BAT, GRID, SIM, OPT)


@st.cache_resource(show_spinner="Running outage sweep (11 cases)...")
def outage_sweep():
    rows = []
    for h0 in range(0, 22, 2):
        r = run_scenario(outage_scenario(h0, 3.0, SIM), BAT, GRID, SIM, OPT)
        rows.append({"Outage start": f"{h0:02d}:00",
                     **{LABEL[c]: r.runs[c].metrics["critical_unserved_kwh"] for c in CONTROLLERS}})
    return pd.DataFrame(rows)


def base_layout(fig: go.Figure, ytitle: str, height: int = 320) -> go.Figure:
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=30, b=10), hovermode="x unified",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                      yaxis_title=ytitle, xaxis_title="Hour of day")
    fig.update_xaxes(range=[0, 24], dtick=3, showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.2)", zeroline=False)
    return fig


def shade_disturbance(fig: go.Figure, spec) -> None:
    if spec.t_disturbance is None:
        return
    a, f = spec.actual, spec.forecast
    changed = ((a.solar_avail_kw != f.solar_avail_kw) | (a.grid_available != f.grid_available)
               | (a.crit_demand_kw != f.crit_demand_kw))
    idx = np.where(changed)[0]
    fig.add_vrect(x0=HOURS[idx[0]], x1=HOURS[idx[-1]] + SIM.dt_h, fillcolor="gray", opacity=0.15,
                  line_width=0, annotation_text="disturbance", annotation_position="bottom left")


# ---------------------------------------------------------------- sidebar
st.sidebar.title("GridGuard")
st.sidebar.caption("Carbon-aware microgrid resilience optimizer")
scenario = st.sidebar.radio("Scenario", SCENARIO_NAMES, format_func=SCENARIO_LABEL.get)
focus = st.sidebar.selectbox("Controller for the dispatch chart", CONTROLLERS, index=2,
                             format_func=LABEL.get)
with st.sidebar.expander("System parameters"):
    st.json(config_dict(BAT, GRID, SIM, OPT), expanded=False)

res = solve(scenario)
spec = res.spec

st.warning("**SIMULATION.** Inputs are synthetic profiles; every figure is a simulated estimate "
           "from the model, not a measurement of real-world climate impact.", icon="⚠️")
st.title(f"{SCENARIO_LABEL[scenario]}")
st.caption(spec.description)

tab_overview, tab_dispatch, tab_checks, tab_ledger, tab_sweep, tab_carbon = st.tabs(
    ["Overview", "Dispatch", "Constraint checks", "Audit ledger", "Outage sweep", "Carbon trade-off"])

# ---------------------------------------------------------------- overview
with tab_overview:
    g, b = res.runs["reoptimized"].metrics, res.runs["baseline_solar_flex"].metrics
    st.subheader("GridGuard vs the stronger rule-based baseline")
    def kpi(col, label: str, key: str, unit: str, nd: int) -> None:
        diff = g[key] - b[key]
        shown = f"₹{g[key]:,.{nd}f}" if unit == "₹" else f"{g[key]:,.{nd}f} {unit}"
        delta = None if abs(diff) < 0.5 * 10 ** -nd else f"{diff:+,.{nd}f} {unit}"
        col.metric(label, shown, delta, delta_color="inverse",
                   help="Change vs Baseline + solar-following flex (lower is better)")

    c1, c2, c3, c4 = st.columns(4)
    kpi(c1, "Cost, storage-adjusted", "cost_storage_adjusted", "₹", 0)
    kpi(c2, "Emissions, storage-adjusted", "emissions_storage_adjusted_kg", "kg", 1)
    kpi(c3, "Critical load unserved", "critical_unserved_kwh", "kWh", 1)
    kpi(c4, "Solar curtailed", "pv_curtailed_kwh", "kWh", 0)
    dec = decompose_emissions_change(b["grid_import_storage_adjusted_kwh"], b["emissions_storage_adjusted_kg"],
                                     g["grid_import_storage_adjusted_kwh"], g["emissions_storage_adjusted_kg"])
    st.caption(f"Emissions change split: volume {-dec['volume_effect_kg']:+.1f} kg (less/more grid energy), "
               f"timing {-dec['timing_effect_kg']:+.1f} kg (cleaner/dirtier hours). Storage-adjusted figures "
               "charge each controller for battery energy it drew down by end of day.")

    left, right = st.columns(2)
    with left:
        fig = go.Figure()
        fig.add_scatter(x=HOURS, y=spec.forecast.solar_avail_kw, name="Solar forecast",
                        line=dict(color="#2a78d6", width=2, dash="dot"))
        fig.add_scatter(x=HOURS, y=spec.actual.solar_avail_kw, name="Solar actual",
                        line=dict(color="#2a78d6", width=2))
        fig.add_scatter(x=HOURS, y=spec.actual.crit_demand_kw, name="Critical demand",
                        line=dict(color="#eb6834", width=2))
        fig.add_scatter(x=HOURS, y=spec.actual.crit_demand_kw + spec.actual.flex_nominal_kw,
                        name="Critical + nominal flexible", line=dict(color="#eb6834", width=2, dash="dash"))
        shade_disturbance(fig, spec)
        st.markdown("**Inputs: solar and demand (simulated)**")
        st.plotly_chart(base_layout(fig, "kW"), width="stretch")
    with right:
        fig = go.Figure()
        for c in CONTROLLERS:
            d = res.runs[c].dispatch
            E = battery_trajectory(d.charge, d.discharge, BAT, SIM.dt_h)
            fig.add_scatter(x=np.append(HOURS, 24), y=100 * E / BAT.capacity_kwh, name=LABEL[c],
                            line=dict(color=COLOR[c], width=2, dash=DASH[c]))
        fig.add_hline(y=100 * BAT.soc_reserve, line=dict(color="gray", dash="dot", width=1),
                      annotation_text="outage reserve", annotation_position="top left")
        fig.add_hline(y=100 * BAT.soc_min, line=dict(color="gray", width=1), annotation_text="minimum", annotation_position="bottom left")
        shade_disturbance(fig, spec)
        st.markdown("**Battery state of charge**")
        st.plotly_chart(base_layout(fig, "% of capacity").update_yaxes(range=[0, 100]),
                        width="stretch")

    st.markdown("**All controllers**")
    rows = [("Cost, storage-adjusted (₹)", "cost_storage_adjusted", 0),
            ("Emissions, storage-adjusted (kg CO2e)", "emissions_storage_adjusted_kg", 1),
            ("Grid import (kWh)", "grid_import_kwh", 1), ("Solar used (kWh)", "pv_used_kwh", 1),
            ("Solar curtailed (kWh)", "pv_curtailed_kwh", 1),
            ("Critical unserved (kWh)", "critical_unserved_kwh", 1),
            ("Flexible unserved (kWh)", "flex_unserved_kwh", 1),
            ("Battery at 24:00 (kWh)", "battery_e_final_kwh", 1),
            ("Solve time (s)", None, 2)]
    table = {}
    for c in CONTROLLERS:
        r = res.runs[c]
        table[LABEL[c]] = [round(r.solve_time_s if k is None else r.metrics[k], n) for _, k, n in rows]
    st.dataframe(pd.DataFrame(table, index=[r[0] for r in rows]), width="stretch")

# ---------------------------------------------------------------- dispatch
with tab_dispatch:
    d = res.runs[focus].dispatch
    st.markdown(f"**Power sources and demand: {LABEL[focus]}**")
    fig = go.Figure()
    for key, (name, color) in SUPPLY.items():
        fig.add_bar(x=HOURS + SIM.dt_h / 2, y=getattr(d, key), name=name, marker_color=color,
                    width=SIM.dt_h * 0.9)
    fig.add_bar(x=HOURS + SIM.dt_h / 2, y=-d.charge, name="Battery charging (negative)",
                marker_color="#e87ba4", width=SIM.dt_h * 0.9)
    fig.add_scatter(x=HOURS + SIM.dt_h / 2, y=d.crit_served + d.flex_served, name="Load served",
                    line=dict(color="#6250d6", width=2), mode="lines")
    fig.add_scatter(x=HOURS + SIM.dt_h / 2, y=spec.actual.crit_demand_kw, name="Critical demand",
                    line=dict(color="#8a8984", width=2, dash="dot"), mode="lines")
    fig.update_layout(barmode="relative")
    shade_disturbance(fig, spec)
    st.plotly_chart(base_layout(fig, "kW", 400), width="stretch")
    st.caption("Bars above zero supply load; pink bars below zero charge the battery. "
               "In each 15-minute step, supply = load served + charging. Where the purple line sits "
               "below the dotted critical-demand line, critical load is going unserved.")

    st.markdown("**Grid import by controller**")
    fig = go.Figure()
    for c in CONTROLLERS:
        fig.add_scatter(x=HOURS, y=res.runs[c].dispatch.grid_import, name=LABEL[c],
                        line=dict(color=COLOR[c], width=2, dash=DASH[c], shape="hv"))
    shade_disturbance(fig, spec)
    st.plotly_chart(base_layout(fig, "kW"), width="stretch")

    with st.expander("Dispatch table (15-minute steps)"):
        st.dataframe(pd.DataFrame({"hour": HOURS, **d.to_dict()}).round(2), width="stretch")

# ---------------------------------------------------------------- checks
with tab_checks:
    st.markdown("Every controller's dispatch is checked by the same independent validator. "
                "**Physical** checks must never fail; the **target** (end-of-day battery energy) "
                "is an operating goal that rule-based baselines do not pursue.")
    cols = st.columns(len(CONTROLLERS))
    for col, c in zip(cols, CONTROLLERS):
        v = res.runs[c].validation
        with col:
            st.markdown(f"**{LABEL[c]}**")
            if v.all_passed:
                st.success("All checks passed", icon="✅")
            elif v.physical_ok:
                st.warning("Physics OK, target missed", icon="⚠️")
            else:
                st.error("Physical violation", icon="❌")
    c = st.selectbox("Show checks for", CONTROLLERS, index=2, format_func=LABEL.get, key="chk")
    st.dataframe(pd.DataFrame([{"check": k.name, "kind": k.kind, "passed": "✅" if k.passed else "❌",
                                "worst violation": k.worst_violation, "detail": k.detail}
                               for k in res.runs[c].validation.checks]),
                 width="stretch", hide_index=True)

# ---------------------------------------------------------------- ledger
with tab_ledger:
    ledger = Ledger(LEDGER_PATH)
    anchor = LocalFileAnchor(ANCHOR_PATH)
    st.markdown("Each run is appended as SHA-256 hash-chained records. Changing, deleting or reordering "
                "any record breaks the chain. **Limitation:** the chain proves records were not altered "
                "after writing, not that the inputs were true; detecting a rewritten or truncated chain "
                "needs the head hash published externally (local file anchor shown here as a stand-in).")
    a, b2, c3 = st.columns(3)
    if a.button(f"Append this scenario ({len(CONTROLLERS)} records)", width="stretch"):
        cfg = config_dict(BAT, GRID, SIM, OPT)
        for ctl, r in res.runs.items():
            ledger.append(dispatch_payload(ctl, spec.actual.to_dict(), cfg, r.dispatch.to_dict(),
                                           r.metrics, r.validation.to_dict()), scenario_id=scenario)
        v = ledger.verify()
        anchor.publish(v.head_hash, v.n_records)
        st.success(f"Appended. Ledger now has {v.n_records} records; head anchored.")
    if b2.button("Verify full chain", width="stretch"):
        trusted = anchor.latest()
        v = ledger.verify(trusted["head_hash"] if trusted else None)
        if v.ok:
            st.success(f"VALID: {v.n_records} records, head {v.head_hash[:16]}…"
                       + (" (matches anchored head)" if trusted else " (no anchor yet)"), icon="✅")
        else:
            where = f" at record {v.first_bad_index}" if v.first_bad_index is not None else ""
            st.error(f"TAMPER DETECTED{where}: {v.reason}", icon="❌")
    if c3.button("Tamper test on a copy", width="stretch"):
        recs = ledger.records()
        if not recs:
            st.info("Ledger is empty: append a scenario first.")
        else:
            copy = RESULTS / "tamper_ui_copy.jsonl"
            shutil.copy(LEDGER_PATH, copy)
            recs[0]["metrics"]["emissions_storage_adjusted_kg"] *= 0.8
            copy.write_text("".join(canonical_json(r) + "\n" for r in recs))
            v = Ledger(copy).verify()
            copy.unlink()
            st.error(f"Edited record 0's emissions by −20% on a copy → verification: "
                     f"{'VALID (unexpected!)' if v.ok else 'FAILED at record ' + str(v.first_bad_index) + ', ' + v.reason}")

    recs = ledger.records()
    if recs:
        st.markdown(f"**Records ({len(recs)})**")
        st.dataframe(pd.DataFrame([{"index": r["index"], "time (UTC)": r["timestamp_utc"],
                                    "scenario": r["scenario_id"], "controller": r.get("controller"),
                                    "record hash": r["record_hash"][:16] + "…",
                                    "prev hash": r["prev_hash"][:16] + "…"} for r in recs]),
                     width="stretch", hide_index=True)
        i = st.number_input("Inspect record", 0, len(recs) - 1, len(recs) - 1)
        r = recs[int(i)]
        ok = record_hash(r) == r["record_hash"]
        st.markdown(f"Stored hash `{r['record_hash']}` — recomputed hash "
                    f"{'matches ✅' if ok else 'DOES NOT match ❌'}")
        st.json({k: v for k, v in r.items() if k != "dispatch"}, expanded=False)
        with st.expander("Dispatch decisions in this record"):
            st.dataframe(pd.DataFrame(r["dispatch"]).round(2), width="stretch")
        st.download_button("Export ledger as JSON",
                           json.dumps({"head_hash": ledger.head_hash(), "records": recs}, indent=2),
                           file_name="gridguard_ledger.json", mime="application/json")
    else:
        st.info("Ledger is empty. Click **Append this scenario** or run `run_demo.py`.")

    # ---------------- public blockchain anchor (Ethereum Sepolia testnet)
    st.divider()
    st.subheader("Public blockchain anchor (Ethereum Sepolia testnet)")
    st.markdown("The head hash of an audit-ledger snapshot is published to the `GridGuardAnchor` smart "
                "contract. Anyone can re-check the snapshot against the chain **without a wallet**. "
                "This catches what a local check cannot: a ledger rewritten with every hash "
                "recomputed, or truncated. Records themselves stay off-chain; only 32-byte hashes "
                "are public.")
    if CHAIN_DEPLOYMENT.exists() and CHAIN_RECEIPT.exists() and CHAIN_SNAPSHOT.exists():
        dep = json.loads(CHAIN_DEPLOYMENT.read_text())
        rec = json.loads(CHAIN_RECEIPT.read_text())
        snap = Ledger(CHAIN_SNAPSHOT)
        st.markdown(f"Contract [`{dep['address']}`](https://sepolia.etherscan.io/address/{dep['address']}) · "
                    f"anchor transaction [`{rec['tx'][:18]}…`]({rec['explorer_tx']}) · "
                    f"{rec['n_records']} records · publisher `{rec['publisher']}`")
        b1, b2 = st.columns(2)
        if b1.button("Verify snapshot against Sepolia", width="stretch"):
            try:
                from src.chain import ChainAnchor, connect, verify_against_chain
                with st.spinner("Reading the contract from a public Sepolia node..."):
                    res, onchain = verify_against_chain(
                        snap, ChainAnchor(connect(), dep["address"], rec["publisher"], snap.ledger_id()))
                if res.ok:
                    st.success(f"VALID: all {res.n_records} records hash-chain correctly and record "
                               f"{onchain['n_records'] - 1} matches the on-chain head "
                               f"{onchain['head_hash'][:16]}… (block {onchain['block']}).", icon="✅")
                else:
                    st.error(f"FAILED: {res.reason}", icon="❌")
            except Exception as e:  # network or RPC problems must not crash the demo
                st.warning(f"Could not reach a Sepolia node right now ({type(e).__name__}). "
                           f"The anchor can still be checked on Etherscan: {rec['explorer_tx']}")
        if b2.button("Attack test: rewrite and re-hash a copy", width="stretch"):
            try:
                from src.chain import ChainAnchor, connect, verify_against_chain
                recs2 = snap.records()
                k = len(recs2) // 2
                recs2[k]["metrics"]["emissions_storage_adjusted_kg"] *= 0.8
                for j in range(k, len(recs2)):
                    if j > k:
                        recs2[j]["prev_hash"] = recs2[j - 1]["record_hash"]
                    recs2[j]["record_hash"] = record_hash(recs2[j])
                copy = RESULTS / "attack_copy.jsonl"
                copy.write_text("".join(canonical_json(x) + "\n" for x in recs2))
                attacked = Ledger(copy)
                local = attacked.verify()
                with st.spinner("Checking the forged copy against Sepolia..."):
                    res, _ = verify_against_chain(
                        attacked, ChainAnchor(connect(), dep["address"], rec["publisher"], snap.ledger_id()))
                copy.unlink()
                st.info(f"Forged copy: record {k}'s emissions cut by 20% and every later hash recomputed.\n\n"
                        f"- Local hash-chain check: **{'VALID (fooled)' if local.ok else 'FAILED'}**\n"
                        f"- Check against Sepolia anchor: **{'VALID' if res.ok else 'FAILED: ' + res.reason}**")
            except Exception as e:
                st.warning(f"Could not reach a Sepolia node right now ({type(e).__name__}).")
    else:
        st.info("No on-chain anchor published yet. Run `run_chain_anchor.py deploy` and "
                "`run_chain_anchor.py anchor` (see README).")

# ---------------------------------------------------------------- sweep
with tab_sweep:
    st.markdown("**Critical energy unserved for an unannounced 3 h outage starting at each even hour "
                "(normal day, simulated).** The oracle column is what advance notice of the outage "
                "(e.g. scheduled load-shedding) would allow.")
    if st.button("Run sweep (about 1 minute)"):
        st.session_state["sweep"] = outage_sweep()
    if "sweep" in st.session_state:
        df = st.session_state["sweep"]
        fig = go.Figure()
        for c in CONTROLLERS:
            fig.add_bar(x=df["Outage start"], y=df[LABEL[c]], name=LABEL[c], marker_color=COLOR[c])
        fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.08)
        st.plotly_chart(base_layout(fig, "kWh unserved", 380).update_xaxes(range=None, dtick=None,
                        title="Outage start"), width="stretch")
        st.dataframe(df, width="stretch", hide_index=True)

# ---------------------------------------------------------------- carbon
with tab_carbon:
    st.markdown("**How much CO₂ does each extra rupee buy?** The optimizer's objective adds an assumed "
                "shadow carbon price (₹/kg CO₂e) to the electricity cost. Each point is the optimal "
                "dispatch at one carbon price (simulated, storage-adjusted).")
    sweep_path = RESULTS / "carbon_sweep.json"
    if sweep_path.exists():
        data = json.loads(sweep_path.read_text())
        names = {"normal": "Sunny day, time-of-day tariff", "monsoon_flat_tariff": "Monsoon day, flat tariff"}
        for day, color in (("normal", "#2a78d6"), ("monsoon_flat_tariff", "#eb6834")):
            if day not in data.get("days", {}):
                continue
            d = data["days"][day]
            # Merge carbon prices that give the same dispatch into one labelled point.
            pts: list[list] = []
            for r in d["optimizer"]:
                key = (round(r["cost_storage_adjusted"], 1), round(r["emissions_storage_adjusted_kg"], 1))
                if pts and pts[-1][0] == key:
                    pts[-1][1].append(r["carbon_price_per_kg"])
                else:
                    pts.append([key, [r["carbon_price_per_kg"]]])
            label = lambda ps: (f"₹{ps[0]:g}/kg" if len(ps) == 1
                                else f"₹{ps[0]:g}–{ps[-1]:g}/kg (same plan)")
            fig = go.Figure()
            fig.add_scatter(x=[k[0] for k, _ in pts], y=[k[1] for k, _ in pts],
                            mode="lines+markers+text", name="GridGuard at carbon price",
                            text=[label(ps) for _, ps in pts],
                            textposition="top right", line=dict(color=color, width=2),
                            marker=dict(size=9))
            b = d["baseline_solar_flex"]
            fig.add_scatter(x=[b["cost_storage_adjusted"]], y=[b["emissions_storage_adjusted_kg"]],
                            mode="markers+text", name="Baseline + solar-following flex",
                            text=["baseline"], textposition="bottom left",
                            marker=dict(size=11, symbol="diamond", color="#8a8984"))
            fig.update_layout(height=340, margin=dict(l=10, r=10, t=30, b=10),
                              legend=dict(orientation="h", y=1.08, x=0),
                              xaxis_title="Cost, storage-adjusted (₹)",
                              yaxis_title="Emissions, storage-adjusted (kg CO₂e)")
            fig.update_yaxes(gridcolor="rgba(128,128,128,0.2)")
            st.markdown(f"**{names[day]}**")
            st.plotly_chart(fig, width="stretch")
        st.caption("Sunny day: tariff and carbon already point the same way and the battery fills with "
                   "solar, so the carbon price changes nothing. Monsoon day, flat tariff: little sun "
                   "leaves room to shift grid energy, and only the carbon price rewards cleaner hours. "
                   "Carbon intensity shapes are illustrative, not measured grid data.")
    else:
        st.info("Run `run_carbon_sweep.py` to generate results/carbon_sweep.json.")
