"""
loader.py — Caricamento e parsing dei CSV del parco nucleare.

Gestisce:
  - estrazione nome reattore dal filename
  - parsing produzione (unità miste GW/MW, valori negativi)
  - parsing eventi di indisponibilità
  - caricamento da ZIP o da cartella locale
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# Riconoscimento file
# ─────────────────────────────────────────────────────────────────────────────

def extract_reactor_name(filename: str) -> str:
    """Estrae 'Belleville_1' -> 'Belleville 1' dal nome file."""
    basename = Path(filename).name
    match = re.search(r"_([A-Z][A-Za-z_\-]+\d+)\.csv$", basename)
    if match:
        return match.group(1).replace("_", " ")
    parts = basename.replace(".csv", "").split("_")
    return " ".join(parts[-2:]) if len(parts) >= 2 else basename


def get_file_type(filename: str) -> str:
    """'production', 'unavailabilities' oppure 'unknown'."""
    name = Path(filename).name.lower()
    if name.startswith("availability_vs_production"):
        return "production"
    if name.startswith("unavailabilities"):
        return "unavailabilities"
    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Parsing valori
# ─────────────────────────────────────────────────────────────────────────────

_NUM_RE = re.compile(r"[-\d.]+")


def parse_power(value: str | float) -> float:
    """
    Converte '1.31 GW' -> 1310.0, '714 MW' -> 714.0, '-3 MW' -> -3.0.
    I negativi sono reali: il reattore assorbe rete durante i fermi.
    """
    if pd.isna(value):
        return np.nan
    text = str(value).strip()
    match = _NUM_RE.search(text)
    if match is None:
        return np.nan
    num = float(match.group())
    return num * 1000.0 if "GW" in text else num


# ─────────────────────────────────────────────────────────────────────────────
# Loader singoli
# ─────────────────────────────────────────────────────────────────────────────

def load_production(content: bytes, reactor: str) -> pd.DataFrame:
    """
    DataFrame indicizzato sul tempo (orario) con:
      production_MW      -> valore grezzo (può essere negativo)
      production_MW_pos  -> clip a 0 (per CF)
    """
    df = pd.read_csv(io.BytesIO(content))
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    df["production_MW"] = df["production"].apply(parse_power)
    df = df.dropna(subset=["Time", "production_MW"]).sort_values("Time")
    df = df.set_index("Time")
    df["production_MW_pos"] = df["production_MW"].clip(lower=0)
    df["reactor"] = reactor
    return df[["reactor", "production_MW", "production_MW_pos"]]


def load_unavailabilities(content: bytes, reactor: str) -> pd.DataFrame:
    """
    Eventi di indisponibilità. Tiene solo status 'active' e, per ogni id,
    l'ultima versione pubblicata (la più aggiornata).
      value      -> MW di capacità DISPONIBILE durante l'evento
      duration_h -> durata evento in ore
    """
    df = pd.read_csv(io.BytesIO(content))
    df["start"] = pd.to_datetime(df["start"], errors="coerce")
    df["end"] = pd.to_datetime(df["end"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["version"] = pd.to_numeric(df.get("version", 0), errors="coerce").fillna(0)
    df["reactor"] = reactor

    df = df.dropna(subset=["start", "end"])
    df = df[df["status"] == "active"]
    # ultima versione per ciascun id
    df = df.sort_values("version").groupby("id", as_index=False).last()

    df["duration_h"] = (df["end"] - df["start"]).dt.total_seconds() / 3600.0
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Caricamento in blocco
# ─────────────────────────────────────────────────────────────────────────────

def load_from_zip(zip_bytes: bytes, progress_cb=None) -> tuple[dict, dict, list]:
    """
    Legge uno ZIP di CSV.
    Ritorna: (prod_data, unavail_data, errors)
      prod_data[reactor]    -> DataFrame produzione
      unavail_data[reactor] -> DataFrame eventi
    """
    prod_data: dict[str, pd.DataFrame] = {}
    unavail_data: dict[str, pd.DataFrame] = {}
    errors: list[str] = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        total = len(names)

        for i, name in enumerate(names):
            reactor = extract_reactor_name(name)
            ftype = get_file_type(name)
            try:
                content = zf.read(name)
                if ftype == "production":
                    prod_data[reactor] = load_production(content, reactor)
                elif ftype == "unavailabilities":
                    unavail_data[reactor] = load_unavailabilities(content, reactor)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")

            if progress_cb:
                progress_cb((i + 1) / total, reactor, i + 1, total)

    return prod_data, unavail_data, errors


def load_from_folder(folder: str | Path, progress_cb=None) -> tuple[dict, dict, list]:
    """Come load_from_zip ma legge una cartella locale (utile in dev)."""
    folder = Path(folder)
    prod_data, unavail_data, errors = {}, {}, []
    files = sorted(folder.glob("*.csv"))
    total = len(files)

    for i, path in enumerate(files):
        reactor = extract_reactor_name(path.name)
        ftype = get_file_type(path.name)
        try:
            content = path.read_bytes()
            if ftype == "production":
                prod_data[reactor] = load_production(content, reactor)
            elif ftype == "unavailabilities":
                unavail_data[reactor] = load_unavailabilities(content, reactor)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path.name}: {exc}")

        if progress_cb:
            progress_cb((i + 1) / total, reactor, i + 1, total)

    return prod_data, unavail_data, errors
