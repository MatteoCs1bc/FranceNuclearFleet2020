"""
environment.py — Indisponibilità per cause ambientali (siccità, ondate di calore,
temperatura e portata dei fiumi).

ATTENZIONE METODOLOGICA
-----------------------
Nei dati di energygraph **non esiste** un'etichetta esplicita "siccità" o
"canicule": cercandole non si trova nulla. L'unico appiglio è la categoria
   "Causes externes liées à l'environnement / Environmental issues"
che raggruppa tutti i vincoli ambientali. È quindi un **proxy**, non una misura
diretta della siccità.

Il proxy è però solido, perché mostra le due firme attese:
  1. STAGIONALITÀ — gli eventi si concentrano in luglio-agosto-settembre e sono
     quasi assenti in inverno;
  2. GEOGRAFIA — colpiscono i reattori raffreddati da fiumi (Rodano, Mosa, Reno,
     Garonna, Loira) e mai quelli costieri (Gravelines, Paluel, Penly,
     Flamanville), che hanno acqua di mare in abbondanza.

Restano inclusi altri vincoli ambientali non climatici (es. presenza di alghe o
detriti alle prese d'acqua): i numeri vanno letti come "vincoli ambientali",
di cui caldo e siccità sono la componente dominante estiva.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Sorgente di raffreddamento per sito. I siti fluviali sono quelli esposti a
# siccità e limiti di temperatura allo scarico; i costieri praticamente immuni.
COOLING = {
    "Belleville": ("fiume", "Loira"),
    "Blayais": ("estuario", "Gironda"),
    "Bugey": ("fiume", "Rodano"),
    "Cattenom": ("fiume", "Mosella"),
    "Chinon": ("fiume", "Loira"),
    "Chooz": ("fiume", "Mosa"),
    "Civaux": ("fiume", "Vienne"),
    "Cruas": ("fiume", "Rodano"),
    "Dampierre": ("fiume", "Loira"),
    "Fessenheim": ("fiume", "Reno"),
    "Flamanville": ("mare", "Manica"),
    "Golfech": ("fiume", "Garonna"),
    "Gravelines": ("mare", "Mare del Nord"),
    "Nogent": ("fiume", "Senna"),
    "Paluel": ("mare", "Manica"),
    "Penly": ("mare", "Manica"),
    "Saint-Alban": ("fiume", "Rodano"),
    "Saint-Laurent": ("fiume", "Loira"),
    "Tricastin": ("fiume", "Rodano"),
}

ENV_PATTERN = r"environnement|environmental"


def site_of(reactor: str) -> str:
    """'Saint-Alban 2' -> 'Saint-Alban'."""
    return reactor.rsplit(" ", 1)[0] if " " in reactor else reactor


def cooling_of(reactor: str) -> tuple[str, str]:
    """Ritorna (tipo_raffreddamento, corpo_idrico) per un reattore."""
    return COOLING.get(site_of(reactor), ("n/d", "n/d"))


def is_environmental(reason: pd.Series) -> pd.Series:
    """Maschera booleana: l'evento è classificato come causa ambientale."""
    return reason.fillna("").astype(str).str.lower().str.contains(
        ENV_PATTERN, regex=True
    )


def environmental_events(unavail_data: dict, nominal: dict,
                         date_from=None, date_to=None) -> pd.DataFrame:
    """
    Estrae gli eventi ambientali di tutti i reattori, con la stima dell'energia
    persa: (nominale − capacità disponibile durante l'evento) × durata.

    Colonne: reactor, site, cooling, water, start, end, duration_h,
             lost_MW, lost_GWh, year, month
    """
    frames = []
    for reactor, df in (unavail_data or {}).items():
        if df is None or df.empty or "reason" not in df.columns:
            continue
        e = df[is_environmental(df["reason"])].copy()
        if e.empty:
            continue
        e["reactor"] = reactor
        frames.append(e)

    if not frames:
        return pd.DataFrame(columns=["reactor", "site", "cooling", "water",
                                     "start", "end", "duration_h",
                                     "lost_MW", "lost_GWh", "year", "month"])

    E = pd.concat(frames, ignore_index=True)
    E["start"] = pd.to_datetime(E["start"], errors="coerce")
    E["end"] = pd.to_datetime(E["end"], errors="coerce")
    E = E.dropna(subset=["start", "end"])

    if date_from is not None:
        E = E[E["end"] > pd.Timestamp(date_from)]
    if date_to is not None:
        E = E[E["start"] < pd.Timestamp(date_to) + pd.Timedelta(days=1)]
    if E.empty:
        return pd.DataFrame(columns=["reactor", "site", "cooling", "water",
                                     "start", "end", "duration_h",
                                     "lost_MW", "lost_GWh", "year", "month"])

    E["duration_h"] = (E["end"] - E["start"]).dt.total_seconds() / 3600.0
    E["nominal_MW"] = E["reactor"].map(nominal).astype(float)
    E["value"] = pd.to_numeric(E.get("value"), errors="coerce")
    E["lost_MW"] = (E["nominal_MW"] - E["value"]).clip(lower=0)
    E["lost_GWh"] = E["lost_MW"] * E["duration_h"] / 1000.0
    E["site"] = E["reactor"].map(site_of)
    E["cooling"] = E["reactor"].map(lambda r: cooling_of(r)[0])
    E["water"] = E["reactor"].map(lambda r: cooling_of(r)[1])
    E["year"] = E["start"].dt.year
    E["month"] = E["start"].dt.month

    cols = ["reactor", "site", "cooling", "water", "start", "end",
            "duration_h", "lost_MW", "lost_GWh", "year", "month"]
    return E[cols].sort_values("start")


def environmental_summary(events: pd.DataFrame, total_production_TWh: float | None = None) -> dict:
    """KPI sintetici sugli eventi ambientali."""
    if events is None or events.empty:
        return {}
    summer = events[events["month"].isin([6, 7, 8, 9])]
    river = events[events["cooling"].isin(["fiume", "estuario"])]
    out = {
        "n_events": len(events),
        "hours": float(events["duration_h"].sum()),
        "lost_GWh": float(events["lost_GWh"].sum()),
        "pct_summer": float(len(summer) / len(events) * 100),
        "pct_river": float(len(river) / len(events) * 100),
        "n_reactors": int(events["reactor"].nunique()),
        "worst_year": int(events.groupby("year")["lost_GWh"].sum().idxmax()),
        "worst_year_GWh": float(events.groupby("year")["lost_GWh"].sum().max()),
        "top_reactor": events.groupby("reactor")["lost_GWh"].sum().idxmax(),
    }
    if total_production_TWh:
        out["pct_of_production"] = out["lost_GWh"] / 1000 / total_production_TWh * 100
    return out
