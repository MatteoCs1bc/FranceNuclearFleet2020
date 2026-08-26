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

# Alias di sito. Le CHIAVI sono "compattate": minuscole, senza spazi/underscore/
# trattini, senza la 'b' finale di designazione. Così la stessa voce copre
# 'Dampierre En Burly 3', 'Dampierre_En_Burly_3' e 'DampierreEnBurly3'.
_SITE_ALIASES = {
    "stalban": "Saint-Alban",
    "saintalban": "Saint-Alban",
    "stalbanstmaurice": "Saint-Alban",
    "stlaurent": "Saint-Laurent",
    "saintlaurent": "Saint-Laurent",
    "stlaurentdeseaux": "Saint-Laurent",
    "fessheneim": "Fessenheim",       # refuso nella sorgente
    # 'Dampierre-en-Burly' è il nome completo del comune: alcune sorgenti
    # usano solo 'Burly' → sono i reattori di Dampierre.
    "burly": "Dampierre",
    "dampierreenburly": "Dampierre",
    "nogentsurseine": "Nogent",
}

# Siti noti, per il fallback quando non c'è un alias
_KNOWN_SITES = {
    "belleville": "Belleville", "blayais": "Blayais", "bugey": "Bugey",
    "cattenom": "Cattenom", "chinon": "Chinon", "chooz": "Chooz",
    "civaux": "Civaux", "cruas": "Cruas", "dampierre": "Dampierre",
    "fessenheim": "Fessenheim", "flamanville": "Flamanville",
    "golfech": "Golfech", "gravelines": "Gravelines", "nogent": "Nogent",
    "paluel": "Paluel", "penly": "Penly", "tricastin": "Tricastin",
}


