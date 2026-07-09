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
# Riconoscimento file + canonicalizzazione nomi reattore
# ─────────────────────────────────────────────────────────────────────────────

# Alias di sito per uniformare le grafie incoerenti della sorgente
_SITE_ALIASES = {
    "st alban": "Saint-Alban",
    "saint alban": "Saint-Alban",
    "st laurent": "Saint-Laurent",
    "saint laurent": "Saint-Laurent",
    "fessheneim": "Fessenheim",   # refuso nella sorgente
    # 'Dampierre-en-Burly' è il nome completo del comune: energygraph usa
    # 'Burly' come sito → sono i reattori di Dampierre.
    "burly": "Dampierre",
    "dampierre en burly": "Dampierre",
}


def canonicalize_reactor_name(raw: str) -> str:
    """
    Normalizza le mille grafie in un nome canonico 'Sito N'.
      'bugey3'      -> 'Bugey 3'
      'Chinonb1'    -> 'Chinon 1'
      'ChinonB3'    -> 'Chinon 3'
      'Chooz B2'    -> 'Chooz 2'
      'St Alban 1'  -> 'Saint-Alban 1'
      'Fessheneim 1'-> 'Fessenheim 1'
      'Belleville2' -> 'Belleville 2'
    Nomi non riconosciuti (es. 'Burly 1') vengono solo ripuliti.
    """
    s = re.sub(r"\s+", " ", raw.strip())
    m = re.match(r"^(.+?)\s*(\d+)$", s)   # parte-sito + numero finale
    if not m:
        return s
    site, num = m.group(1).strip(), m.group(2)
    # rimuovi la lettera di designazione B/b (Chinon B, Chooz B), attaccata o no
    site = re.sub(r"\s*[Bb]$", "", site).strip()
    key = site.lower().replace("-", " ")
    if key in _SITE_ALIASES:
        site = _SITE_ALIASES[key]
    else:
        site = site.title()   # 'bugey' -> 'Bugey', 'BELLEVILLE' -> 'Belleville'
    return f"{site} {num}"


def extract_reactor_name(filename: str) -> str:
    """
    Estrae il nome reattore dal filename e lo canonicalizza.
    Ancora sul pattern orario 'HH_MM_SS_<Reattore>.csv'; in fallback prova
    il vecchio schema con underscore.
    """
    basename = Path(filename).name
    m = re.search(r"\d{2}_\d{2}_\d{2}[_ ](.+?)\.csv$", basename)
    if m:
        return canonicalize_reactor_name(m.group(1))
    # fallback: vecchio schema '..._Belleville_1.csv'
    m2 = re.search(r"_([A-Za-z][A-Za-z _\-]*\d+)\.csv$", basename)
    if m2:
        return canonicalize_reactor_name(m2.group(1))
    return basename.replace(".csv", "")


def get_file_type(filename: str) -> str:
    """'production', 'unavailabilities' oppure 'unknown'. Tollerante a spazi,
    parentesi e maiuscole/minuscole."""
    name = Path(filename).name.lower().lstrip()
    if name.startswith("unavail"):
        return "unavailabilities"
    if name.startswith("availability"):
        return "production"
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
    df["production_MW"] = df["production"].apply(parse_power).astype("float32")
    df = df.dropna(subset=["Time", "production_MW"]).sort_values("Time")
    df = df.set_index("Time")
    df["production_MW_pos"] = df["production_MW"].clip(lower=0).astype("float32")
    return df[["production_MW", "production_MW_pos"]]


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
