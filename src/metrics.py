"""
metrics.py — Calcolo metriche e aggregazioni di flotta.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .availability import build_hourly_frame, estimate_nominal


def compute_kpis(hourly: pd.DataFrame) -> dict:
    """KPI sintetici su un frame orario (già filtrato per periodo)."""
    if hourly.empty:
        return {}

    prod = hourly["production_MW_pos"]
    ramp = hourly["ramp_MW_h"].dropna()
    ramp = ramp[ramp.abs() > 1]  # filtra rumore < 1 MW/h

    nominal = float(hourly["nominal_MW"].iloc[0])

    # Energia (MWh) — passo orario => MW ≈ MWh
    energy_produced = prod.sum()
    energy_available = hourly["availability_MW"].sum()
    energy_nominal = nominal * len(hourly)

    outage_hours = int((prod < 10).sum())

    return {
        "nominal_MW": nominal,
        "hours": len(hourly),
        "cf_nominal": prod.mean() / nominal * 100,
        "cf_available": (energy_produced / energy_available * 100)
        if energy_available > 0 else np.nan,
        "energy_produced_GWh": energy_produced / 1000,
        "energy_available_GWh": energy_available / 1000,
        "energy_nominal_GWh": energy_nominal / 1000,
        "availability_factor": energy_available / energy_nominal * 100
        if energy_nominal > 0 else np.nan,
        "outage_hours": outage_hours,
        "outage_pct": outage_hours / len(hourly) * 100,
        "max_ramp_up": ramp[ramp > 0].max() if (ramp > 0).any() else 0.0,
        "max_ramp_down": ramp[ramp < 0].min() if (ramp < 0).any() else 0.0,
        "mean_prod_MW": prod.mean(),
    }


def slice_period(hourly: pd.DataFrame, date_from, date_to) -> pd.DataFrame:
    """Filtra un frame orario su [date_from, date_to] inclusi."""
    start = pd.Timestamp(date_from)
    end = pd.Timestamp(date_to) + pd.Timedelta(days=1)  # inclusivo sul giorno
    return hourly.loc[(hourly.index >= start) & (hourly.index < end)]


def build_all_hourly(
    prod_data: dict,
    unavail_data: dict,
) -> tuple[dict, dict]:
    """
    Costruisce il frame orario per ogni reattore + dict dei nominali.
    Ritorna (hourly_by_reactor, nominal_by_reactor).
    """
    hourly_by_reactor: dict[str, pd.DataFrame] = {}
    nominal_by_reactor: dict[str, float] = {}

    for reactor, pdf in prod_data.items():
        nominal = estimate_nominal(pdf)
        nominal_by_reactor[reactor] = nominal
        hourly_by_reactor[reactor] = build_hourly_frame(
            pdf, unavail_data.get(reactor), nominal
        )

    return hourly_by_reactor, nominal_by_reactor


def aggregate_fleet(
    hourly_by_reactor: dict,
    reactors: list[str],
    date_from,
    date_to,
) -> pd.DataFrame:
    """
    Somma oraria della flotta selezionata: produzione, availability, nominale.
    Allinea gli indici orari (union) e somma.
    """
    prod_frames, avail_frames, nom_frames = [], [], []

    for r in reactors:
        if r not in hourly_by_reactor:
            continue
        h = slice_period(hourly_by_reactor[r], date_from, date_to)
        if h.empty:
            continue
        prod_frames.append(h["production_MW_pos"].rename(r))
        avail_frames.append(h["availability_MW"].rename(r))
        nom_frames.append(h["nominal_MW"].rename(r))

    if not prod_frames:
        return pd.DataFrame()

    prod_sum = pd.concat(prod_frames, axis=1).sum(axis=1)
    avail_sum = pd.concat(avail_frames, axis=1).sum(axis=1)
    nom_sum = pd.concat(nom_frames, axis=1).sum(axis=1)

    fleet = pd.DataFrame({
        "production_MW_pos": prod_sum,
        "availability_MW": avail_sum,
        "nominal_MW": nom_sum,
    }).sort_index()

    fleet["ramp_MW_h"] = fleet["production_MW_pos"].diff()
    fleet["cf_nominal"] = fleet["production_MW_pos"] / fleet["nominal_MW"] * 100
    denom = fleet["availability_MW"].where(fleet["availability_MW"] > 1)
    fleet["cf_available"] = (fleet["production_MW_pos"] / denom * 100).clip(upper=150)
    fleet["unused_MW"] = fleet["availability_MW"] - fleet["production_MW_pos"]
    # production_MW = production_MW_pos a livello flotta (non ha senso il negativo aggregato)
    fleet["production_MW"] = fleet["production_MW_pos"]
    fleet["nominal_MW"] = fleet["nominal_MW"]  # somma dei nominali
    return fleet


def fleet_kpis(fleet: pd.DataFrame) -> dict:
    """KPI su frame flotta aggregato."""
    if fleet.empty:
        return {}
    prod = fleet["production_MW_pos"]
    ramp = fleet["ramp_MW_h"].dropna()
    energy_produced = prod.sum()
    energy_available = fleet["availability_MW"].sum()
    energy_nominal = fleet["nominal_MW"].sum()
    return {
        "hours": len(fleet),
        "installed_MW": fleet["nominal_MW"].iloc[0],
        "cf_nominal": energy_produced / energy_nominal * 100 if energy_nominal else np.nan,
        "cf_available": energy_produced / energy_available * 100 if energy_available else np.nan,
        "availability_factor": energy_available / energy_nominal * 100 if energy_nominal else np.nan,
        "energy_produced_TWh": energy_produced / 1e6,
        "peak_prod_MW": prod.max(),
        "min_prod_MW": prod.min(),
        "max_ramp_up": ramp[ramp > 0].max() if (ramp > 0).any() else 0.0,
        "max_ramp_down": ramp[ramp < 0].min() if (ramp < 0).any() else 0.0,
    }


def reactor_modulation_metrics(
    hourly_by_reactor: dict,
    reactors: list[str],
    date_from,
    date_to,
) -> pd.DataFrame:
    """
    Per ogni reattore, metriche di modulazione nel periodo:
      cf_nominal        — capacity factor su nominale (%)
      ramp_rate_pct     — 95° perc. di |ramp| in % del nominale/h (velocità modulazione)
      daily_swing_pct   — escursione intra-giornaliera media (max−min)/nom ×100
      n_big_ramps       — ore con |ramp| > 5% del nominale (frequenza modulazione)
    """
    rows = []
    for r in reactors:
        if r not in hourly_by_reactor:
            continue
        h = slice_period(hourly_by_reactor[r], date_from, date_to)
        if h.empty:
            continue
        nominal = float(h["nominal_MW"].iloc[0])
        prod = h["production_MW_pos"]
        ramp = h["ramp_MW_h"].dropna().abs()
        big = ramp[ramp > 0.05 * nominal]
        # escursione intra-giornaliera: solo giorni "in marcia" (media > 20% nom)
        daily = prod.resample("D")
        day_mean = daily.mean()
        day_range = (daily.max() - daily.min())
        active_days = day_mean > 0.20 * nominal
        swing = (day_range[active_days].mean() / nominal * 100) if active_days.any() else 0
        rows.append({
            "reactor": r,
            "cf_nominal": prod.mean() / nominal * 100,
            "ramp_rate_pct": (ramp.quantile(0.95) / nominal * 100) if len(ramp) else 0,
            "daily_swing_pct": swing,
            "n_big_ramps": int(len(big)),
        })
    return pd.DataFrame(rows)


def matched_events_in_period(
    unavail_df: pd.DataFrame | None,
    date_from,
    date_to,
) -> pd.DataFrame:
    """Eventi di indisponibilità che intersecano il periodo selezionato."""
    if unavail_df is None or unavail_df.empty:
        return pd.DataFrame()
    start = pd.Timestamp(date_from)
    end = pd.Timestamp(date_to) + pd.Timedelta(days=1)
    mask = (unavail_df["start"] < end) & (unavail_df["end"] > start)
    return unavail_df[mask].sort_values("start")