def _squash(text: str) -> str:
    """'Dampierre En Burly' / 'Dampierre_En_Burly' -> 'dampierreenburly'."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def canonicalize_reactor_name(raw: str) -> str:
    """
    Normalizza qualunque grafia in un nome canonico 'Sito N'. Copre:
      'bugey3' / 'Bugey 3' / 'Bugey_3'            -> 'Bugey 3'
      'ChinonB1' / 'Chinon B 1' / 'Chinonb1'      -> 'Chinon 1'
      'CHOOZB2' / 'Chooz B2'                      -> 'Chooz 2'
      'DampierreEnBurly3' / 'Burly 3'             -> 'Dampierre 3'
      'StLaurentdesEauxB1' / 'St Laurent des Eaux B 1' -> 'Saint-Laurent 1'
      'NogentSurSeine1'                           -> 'Nogent 1'
      'StAlbanStMaurice2'                         -> 'Saint-Alban 2'
    """
    s = re.sub(r"[\s_]+", " ", raw.strip())
    m = re.match(r"^(.*?)\s*(\d+)\s*$", s)      # parte-sito + numero finale
    if not m or not m.group(1).strip():
        return s
    site_raw, num = m.group(1).strip(), m.group(2)

    key = _squash(site_raw)
    key = re.sub(r"b$", "", key)                # 'chinonb' -> 'chinon'

    if key in _SITE_ALIASES:
        site = _SITE_ALIASES[key]
    elif key in _KNOWN_SITES:
        site = _KNOWN_SITES[key]
    else:
        # sito sconosciuto: ripulisci senza inventare (spazi + Title Case)
        site = re.sub(r"\s*[Bb]$", "", site_raw).strip().title()

    return f"{site} {num}"


def extract_reactor_name(filename: str) -> str:
    """
    Estrae il nome reattore dal filename e lo canonicalizza. Supporta:
      NUOVO (2015+):  'Belleville 1 - Availability.csv'
                      'Nogent Sur Seine 2 -Unavailabilities.csv'
      VECCHIO:        '...HH_MM_SS_Belleville 1.csv'
                      '..._Belleville_1.csv'
    """
    basename = Path(filename).name
    # NUOVO schema: '<Reattore> - Availability|Unavailabilities.csv'
    m0 = re.match(r"^(.*?)\s*-\s*(?:un)?availabilit(?:y|ies)\.csv$",
                  basename, flags=re.IGNORECASE)
    if m0 and m0.group(1).strip():
        return canonicalize_reactor_name(m0.group(1))
    # VECCHIO: ancorato all'orario 'HH_MM_SS_<Reattore>.csv'
    m = re.search(r"\d{2}_\d{2}_\d{2}[_ ](.+?)\.csv$", basename)
    if m:
        return canonicalize_reactor_name(m.group(1))
    # VECCHIO con underscore: '..._Belleville_1.csv'
    m2 = re.search(r"_([A-Za-z][A-Za-z _\-]*\d+)\.csv$", basename)
    if m2:
        return canonicalize_reactor_name(m2.group(1))
    return basename.replace(".csv", "")


def get_file_type(filename: str) -> str:
    """
    'production', 'unavailabilities' oppure 'unknown'.
    Riconosce sia i nomi vecchi (che iniziano con Availability/Unavailabilities)
    sia i nuovi ('<Reattore> - Availability.csv'), tollerando spazi e maiuscole.
    IMPORTANTE: 'unavail' va testato PRIMA di 'avail' perché contiene 'avail'.
    """
    name = Path(filename).name.lower().strip()
    if not name.endswith(".csv"):
        return "unknown"
    if "unavailabilit" in name:
        return "unavailabilities"
    if "availabilit" in name:
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

def normalize_production_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalizza un DataFrame grezzo di produzione (da CSV o da Flock/Arrow).
    Attende le colonne 'Time' e 'production' (accetta anche minuscole).
      production_MW      -> valore grezzo (può essere negativo)
      production_MW_pos  -> clip a 0 (per CF)
    """
    df = df.rename(columns={c: c.strip().lower() for c in df.columns})
    time_col = "time" if "time" in df.columns else df.columns[0]
    prod_col = "production" if "production" in df.columns else df.columns[-1]

    out = pd.DataFrame()
    out["Time"] = pd.to_datetime(df[time_col], errors="coerce")
    # se già numerico (Flock/Parquet tipizzato) evita il parsing di stringhe
    if pd.api.types.is_numeric_dtype(df[prod_col]):
        out["production_MW"] = df[prod_col].astype("float32").values
    else:
        out["production_MW"] = df[prod_col].apply(parse_power).astype("float32").values
    out = out.dropna(subset=["Time", "production_MW"]).sort_values("Time")
    out = out.set_index("Time")
    out["production_MW_pos"] = out["production_MW"].clip(lower=0).astype("float32")
    return out[["production_MW", "production_MW_pos"]]


