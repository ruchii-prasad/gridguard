"""Operational carbon accounting (estimates from SIMULATED dispatch, not measured impact).

Emissions are attributed to every kWh imported from the grid at the intensity of the step in
which it was imported:
    C = sum_t grid_import[t] * dt * carbon[t]      (kg CO2e)
Grid energy that charges the battery is therefore counted when it is imported, and battery
discharge is not double-counted or treated as free. PV is counted as zero operational emissions.
"""
from __future__ import annotations

import numpy as np

from .data import ScenarioInputs
from .microgrid import Dispatch


def grid_emissions_kg(d: Dispatch, inp: ScenarioInputs, dt_h: float) -> float:
    return float(np.sum(d.grid_import * dt_h * inp.carbon_kg_per_kwh))


def grid_cost(d: Dispatch, inp: ScenarioInputs, dt_h: float) -> float:
    return float(np.sum(d.grid_import * dt_h * inp.price_per_kwh))


def decompose_emissions_change(g_base: float, c_base: float,
                               g_new: float, c_new: float) -> dict[str, float]:
    """Split an emissions reduction into a VOLUME effect (less grid energy) and a TIMING effect
    (grid energy bought at cleaner hours). Exact identity, with I = C / G the average intensity:

        C_base - C_new = (G_base - G_new) * I_base  +  G_new * (I_base - I_new)
                         \\_____ volume ________/      \\______ timing ______/

    Inputs: grid energy G (kWh) and emissions C (kg) for each controller, ideally
    storage-adjusted so both end the day with comparable stored energy.
    """
    i_base = c_base / g_base if g_base > 0 else 0.0
    i_new = c_new / g_new if g_new > 0 else 0.0
    volume = (g_base - g_new) * i_base
    timing = g_new * (i_base - i_new)
    return {"total_reduction_kg": c_base - c_new, "volume_effect_kg": volume,
            "timing_effect_kg": timing, "avg_intensity_base": i_base, "avg_intensity_new": i_new}
