"""
loadfollowing.py — Analisi del load-following: quanto e quanto spesso i
reattori modulano *mentre sono in marcia*, distinguendo la modulazione
operativa dai transitori di avvio/arresto per ricarica.

Riferimenti di letteratura usati come benchmark (citati nell'app):
  - EDF (Morilhat et al. 2019): range 20–100% Pnom in 30 min, 2 cicli/giorno.
  - Jenkins/Argonne-MIT (2018): rampa max ~20% Pnom/h, min stabile 50% (15%
    in FullFlex), 3 h stabili prima di ri-rampare.
  - OECD/NEA (2011): baseload = solo regolazione di frequenza; il LF stressa
    combustibile e componenti (xeno-135, burn-up, fatica del cladding).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Soglie (frazioni del nominale) per classificare lo stato operativo orario
FULL_THR = 0.92     # ≥92% del nominale = a piena potenza
ONLINE_THR = 0.20   # ≥20% = in marcia (soglia inferiore del LF secondo EDF)
OFF_THR = 0.03      # <3% = fermo/outage

# Valori di riferimento della letteratura (per il pannello di confronto)
LIT_REFERENCE = {
    "power_range_low_pct": 20,     # EDF: modulazione fino al 20% Pnom
    "power_range_high_pct": 100,
    "max_ramp_pct_h": 20,          # Argonne/MIT: ~20% Pnom/h
    "cycles_per_day": 2,           # EDF: due volte al giorno
    "min_stable_pct": 50,          # min stabile tipico
}


def classify_states(hourly: pd.DataFrame) -> pd.Series:
    """Stato operativo orario: 'full' | 'load_follow' | 'low' | 'off'."""
    nominal = float(hourly["nominal_MW"].iloc[0])
    p = hourly["production_MW_pos"]
    conditions = [
        p < OFF_THR * nominal,
        p < ONLINE_THR * nominal,
        p < FULL_THR * nominal,
    ]
    choices = ["off", "low", "load_follow"]
    return pd.Series(np.select(conditions, choices, default="full"),
                     index=hourly.index, name="state")


def ramp_events(hourly: pd.DataFrame, min_pct: float = 2.0) -> pd.DataFrame:
    """
    Raggruppa ore consecutive con rampa dello stesso segno in *eventi* discreti.
    Filtra il rumore sotto min_pct (% del nominale/h sul singolo passo).

    Ogni evento: start, end, duration_h, delta_MW, delta_pct (del nominale),
    rate_pct_h (velocità media in %Pnom/h), direction ('up'/'down'),
    online (True se sia inizio che fine ≥20% Pnom → load-following operativo;
    False se è un transitorio di avvio/arresto legato a un outage).
    """
    nominal = float(hourly["nominal_MW"].iloc[0])
    ramp = hourly["ramp_MW_h"].fillna(0.0)
    thr = (min_pct / 100.0) * nominal
    prod = hourly["production_MW_pos"]

    sign = np.sign(ramp.where(ramp.abs() >= thr, 0.0))
    # id di gruppo: cambia quando cambia il segno
    grp = (sign != sign.shift()).cumsum()

    events = []
    for _, idx in hourly.groupby(grp.values).groups.items():
        s = sign.loc[idx].iloc[0]
        if s == 0:
            continue  # tratto piatto/sotto soglia
        block = hourly.loc[idx]
        start, end = block.index[0], block.index[-1]
        # produzione prima dell'evento e alla fine
        p_before = prod.loc[:start].iloc[-2] if len(prod.loc[:start]) >= 2 else prod.loc[start]
        p_after = prod.loc[end]
        delta = ramp.loc[idx].sum()
        dur = len(idx)  # passo orario
        online = (p_before >= ONLINE_THR * nominal) and (p_after >= ONLINE_THR * nominal)
        events.append({
            "start": start, "end": end, "duration_h": dur,
            "delta_MW": delta, "delta_pct": delta / nominal * 100,
            "rate_pct_h": (delta / dur) / nominal * 100,
            "direction": "up" if s > 0 else "down",
            "online": online,
        })
    return pd.DataFrame(events)


def daily_load_following(hourly: pd.DataFrame) -> pd.DataFrame:
    """
    Per ogni giorno: se il reattore è in marcia (online) e modula, quante volte
    inverte la direzione (cicli di load-following).
      online_day    — il reattore è rimasto sopra il 20% Pnom tutto il giorno
      swing_pct     — (max−min)/nominale ×100 nel giorno
      n_cycles      — numero di inversioni giù→su (cicli di LF) nel giorno
      is_lf_day     — giorno di load-following (online + swing ≥ 8% Pnom)
    """
    nominal = float(hourly["nominal_MW"].iloc[0])
    out = []
    for day, block in hourly.groupby(hourly.index.normalize()):
        p = block["production_MW_pos"]
        if len(p) < 12:
            continue
        pmin, pmax = p.min(), p.max()
        online_day = pmin >= ONLINE_THR * nominal
        swing = (pmax - pmin) / nominal * 100
        # cicli: conta i minimi locali "significativi" quando online
        r = block["ramp_MW_h"].fillna(0.0)
        sig = np.sign(r.where(r.abs() >= 0.03 * nominal, 0.0))
        sig = sig[sig != 0]
        reversals = int((sig.diff().abs() == 2).sum()) if len(sig) > 1 else 0
        n_cycles = reversals // 2
        out.append({
            "date": day, "online_day": online_day, "swing_pct": swing,
            "n_cycles": n_cycles,
            "is_lf_day": bool(online_day and swing >= 8),
        })
    return pd.DataFrame(out)


def diurnal_signature(hourly: pd.DataFrame) -> pd.DataFrame:
    """
    Firma giornaliera del load-following: per ogni ora del giorno, produzione
    media (in % Pnom) e rampa media. Il LF classico mostra un avvallamento
    notturno e rampe negative la sera / positive al mattino.
    """
    nominal = float(hourly["nominal_MW"].iloc[0])
    df = hourly.copy()
    df["hour"] = df.index.hour
    g = df.groupby("hour").agg(
        prod_pct=("production_MW_pos", lambda x: x.mean() / nominal * 100),
        ramp_MW=("ramp_MW_h", "mean"),
    ).reset_index()
    g["ramp_pct"] = g["ramp_MW"] / nominal * 100
    return g


def lf_summary(hourly: pd.DataFrame) -> dict:
    """KPI sintetici di load-following per un reattore/flotta nel periodo."""
    if hourly.empty:
        return {}
    nominal = float(hourly["nominal_MW"].iloc[0])
    states = classify_states(hourly)
    n = len(hourly)
    ev = ramp_events(hourly)
    online_ev = ev[ev["online"]] if not ev.empty else ev
    daily = daily_load_following(hourly)

    n_days = max(1, (hourly.index[-1] - hourly.index[0]).days)
    n_months = max(1, n_days / 30.44)

    # range operativo effettivo osservato mentre online (percentili robusti)
    online_prod = hourly["production_MW_pos"][states.isin(["load_follow", "full"])]
    p_low = (online_prod.quantile(0.02) / nominal * 100) if len(online_prod) else np.nan
    p_high = (online_prod.quantile(0.98) / nominal * 100) if len(online_prod) else np.nan

    return {
        "hours": n,
        "pct_full": (states == "full").mean() * 100,
        "pct_load_follow": (states == "load_follow").mean() * 100,
        "pct_low": (states == "low").mean() * 100,
        "pct_off": (states == "off").mean() * 100,
        "n_online_ramps": int(len(online_ev)),
        "online_ramps_per_month": len(online_ev) / n_months,
        "n_lf_days": int(daily["is_lf_day"].sum()) if not daily.empty else 0,
        "pct_lf_days": (daily["is_lf_day"].mean() * 100) if not daily.empty else 0,
        "cycles_per_lf_day": (daily.loc[daily["is_lf_day"], "n_cycles"].mean()
                              if (not daily.empty and daily["is_lf_day"].any()) else 0),
        "max_online_ramp_pct_h": (online_ev["rate_pct_h"].abs().max()
                                  if not online_ev.empty else 0),
        "p95_online_ramp_pct_h": (online_ev["rate_pct_h"].abs().quantile(0.95)
                                  if not online_ev.empty else 0),
        "obs_range_low_pct": p_low,
        "obs_range_high_pct": p_high,
    }