def normalize_unavail_df(df: pd.DataFrame, reactor: str) -> pd.DataFrame:
    """
    Normalizza gli eventi di indisponibilità (da CSV o Flock/Arrow).
    Tiene solo status 'active' e, per ogni id, l'ultima versione pubblicata.
    """
    df = df.copy()
    df["start"] = pd.to_datetime(df["start"], errors="coerce")
    df["end"] = pd.to_datetime(df["end"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["version"] = pd.to_numeric(df.get("version", 0), errors="coerce").fillna(0)
    df["reactor"] = reactor

    df = df.dropna(subset=["start", "end"])
    if "status" in df.columns:
        df = df[df["status"] == "active"]
    if "id" in df.columns:
        df = df.sort_values("version").groupby("id", as_index=False).last()

    df["duration_h"] = (df["end"] - df["start"]).dt.total_seconds() / 3600.0
    return df


def load_production(content: bytes, reactor: str) -> pd.DataFrame:
    """Produzione da CSV (bytes)."""
    return normalize_production_df(
        pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
    )


def load_unavailabilities(content: bytes, reactor: str) -> pd.DataFrame:
    """Indisponibilità da CSV (bytes)."""
    return normalize_unavail_df(
        pd.read_csv(io.BytesIO(content), encoding="utf-8-sig"), reactor
    )


# ─────────────────────────────────────────────────────────────────────────────
# Caricamento in blocco
# ─────────────────────────────────────────────────────────────────────────────

def load_from_zip(zip_bytes: bytes, progress_cb=None) -> tuple[dict, dict, list]:
    """
    Legge uno ZIP di CSV **oppure** di Parquet (struttura Flock zippata:
    <Impianto>/availability.parquet, <Impianto>/unavailabilities.parquet).
    Ritorna: (prod_data, unavail_data, errors)
      prod_data[reactor]    -> DataFrame produzione
      unavail_data[reactor] -> DataFrame eventi
    """
    prod_data: dict[str, pd.DataFrame] = {}
    unavail_data: dict[str, pd.DataFrame] = {}
    errors: list[str] = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        all_names = zf.namelist()
        parquets = [n for n in all_names if n.lower().endswith(".parquet")]
        csvs = [n for n in all_names if n.lower().endswith(".csv")]

        # --- Caso A: ZIP di Parquet (db Flock zippato) ---
        if parquets:
            total = len(parquets)
            for i, name in enumerate(parquets):
                parts = Path(name).parts
                # l'impianto è la cartella che contiene il parquet
                plant = parts[-2] if len(parts) >= 2 else Path(name).stem
                reactor = canonicalize_reactor_name(plant)
                table = Path(name).stem.lower()
                try:
                    df = pd.read_parquet(io.BytesIO(zf.read(name)))
                    if "unavailabilit" in table:
                        unavail_data[reactor] = normalize_unavail_df(df, reactor)
                    elif "availabilit" in table or "production" in table:
                        prod_data[reactor] = normalize_production_df(df)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{name}: {exc}")
                if progress_cb:
                    progress_cb((i + 1) / total, reactor, i + 1, total)
            return prod_data, unavail_data, errors

        # --- Caso B: ZIP di CSV ---
        total = len(csvs)
        for i, name in enumerate(csvs):
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


def load_from_flock(foldername: str | Path = "data") -> tuple[dict, dict, list]:
    """
    Carica da un database Flock (pyarrow/duckdb) con due chiavi:
    impianto × tipo_di_tabella (availability | unavailabilities).

    Struttura attesa: una cartella per impianto, interrogabile con
        db.availability.plants(<impianto>).to_pandas()
        db.unavailabilities.plants(<impianto>).to_pandas()

    Solleva ImportError se `flock` non è installato: il chiamante
    (`load_from_folder`) intercetta e ricade sui CSV.
    """
    from flock import Flock  # import locale: opzionale

    db = Flock(str(foldername))
    plants = db.get_folders()
    prod_data: dict[str, pd.DataFrame] = {}
    unavail_data: dict[str, pd.DataFrame] = {}
    errors: list[str] = []

    for pp in plants:
        reactor = canonicalize_reactor_name(pp)
        try:
            prod_data[reactor] = normalize_production_df(
                db.availability.plants(pp).to_pandas()
            )
            unavail_data[reactor] = normalize_unavail_df(
                db.unavailabilities.plants(pp).to_pandas(), reactor
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{pp}: {exc}")

    return prod_data, unavail_data, errors


def load_from_folder(folder: str | Path = "data", progress_cb=None,
                     prefer_flock: bool = True) -> tuple[dict, dict, list]:
    """
    Carica da cartella locale. Prova prima il database Flock (più veloce e
    leggero); se `flock` non è disponibile o la cartella non è un db Flock,
    ricade automaticamente sui CSV.
    """
    if prefer_flock:
        try:
            prod, unavail, errors = load_from_flock(folder)
            if prod:                      # Flock ha restituito dati validi
                return prod, unavail, errors
        except ImportError:
            pass                          # flock non installato → CSV
        except Exception:                 # noqa: BLE001
            pass                          # non è un db Flock → CSV

    return load_from_folder_csv(folder, progress_cb=progress_cb)


def load_from_folder_csv(folder: str | Path, progress_cb=None) -> tuple[dict, dict, list]:
    """Come load_from_zip ma legge i CSV da una cartella locale."""
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
