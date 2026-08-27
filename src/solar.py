"""
solar.py — Quanto fotovoltaico regge il sistema?

Incrocia i dati solari francesi (capacità, generazione, quota di domanda,
curtailment per prezzi negativi — fonte RTE/energygraph, annuali) con la
modulazione oraria del parco nucleare misurata dal resto dell'app.

L'IDEA
------
Il nucleare assorbe parte della spinta del fotovoltaico abbassando la potenza a
mezzogiorno. Quel margine però non è infinito: quando si esaurisce, il PV in
eccesso viene tagliato (curtailment). Confrontando le due serie si vede
*quando* il buffer si satura.

CAVEAT (importanti se i numeri vengono citati)
----------------------------------------------
- I dati solari sono ANNUALI, quelli nucleari orari: il legame è forte ma
  correlativo, non un bilancio ora-per-ora.
- La curtailment è misurata "durante prezzi negativi": è un segnale di MERCATO,
  influenzato anche da export, vento e domanda, non solo da un limite fisico.
- Il 2026 è parziale (primo semestre, che pesa la primavera: stagione di
  massima curtailment) → va letto con cautela.
- Il 2022 è l'anno della crisi corrosione: metà parco fermo. Serve come
  controprova (nucleare assente → nessuna curtailment), non come trend.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "solar_france.csv"

# Mesi di alto irraggiamento: è lì che il conflitto nucleare/PV si gioca
SOLAR_SEASON = (4, 9)   # aprile → settembre


def load_solar(path: str | Path | None = None) -> pd.DataFrame:
    """Carica la serie annuale del fotovoltaico francese."""
    path = Path(path) if path else _DEFAULT_PATH
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["curtail_pct"] = np.where(
        df["pv_TWh"] > 0, df["curtail_GWh"] / (df["pv_TWh"] * 1000) * 100, np.nan
    )
    return df


def nuclear_midday_dip(hourly_by_reactor: dict, reactors: list,
                       years: list[int] | None = None,
                       season: tuple[int, int] = SOLAR_SEASON) -> pd.DataFrame:
    """
    Per ogni anno, di quanti GW il parco nucleare produce MENO a mezzogiorno
    (12–15) rispetto alla notte (2–5), nei mesi di alto sole.

    Valore positivo = il nucleare si abbassa a mezzogiorno (assorbe il PV).
    Valore negativo = regime pre-solare (a mezzogiorno produceva di più).
    """
    from src.metrics import aggregate_fleet

    if years is None:
        idx = None
        for r in reactors:
            if r in hourly_by_reactor:
                i = hourly_by_reactor[r].index
                idx = i if idx is None else idx.union(i)
        if idx is None or len(idx) == 0:
            return pd.DataFrame(columns=["year", "night_GW", "noon_GW", "dip_GW"])
        years = sorted({int(y) for y in idx.year})

    m0, m1 = season
    rows = []
    for y in years:
        fleet = aggregate_fleet(hourly_by_reactor, reactors,
                                f"{y}-{m0:02d}-01", f"{y}-{m1:02d}-30")
        if fleet.empty or len(fleet) < 24 * 60:
            continue
        p = fleet["production_MW_pos"] / 1000.0
        g = p.groupby(p.index.hour).mean()
        night = float(g.loc[2:5].mean())
        noon = float(g.loc[12:15].mean())
        rows.append({"year": int(y), "night_GW": night, "noon_GW": noon,
                     "dip_GW": night - noon})
    return pd.DataFrame(rows)


def integration_table(hourly_by_reactor: dict, reactors: list,
                      solar_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Tabella integrata: PV installato, quota di domanda, curtailment, dip nucleare."""
    solar = solar_df if solar_df is not None else load_solar()
    dip = nuclear_midday_dip(hourly_by_reactor, reactors)
    if solar.empty or dip.empty:
        return pd.DataFrame()
    t = solar.merge(dip, on="year", how="inner")
    return t.sort_values("year")


def saturation_summary(table: pd.DataFrame) -> dict:
    """
    Individua il regime di saturazione: l'anno in cui il dip nucleare smette di
    crescere mentre la curtailment continua a salire.
    """
    if table is None or table.empty or len(table) < 3:
        return {}
    t = table.dropna(subset=["dip_GW"]).sort_values("year")
    last = t.iloc[-1]
    peak_dip = float(t["dip_GW"].max())
    peak_year = int(t.loc[t["dip_GW"].idxmax(), "year"])

    # plateau: ultimi due anni con dip che cresce < 0.3 GW
    plateau = None
    if len(t) >= 2:
        d = t["dip_GW"].diff().iloc[-1]
        if abs(d) < 0.3 and peak_dip > 1:
            plateau = int(last["year"])

    out = {
        "peak_dip_GW": peak_dip,
        "peak_dip_year": peak_year,
        "last_year": int(last["year"]),
        "last_dip_GW": float(last["dip_GW"]),
        "last_pv_GW": float(last["pv_GW"]) if pd.notna(last.get("pv_GW")) else np.nan,
        "last_share_pct": float(last["max_share_pct"]) if pd.notna(last.get("max_share_pct")) else np.nan,
        "last_curtail_pct": float(last["curtail_pct"]) if pd.notna(last.get("curtail_pct")) else np.nan,
        "plateau_year": plateau,
    }
    # anno di controprova: nucleare basso e curtailment ~0
    if "curtail_pct" in t:
        low = t[(t["curtail_pct"] < 0.1) & (t["pv_GW"] > 12)]
        if not low.empty:
            out["control_year"] = int(low.iloc[-1]["year"])
    return out
