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
    grp = (sign != sign.shift()).cumsum()

    work = pd.DataFrame({
        "time": hourly.index, "ramp": ramp.values,
        "sign": sign.values, "grp": grp.values,
    })
    work = work[work["sign"] != 0]
    if work.empty:
        return pd.DataFrame()

    g = work.groupby("grp", sort=False)
    res = g.agg(
        start=("time", "first"), end=("time", "last"),
        duration_h=("time", "size"), delta_MW=("ramp", "sum"),
        sign=("sign", "first"),
    ).reset_index(drop=True)

    prod_prev = prod.shift(1)
    res["p_before"] = prod_prev.reindex(res["start"]).values
    res["p_after"] = prod.reindex(res["end"]).values
    res["p_before"] = res["p_before"].fillna(res["p_after"])

    res["delta_pct"] = res["delta_MW"] / nominal * 100
    res["rate_pct_h"] = (res["delta_MW"] / res["duration_h"]) / nominal * 100
    res["direction"] = np.where(res["sign"] > 0, "up", "down")
    res["online"] = ((res["p_before"] >= ONLINE_THR * nominal) &
                     (res["p_after"] >= ONLINE_THR * nominal))
    return res[["start", "end", "duration_h", "delta_MW", "delta_pct",
                "rate_pct_h", "direction", "online"]]


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
    day = hourly.index.normalize()
    p = hourly["production_MW_pos"]
    g = p.groupby(day)
    pmin, pmax = g.min(), g.max()
    online_day = pmin >= ONLINE_THR * nominal
    swing = (pmax - pmin) / nominal * 100

    # cicli: conta le inversioni di segno della rampa entro lo stesso giorno
    r = hourly["ramp_MW_h"].fillna(0.0)
    sig = np.sign(r.where(r.abs() >= 0.03 * nominal, 0.0))
    sd = pd.DataFrame({"day": day, "sig": sig.values})
    sd = sd[sd["sig"] != 0]
    if not sd.empty:
        sd["prev"] = sd.groupby("day")["sig"].shift()
        sd["rev"] = (sd["sig"] != sd["prev"]) & sd["prev"].notna()
        revs = sd.groupby("day")["rev"].sum()
        n_cycles = (revs // 2).reindex(pmin.index).fillna(0).astype(int)
    else:
        n_cycles = pd.Series(0, index=pmin.index, dtype=int)

    out = pd.DataFrame({
        "date": pmin.index, "online_day": online_day.values,
        "swing_pct": swing.values, "n_cycles": n_cycles.values,
    })
    out["is_lf_day"] = out["online_day"] & (out["swing_pct"] >= 8)
    return out


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
    g["ramp_pct_min"] = g["ramp_pct"] / 60
    return g


def modulation_limits(hourly: pd.DataFrame) -> dict:
    """
    Caratterizza i LIMITI di modulazione osservati — il confronto col gas.
    Un reattore nucleare, a differenza di una turbina a gas, è vincolato da
    xeno-135, burn-up e fatica del cladding: modula lentamente, poche volte,
    con tempi di recupero tra una manovra e l'altra.

      max_ramp_rate_pct_h   — rampa online più veloce osservata (% Pnom/h)
      max_sustained_ramp_h  — durata max di una rampa mono-direzione (ore)
      max_depth_pct         — modulazione più profonda: 100 − min% online
      max_cycles_day        — max n. di cicli su/giù in un singolo giorno
      median_gap_h          — ore mediane tra due eventi-rampa (tempo "stabile")
      pct_baseload          — % di ore a piena potenza (non modula)
      n_online_ramps        — n. totale di eventi-rampa online nel periodo
    """
    if hourly.empty:
        return {}
    nominal = float(hourly["nominal_MW"].iloc[0])
    states = classify_states(hourly)
    ev = ramp_events(hourly)
    online = ev[ev["online"]] if not ev.empty else ev
    daily = daily_load_following(hourly)

    # tempo tra eventi (recovery): gap tra fine di un evento e inizio del successivo
    gaps = []
    if len(online) > 1:
        starts = online["start"].reset_index(drop=True)
        ends = online["end"].reset_index(drop=True)
        gaps = ((starts.iloc[1:].values - ends.iloc[:-1].values)
                .astype("timedelta64[h]").astype(float))

    online_prod = hourly["production_MW_pos"][states.isin(["load_follow", "full"])]
    min_online_pct = (online_prod.quantile(0.02) / nominal * 100) if len(online_prod) else np.nan

    return {
        "max_ramp_rate_pct_h": online["rate_pct_h"].abs().max() if not online.empty else 0,
        "max_ramp_rate_pct_min": (online["rate_pct_h"].abs().max() / 60) if not online.empty else 0,
        "max_sustained_ramp_h": int(online["duration_h"].max()) if not online.empty else 0,
        "max_depth_pct": (100 - min_online_pct) if pd.notna(min_online_pct) else 0,
        "max_cycles_day": int(daily["n_cycles"].max()) if not daily.empty else 0,
        "median_gap_h": float(np.median(gaps)) if len(gaps) else np.nan,
        "pct_baseload": (states == "full").mean() * 100,
        "n_online_ramps": int(len(online)),
    }


def peak_modulation_day(hourly: pd.DataFrame) -> dict:
    """
    Giorno di MASSIMA modulazione (escursione intra-giornaliera più ampia
    mentre online) col profilo orario, per mostrare "ecco quando ha modulato
    di più".
    """
    if hourly.empty:
        return {}
    nominal = float(hourly["nominal_MW"].iloc[0])
    daily = hourly.groupby(hourly.index.normalize())["production_MW_pos"]
    online = daily.min() >= ONLINE_THR * nominal
    swing = (daily.max() - daily.min()) / nominal * 100
    sw = swing[online]
    if sw.empty:
        sw = swing
    if sw.empty:
        return {}
    best = sw.idxmax()
    day = hourly[hourly.index.normalize() == best].copy()
    prof = pd.DataFrame({
        "hour": day.index.hour,
        "prod_MW": day["production_MW_pos"].values,
        "prod_pct": day["production_MW_pos"].values / nominal * 100,
    })
    r = day["ramp_MW_h"].fillna(0.0)
    sig = np.sign(r.where(r.abs() >= 0.03 * nominal, 0.0))
    sig = sig[sig != 0]
    reversals = int((sig.diff().abs() == 2).sum()) if len(sig) > 1 else 0
    return {"date": pd.Timestamp(best), "swing_pct": float(sw.loc[best]),
            "profile": prof, "n_cycles": reversals // 2, "nominal_MW": nominal}


def simultaneous_modulating(hourly_by_reactor: dict, reactors: list,
                            date_from, date_to) -> pd.Series:
    """Serie oraria: quanti reattori modulano insieme. Accumulo memory-light."""
    from src.metrics import slice_period
    simul = None
    for r in reactors:
        if r not in hourly_by_reactor:
            continue
        h = slice_period(hourly_by_reactor[r], date_from, date_to)
        if h.empty:
            continue
        flag = (classify_states(h) == "load_follow").astype("int16")
        simul = flag if simul is None else simul.add(flag, fill_value=0)
    return simul if simul is not None else pd.Series(dtype="int16")


def deep_modulations(hourly: pd.DataFrame, threshold_pct: float = 40.0) -> pd.DataFrame:
    """
    Conta per giorno le modulazioni profonde (ramp-down oltre threshold_pct del
    nominale) mentre il reattore è online. Restituisce un DataFrame per giorno
    con il numero di discese profonde: mostra il "tetto" fisico giornaliero.
    """
    ev = ramp_events(hourly)
    if ev.empty:
        return pd.DataFrame(columns=["day", "n_deep_down"])
    ev = ev[ev["online"]]
    deep = ev[(ev["direction"] == "down") & (ev["delta_pct"] < -threshold_pct)].copy()
    if deep.empty:
        return pd.DataFrame(columns=["day", "n_deep_down"])
    deep["day"] = deep["start"].dt.normalize()
    g = deep.groupby("day").size().rename("n_deep_down").reset_index()
    return g


def xenon_recovery(hourly: pd.DataFrame, threshold_pct: float = 40.0,
                   max_gap_h: float = 48) -> pd.Series:
    """
    Tempo (ore) tra la fine di un ramp-down profondo (> threshold_pct) e l'inizio
    della successiva risalita di potenza. È la firma del transitorio da xeno-135:
    dopo una discesa profonda, lo xeno accumulato ritarda la ripresa (picco a
    ~6-9 h, decadimento in 1-2 giorni).
    """
    ev = ramp_events(hourly)
    if ev.empty:
        return pd.Series(dtype=float)
    ev = ev[ev["online"]].sort_values("start").reset_index(drop=True)
    gaps = []
    dirn = ev["direction"].values
    dpct = ev["delta_pct"].values
    starts = ev["start"].values
    ends = ev["end"].values
    for i in range(len(ev) - 1):
        if dirn[i] == "down" and dpct[i] < -threshold_pct:
            for j in range(i + 1, len(ev)):
                if dirn[j] == "up":
                    gap = (starts[j] - ends[i]) / np.timedelta64(1, "h")
                    if 0 <= gap < max_gap_h:
                        gaps.append(float(gap))
                    break
    return pd.Series(gaps, dtype=float)


def fleet_modulation_capacity(hourly_by_reactor: dict, reactors: list,
                              date_from, date_to, min_coverage: float = 0.95) -> dict:
    """
    Capacità di modulazione della flotta su tre scale temporali, filtrando le
    ore con copertura dati insufficiente (per evitare artefatti quando molti
    reattori hanno dati mancanti):

      peak_swing_GW      — escursione intra-giornaliera MASSIMA (una tantum)
      peak_swing_p99_GW  — 99° percentile (picco robusto)
      sustained_GW       — escursione giornaliera MEDIANA (sostenibile ogni giorno)
      sustained_iqr_GW   — range abituale 25–75° percentile
      week_best_GW       — settimana più intensa (media giornaliera)
      seasonal_GW        — escursione tra mese più alto e più basso (modul. lenta)
      installed_GW, ramp_down_GW_h, ramp_up_GW_h, hours_valid, coverage_pct
    """
    from src.metrics import slice_period
    frames = []
    for r in reactors:
        if r not in hourly_by_reactor:
            continue
        h = slice_period(hourly_by_reactor[r], date_from, date_to)
        if h.empty:
            continue
        frames.append(h["production_MW_pos"].rename(r))
    if not frames:
        return {}
    mat = pd.concat(frames, axis=1, sort=True)
    n = len(frames)
    coverage = mat.notna().sum(axis=1)
    good = coverage >= min_coverage * n
    p = (mat.sum(axis=1) / 1000)[good]        # GW, solo ore ben coperte
    if p.empty:
        return {}

    installed = sum(float(hourly_by_reactor[r]["nominal_MW"].iloc[0])
                    for r in reactors if r in hourly_by_reactor) / 1000

    daily_max = p.resample("D").max()
    daily_min = p.resample("D").min()
    swing = (daily_max - daily_min).dropna()
    ramp = p.diff().dropna()
    monthly = p.resample("ME").mean()
    weekly_swing = swing.resample("W").mean()

    return {
        "installed_GW": installed,
        "hours_valid": int(good.sum()),
        "coverage_pct": float(good.mean() * 100),
        "peak_swing_GW": float(swing.max()) if len(swing) else 0,
        "peak_swing_p99_GW": float(swing.quantile(0.99)) if len(swing) else 0,
        "sustained_GW": float(swing.median()) if len(swing) else 0,
        "sustained_q25_GW": float(swing.quantile(0.25)) if len(swing) else 0,
        "sustained_q75_GW": float(swing.quantile(0.75)) if len(swing) else 0,
        "week_best_GW": float(weekly_swing.max()) if len(weekly_swing) else 0,
        "seasonal_GW": float(monthly.max() - monthly.min()) if len(monthly) else 0,
        "ramp_down_GW_h": float(ramp.min()) if len(ramp) else 0,
        "ramp_up_GW_h": float(ramp.max()) if len(ramp) else 0,
        "prod_min_GW": float(p.min()), "prod_max_GW": float(p.max()),
        "swing_series": swing,
    }


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
