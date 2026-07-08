"""
availability.py — Ricostruzione della curva di capacità disponibile.

Il file "Availability_vs_production" contiene SOLO la produzione.
La curva di *availability* (capacità dichiarata disponibile) va ricostruita
dagli eventi di indisponibilità: durante ogni evento la capacità è limitata
al campo `value` (MW disponibili). Con più eventi sovrapposti si prende il
minimo. Fuori dagli eventi la disponibilità = capacità nominale.

Validato su Belleville 1: la produzione supera la availability ricostruita
solo nell'1.9% delle ore, e il CF-su-disponibile risulta ~89% (load factor
realistico).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def estimate_nominal(prod_df: pd.DataFrame, q: float = 0.995) -> float:
    """Capacità nominale stimata come q-esimo percentile della produzione."""
    return float(prod_df["production_MW_pos"].quantile(q))


def reconstruct_availability(
    prod_df: pd.DataFrame,
    unavail_df: pd.DataFrame | None,
    nominal_MW: float,
) -> pd.Series:
    """
    Serie oraria (stesso indice di prod_df) con la capacità disponibile in MW.

    Regola: availability(t) = min(value di tutti gli eventi attivi in t),
    con default = nominal_MW dove non ci sono eventi.
    """
    hours = prod_df.index
    avail = pd.Series(nominal_MW, index=hours, dtype=float, name="availability_MW")

    if unavail_df is None or unavail_df.empty:
        return avail

    for _, ev in unavail_df.iterrows():
        mask = (hours >= ev["start"]) & (hours < ev["end"])
        if mask.any():
            avail.loc[mask] = np.minimum(avail.loc[mask], ev["value"])

    return avail


def label_event_type(
    prod_df: pd.DataFrame,
    unavail_df: pd.DataFrame | None,
) -> pd.Series:
    """
    Serie oraria con l'etichetta dell'evento attivo:
      'nominal' | 'planned_maintenance' | 'forced_unavailability'
    In caso di sovrapposizione, il guasto (forced) ha priorità visiva.
    """
    hours = prod_df.index
    label = pd.Series("nominal", index=hours, dtype=object, name="event_type")

    if unavail_df is None or unavail_df.empty:
        return label

    # prima i planned, poi i forced (così i forced sovrascrivono)
    order = {"planned_maintenance": 0, "forced_unavailability": 1}
    ordered = unavail_df.assign(
        _o=unavail_df["type"].map(order).fillna(0)
    ).sort_values("_o")

    for _, ev in ordered.iterrows():
        mask = (hours >= ev["start"]) & (hours < ev["end"])
        if mask.any():
            label.loc[mask] = ev["type"]

    return label


def build_hourly_frame(
    prod_df: pd.DataFrame,
    unavail_df: pd.DataFrame | None,
    nominal_MW: float,
) -> pd.DataFrame:
    """
    Costruisce il DataFrame orario completo per un reattore:
      production_MW, production_MW_pos, availability_MW, nominal_MW,
      event_type, ramp_MW_h, cf_nominal, cf_available, unused_MW
    """
    df = prod_df.copy()

    # Cap di sanità: un reattore non può superare ~115% del nominale.
    # Valori oltre (es. 7000 MW su una macchina da 1310) sono errori della
    # sorgente e vanno rimossi, altrimenti falsano ramp e CF.
    ceiling = nominal_MW * 1.15
    outliers = df["production_MW_pos"] > ceiling
    df.loc[outliers, "production_MW_pos"] = np.nan
    df["production_MW_pos"] = df["production_MW_pos"].interpolate(limit=3).clip(lower=0)
    df.loc[outliers, "production_MW"] = df.loc[outliers, "production_MW_pos"]

    df["availability_MW"] = reconstruct_availability(prod_df, unavail_df, nominal_MW)
    df["nominal_MW"] = nominal_MW
    df["event_type"] = label_event_type(prod_df, unavail_df)

    df["ramp_MW_h"] = df["production_MW"].diff()
    df["cf_nominal"] = df["production_MW_pos"] / nominal_MW * 100
    # CF su disponibile: evita divisione per ~0 durante outage completi
    denom = df["availability_MW"].where(df["availability_MW"] > 1)
    df["cf_available"] = (df["production_MW_pos"] / denom * 100).clip(upper=150)
    df["unused_MW"] = df["availability_MW"] - df["production_MW_pos"]

    return df
