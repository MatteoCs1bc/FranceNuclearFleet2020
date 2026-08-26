"""
metadata.py — Anagrafica dei reattori (tipo, palier, potenza, età).

I metadati vivono in data/reactors_metadata.csv (editabile).
Il matching col nome estratto dai CSV è tollerante: 'Belleville 1',
'Belleville_1', 'Belleville1', 'Chooz B2' vengono tutti normalizzati.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd

# Palier ordinati per generazione (per colori/ordinamento coerenti)
PALIER_ORDER = ["CP0", "CP1", "CP2", "P4", "P'4", "N4", "EPR"]

PALIER_COLORS = {
    "CP0": "#7C3AED",   # viola
    "CP1": "#2563EB",   # blu
    "CP2": "#0891B2",   # ciano
    "P4":  "#059669",   # verde
    "P'4": "#65A30D",   # verde-lime
    "N4":  "#EA580C",   # arancio
    "EPR": "#DC2626",   # rosso
}

PALIER_DESCR = {
    "CP0": "900 MW — 1ª gen. (Bugey/Fessenheim)",
    "CP1": "900 MW — CP1",
    "CP2": "900 MW — CP2",
    "P4":  "1300 MW — P4",
    "P'4": "1300 MW — P'4",
    "N4":  "1450 MW — N4 (modulazione avanzata)",
    "EPR": "1600 MW — EPR (Gen III+)",
}

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "reactors_metadata.csv"


def _normalize(name: str) -> str:
    """
    'Belleville 1' / 'Belleville_1' / 'Chooz B2' -> chiave comparabile.
    Rimuove spazi/underscore/trattini, la lettera di palier 'B' prima del
    numero, e mette in minuscolo. 'Saint-Alban 1' -> 'saintalban1'.
    """
    s = name.lower().strip()
    s = re.sub(r"[\s_\-]+", "", s)
    # rimuovi 'b' isolata prima del numero finale (Chinon B1 -> chinon1)
    s = re.sub(r"b(?=\d+$)", "", s)
    return s


def load_metadata(path: str | Path | None = None) -> pd.DataFrame:
    """Carica il CSV anagrafica e aggiunge la colonna chiave normalizzata."""
    path = Path(path) if path else _DEFAULT_PATH
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["_key"] = df["reactor"].apply(_normalize)
    return df


def build_lookup(meta_df: pd.DataFrame) -> dict:
    """Dizionario chiave_normalizzata -> record metadati (dict)."""
    if meta_df.empty:
        return {}
    return {row["_key"]: row.to_dict() for _, row in meta_df.iterrows()}


def match(reactor_name: str, lookup: dict) -> dict | None:
    """Restituisce i metadati per un nome reattore, o None."""
    return lookup.get(_normalize(reactor_name))


def enrich_reactor_list(
    reactors: list[str],
    meta_df: pd.DataFrame,
    as_of: int | None = None,
) -> pd.DataFrame:
    """
    Per una lista di reattori (nomi dai CSV) costruisce una tabella con i
    metadati agganciati + anni di esercizio calcolati.
    """
    as_of = as_of or datetime.now().year
    lookup = build_lookup(meta_df)
    rows = []
    for r in reactors:
        m = match(r, lookup)
        if m is None:
            rows.append({"reactor": r, "matched": False})
            continue
        comm = m.get("commissioning_year")
        decomm = m.get("decommission_year")
        end = int(decomm) if pd.notna(decomm) else as_of
        years = (end - int(comm)) if pd.notna(comm) else None
        rows.append({
            "reactor": r,
            "matched": True,
            "site": m.get("site"),
            "palier": m.get("palier"),
            "reactor_type": m.get("reactor_type"),
            "power_class_MW": m.get("power_class_MW"),
            "net_MW": m.get("net_MW"),
            "commissioning_year": int(comm) if pd.notna(comm) else None,
            "decommission_year": int(decomm) if pd.notna(decomm) else None,
            "years_operation": years,
            "active": pd.isna(decomm),
        })
    return pd.DataFrame(rows)
