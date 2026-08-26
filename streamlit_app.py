"""
Nuclear Fleet Analyzer — Analisi della modulazione del parco nucleare francese
Capacity factor, load-following, limiti di modulazione e vincoli fisici (xeno-135),
per reattore singolo e per l'intera flotta.

Sviluppato da Matteo De Piccoli — Ci Sarà un Bel Clima (https://unbelclima.it/)
Autore di "Avete rotto l'atomo".

Entry point per Streamlit (compatibile con Streamlit Community Cloud).
Uso:
    streamlit run streamlit_app.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from src.loader import load_from_zip, load_from_folder
from src.metrics import (
    build_all_hourly, slice_period, compute_kpis,
    aggregate_fleet, fleet_kpis, matched_events_in_period,
    reactor_modulation_metrics, palier_summary,
)
from src.metadata import load_metadata, match, build_lookup, enrich_reactor_list, PALIER_DESCR
from src import charts
from src import loadfollowing as lf
from src import environment as env

# Coordinate dei siti (chiavi = nomi CANONICI prodotti da canonicalize_reactor_name:
# 'Chinon 1' non 'Chinon B1', 'Saint-Laurent 1' non 'Saint-Laurent B1', ecc.)
REACTOR_COORDS = {
    "Belleville 1": (47.5092, 2.8753), "Belleville 2": (47.5103, 2.8758),
    "Blayais 1": (45.2551, -0.6936), "Blayais 2": (45.2556, -0.6931),
    "Blayais 3": (45.2562, -0.6925), "Blayais 4": (45.2567, -0.6920),
    "Bugey 2": (45.7981, 5.2703), "Bugey 3": (45.7986, 5.2708),
    "Bugey 4": (45.7991, 5.2713), "Bugey 5": (45.7996, 5.2718),
    "Cattenom 1": (49.4151, 6.2175), "Cattenom 2": (49.4156, 6.2180),
    "Cattenom 3": (49.4161, 6.2185), "Cattenom 4": (49.4166, 6.2190),
    "Chinon 1": (47.2301, 0.1701), "Chinon 2": (47.2306, 0.1706),
    "Chinon 3": (47.2311, 0.1711), "Chinon 4": (47.2316, 0.1716),
    "Chooz 1": (50.0901, 4.7891), "Chooz 2": (50.0906, 4.7896),
    "Civaux 1": (46.4561, 0.6523), "Civaux 2": (46.4566, 0.6528),
    "Cruas 1": (44.6326, 4.7562), "Cruas 2": (44.6331, 4.7567),
    "Cruas 3": (44.6336, 4.7572), "Cruas 4": (44.6341, 4.7577),
    "Dampierre 1": (47.7331, 2.5181), "Dampierre 2": (47.7336, 2.5186),
    "Dampierre 3": (47.7341, 2.5191), "Dampierre 4": (47.7346, 2.5196),
    "Fessenheim 1": (47.9033, 7.5722), "Fessenheim 2": (47.9038, 7.5727),
    "Flamanville 1": (49.5356, -1.8824), "Flamanville 2": (49.5361, -1.8819),
    "Flamanville 3": (49.5370, -1.8790),
    "Golfech 1": (44.1064, 0.8448), "Golfech 2": (44.1069, 0.8453),
    "Gravelines 1": (51.0148, 2.1364), "Gravelines 2": (51.0151, 2.1367),
    "Gravelines 3": (51.0154, 2.1370), "Gravelines 4": (51.0157, 2.1373),
    "Gravelines 5": (51.0160, 2.1376), "Gravelines 6": (51.0163, 2.1379),
    "Nogent 1": (48.5148, 3.5173), "Nogent 2": (48.5153, 3.5178),
    "Paluel 1": (49.8576, 0.6331), "Paluel 2": (49.8581, 0.6336),
    "Paluel 3": (49.8586, 0.6341), "Paluel 4": (49.8591, 0.6346),
    "Penly 1": (49.9753, 1.2117), "Penly 2": (49.9758, 1.2122),
    "Saint-Alban 1": (45.4034, 4.7553), "Saint-Alban 2": (45.4039, 4.7558),
    "Saint-Laurent 1": (47.7195, 1.5770), "Saint-Laurent 2": (47.7200, 1.5775),
    "Tricastin 1": (44.3287, 4.7312), "Tricastin 2": (44.3292, 4.7317),
    "Tricastin 3": (44.3297, 4.7322), "Tricastin 4": (44.3302, 4.7327),
}


@st.cache_data(show_spinner=False)
def _metadata_cached():
    return load_metadata()


def _rdylgn(val, vmin: float = 0, vmax: float = 100) -> str:
    """Colore di sfondo rosso→giallo→verde per un valore, senza matplotlib.
    Restituisce una stringa CSS usabile con Styler.map."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    try:
        t = (float(val) - vmin) / (vmax - vmin)
    except (TypeError, ValueError):
        return ""
    t = max(0.0, min(1.0, t))
    if t < 0.5:                      # rosso -> giallo
        f = t / 0.5
        r, g, b = 183 + (245 - 183) * f, 28 + (200 - 28) * f, 28 + (50 - 28) * f
    else:                            # giallo -> verde
        f = (t - 0.5) / 0.5
        r, g, b = 245 + (21 - 245) * f, 200 + (128 - 200) * f, 50 + (61 - 50) * f
    return f"background-color: rgba({int(r)},{int(g)},{int(b)},0.38)"


def _style_gradient(df, subset=None, vmin=0, vmax=100):
    """Applica _rdylgn a un DataFrame (tutte le colonne o un subset)."""
    return df.style.map(lambda v: _rdylgn(v, vmin, vmax), subset=subset)

st.set_page_config(
    page_title="⚛️ Nuclear Fleet Analyzer",
    page_icon="⚛️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─────────────────────────────────────────────────────────────────────────────
# Caching dei dati
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def _load_zip_cached(zip_bytes: bytes):
    holder = {"pct": 0.0, "reactor": "", "i": 0, "n": 0}

    def cb(pct, reactor, i, n):
        holder.update(pct=pct, reactor=reactor, i=i, n=n)

    prod, unavail, errors = load_from_zip(zip_bytes, progress_cb=cb)
    hourly, nominal = build_all_hourly(prod, unavail)
    return prod, unavail, hourly, nominal, errors


@st.cache_data(show_spinner=False)
def _load_folder_cached(folder: str):
    prod, unavail, errors = load_from_folder(folder)
    hourly, nominal = build_all_hourly(prod, unavail)
    return prod, unavail, hourly, nominal, errors


@st.cache_data(show_spinner=False)
def _load_zip_path_cached(zip_path: str, _mtime: float):
    """Carica uno ZIP presente su disco (nel repo). _mtime invalida la cache
    se il file cambia."""
    with open(zip_path, "rb") as fh:
        return _load_zip_cached(fh.read())


def _find_repo_data():
    """
    Cerca dati già presenti nel repo, senza interazione utente.
    Ritorna (kind, path, diag) dove kind ∈ {'zip','folder',None} e diag è un
    dict con info di debug su dove ha cercato e cosa ha visto.
    Priorità: ZIP in data/ → ZIP nella root → ZIP ovunque (ricorsivo) → CSV.
    """
    root = Path(__file__).resolve().parent
    data_dir = root / "data"

    diag = {
        "cartella_app": str(root),
        "data_esiste": data_dir.exists(),
        "contenuto_root": [],
        "contenuto_data": [],
        "zip_trovati": [],
    }
    try:
        diag["contenuto_root"] = sorted(p.name for p in root.iterdir())
    except Exception:
        pass
    if data_dir.exists():
        try:
            diag["contenuto_data"] = sorted(p.name for p in data_dir.iterdir())
        except Exception:
            pass

    # 0) Database Flock (Parquet): ha priorità se la libreria è importabile e
    # data/ contiene sottocartelle-impianto con dentro dei .parquet.
    # NB: reactors_metadata.csv vive in data/ e NON deve invalidare il check.
    try:
        import flock  # noqa: F401
        if data_dir.exists():
            subdirs = [p for p in data_dir.iterdir() if p.is_dir()]
            has_parquet = any(d.glob("*.parquet") for d in subdirs)
            if subdirs and has_parquet:
                diag["flock"] = f"{len(subdirs)} cartelle-impianto con Parquet"
                return "flock", data_dir, diag
            diag["flock"] = (f"libreria ok, ma nessun Parquet in data/ "
                             f"({len(subdirs)} sottocartelle)")
    except ImportError as exc:
        diag["flock"] = f"libreria non importabile ({exc})"

    # Cerca zip: data/ → root → ricorsivo ovunque
    candidates = []
    if data_dir.exists():
        candidates += sorted(data_dir.glob("*.zip"))
    candidates += sorted(root.glob("*.zip"))
    if not candidates:
        candidates += sorted(root.rglob("*.zip"))
    # dedup mantenendo l'ordine
    seen, zips = set(), []
    for z in candidates:
        if str(z) not in seen:
            seen.add(str(z))
            zips.append(z)
    diag["zip_trovati"] = [str(z) for z in zips]

    if zips:
        return "zip", zips[0], diag

    # CSV di produzione/eventi sciolti (ricorsivo, escludendo l'anagrafica)
    csvs = []
    for base in (data_dir, root):
        if base.exists():
            csvs += [p for p in base.rglob("*.csv")
                     if p.name != "reactors_metadata.csv"]
    if csvs:
        return "folder", csvs[0].parent, diag

    return None, None, diag


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar: caricamento + filtri
# ─────────────────────────────────────────────────────────────────────────────

def sidebar_controls():
    st.sidebar.title("⚛️ Fleet Analyzer")

    st.sidebar.markdown(
        "<div style='font-size:0.8em; color:#888; margin-top:-8px; margin-bottom:8px;'>"
        "Sviluppato da <b>Matteo De Piccoli</b><br>"
        "Autore di <a href='https://www.peoplepub.it/pagina-prodotto/avete-rotto-l-atomo' "
        "target='_blank' style='color:#888;'><i>Avete rotto l'atomo</i></a><br>"
        "<a href='https://unbelclima.it/' target='_blank' "
        "style='color:#16A34A; text-decoration:none;'>🌍 Ci Sarà un Bel Clima</a>"
        "</div>",
        unsafe_allow_html=True,
    )

    with st.sidebar.expander("ℹ️ Come funziona"):
        st.markdown(
            "Questo strumento misura **quanto e quanto spesso** il nucleare francese "
            "modula la potenza (*load-following*), per singolo reattore e per l'intera flotta.\n\n"
            "**Dati**: potenze orarie 2015–oggi da energygraph.info. La *capacità "
            "disponibile* viene ricostruita dagli eventi di indisponibilità.\n\n"
            "**Cosa guardare**:\n"
            "- *Reattore singolo* → limiti di modulazione: rampa massima, profondità, "
            "cicli/giorno, tempo tra le manovre, giorno di massima modulazione, e i "
            "vincoli fisici (xeno-135).\n"
            "- *Flotta* → quanti reattori modulano insieme e confronto per palier.\n\n"
            "L'idea di fondo: capire se il nucleare può modulare come una centrale a gas "
            "(spoiler: no, ed è visibile nei numeri)."
        )

    with st.sidebar.expander("🏭 Cosa sono i palier"):
        try:
            _paliers_md = (Path(__file__).resolve().parent / "PALIERS.md").read_text(encoding="utf-8")
            st.markdown(_paliers_md)
        except Exception:
            st.caption("File `PALIERS.md` non trovato nel repo.")

    if st.sidebar.button("🔄 Ricarica dati (svuota cache)"):
        st.cache_data.clear()
        st.rerun()

    prod = unavail = hourly = nominal = errors = None

    # 1) Auto-detect dei dati già nel repo (nessuna interazione richiesta)
    kind, path, diag = _find_repo_data()
    load_error = None

    if kind == "zip":
        try:
            with st.spinner(f"Carico {path.name}…"):
                prod, unavail, hourly, nominal, errors = _load_zip_path_cached(
                    str(path), path.stat().st_mtime
                )
        except Exception as exc:  # noqa: BLE001
            load_error = f"Errore leggendo {path.name}: {exc}"
    elif kind in ("folder", "flock"):
        label = "Carico dal database Flock…" if kind == "flock" else "Carico i CSV…"
        try:
            with st.spinner(label):
                prod, unavail, hourly, nominal, errors = _load_folder_cached(str(path))
        except Exception as exc:  # noqa: BLE001
            load_error = f"Errore leggendo {'il db Flock' if kind=='flock' else 'i CSV'}: {exc}"

    n_react = len(hourly) if hourly else 0

    # Esiti possibili:
    if n_react > 0:
        icon = {"zip": "📦", "flock": "🗄️", "folder": "📁"}.get(kind, "📦")
        src = path.name if kind == "zip" else path
        st.sidebar.success(f"{icon} `{src}` · **{n_react} reattori**")
    elif kind is not None:
        # File trovato ma 0 reattori estratti → problema di nomi/contenuto
        st.sidebar.error(
            f"Trovato `{Path(diag['zip_trovati'][0]).name if diag['zip_trovati'] else path}` "
            "ma **0 reattori** estratti."
        )
        if load_error:
            st.sidebar.caption(load_error)
        st.sidebar.caption(
            "I nomi dei CSV dentro lo ZIP non sono riconosciuti. "
            "Attesi: file che iniziano con *Availability vs production* e "
            "*Unavailabilities*."
        )
    else:
        st.sidebar.warning("Nessuno ZIP/CSV trovato nel repo.")

    # Diagnostica + upload manuale: mostrati SOLO se i dati non si caricano.
    # Con lo ZIP nel repo l'app parte da sola, senza UI di caricamento.
    if n_react == 0:
        with st.sidebar.expander("🔎 Diagnostica dati", expanded=True):
            st.caption(f"Cartella app: `{diag['cartella_app']}`")
            st.write("**File nella root:**", diag["contenuto_root"] or "—")
            if diag["data_esiste"]:
                st.write("**File in `data/`:**", diag["contenuto_data"] or "—")
            st.write("**ZIP trovati:**", diag["zip_trovati"] or "nessuno")
            st.write("**Flock:**", diag.get("flock", "non verificato"))
            if kind == "zip" and diag["zip_trovati"]:
                try:
                    import zipfile
                    from src.loader import get_file_type
                    with zipfile.ZipFile(diag["zip_trovati"][0]) as zf:
                        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                    types = {}
                    for n in names:
                        types[get_file_type(n)] = types.get(get_file_type(n), 0) + 1
                    st.write("Tipi rilevati:", types)
                    if types.get("unknown", 0) == len(names) and names:
                        st.error("Tutti 'unknown' → `src/loader.py` sul server è vecchio.")
                except Exception as exc:  # noqa: BLE001
                    st.caption(f"Ispezione ZIP fallita: {exc}")

        with st.sidebar.expander("📂 Carica uno ZIP manualmente", expanded=True):
            zf = st.file_uploader("ZIP con i CSV", type=["zip"], key="override_zip")
            if zf is not None:
                with st.spinner("Parsing…"):
                    prod, unavail, hourly, nominal, errors = _load_zip_cached(zf.read())

    return prod, unavail, hourly, nominal, errors


def period_and_reactor_controls(hourly: dict, nominal: dict):
    reactors = list(hourly.keys())
    st.sidebar.divider()
    st.sidebar.subheader("🎛️ Selezione")

    # Etichette con palier + anno, ordinate per età (vecchi → nuovi)
    enr = enrich_reactor_list(reactors, _metadata_cached())
    info = {row["reactor"]: row for _, row in enr.iterrows()}

    def sort_key(r):
        m = info.get(r, {})
        yr = m.get("commissioning_year")
        return (yr if pd.notna(yr) else 9999, r)

    reactors_sorted = sorted(reactors, key=sort_key)

    def label(r):
        m = info.get(r, {})
        if m.get("matched"):
            yr = int(m["commissioning_year"]) if pd.notna(m.get("commissioning_year")) else "?"
            return f"{r} · {m['palier']} · {yr}"
        return f"{r} · (n/d)"

    mode = st.sidebar.radio("Modalità analisi",
                            ["Reattore singolo", "Aggregata (flotta)"])

    if mode == "Reattore singolo":
        # session_state tiene la scelta sincronizzata con il clic sulla mappa
        if ("selected_reactor" not in st.session_state
                or st.session_state["selected_reactor"] not in reactors_sorted):
            st.session_state["selected_reactor"] = reactors_sorted[0]
        idx = reactors_sorted.index(st.session_state["selected_reactor"])
        chosen = st.sidebar.selectbox("Reattore", reactors_sorted,
                                      index=idx, format_func=label)
        st.session_state["selected_reactor"] = chosen
        selected = [chosen]
        st.sidebar.caption("Ordinati per anno di accensione (vecchi → nuovi)")
    else:
        # Flotta INTERA di default; filtro rapido per palier
        paliers = sorted({info[r]["palier"] for r in reactors
                          if info.get(r, {}).get("matched")})
        pick_pal = st.sidebar.multiselect("Filtra per palier (vuoto = tutti)",
                                          paliers, default=[])
        pool = [r for r in reactors_sorted
                if not pick_pal or info.get(r, {}).get("palier") in pick_pal]
        selected = st.sidebar.multiselect("Reattori", reactors_sorted,
                                          default=pool, format_func=label)
        st.sidebar.caption(f"{len(selected)} reattori selezionati (default: tutti)")

    # Range temporale globale
    all_idx = pd.DatetimeIndex([])
    for r in (selected or reactors):
        if r in hourly:
            all_idx = all_idx.union(hourly[r].index)
    if len(all_idx) == 0:
        return mode, selected, None, None, reactors_sorted
    min_d, max_d = all_idx.min().date(), all_idx.max().date()

    st.sidebar.markdown("**Periodo**")
    quick = st.sidebar.selectbox(
        "Preset", ["Personalizzato", "Ultimo anno", "Ultimi 6 mesi",
                   "Ultimo mese", "Tutto"],
    )
    preset_days = {"Ultimo anno": 365, "Ultimi 6 mesi": 182, "Ultimo mese": 30}

    if quick == "Tutto":
        date_from, date_to = min_d, max_d
    elif quick in preset_days:
        date_to = max_d
        date_from = (pd.Timestamp(max_d) - pd.Timedelta(days=preset_days[quick])).date()
        date_from = max(min_d, date_from)
    else:  # Personalizzato
        picked = st.sidebar.date_input(
            "Intervallo", value=(min_d, max_d),
            min_value=min_d, max_value=max_d,
        )
        if isinstance(picked, tuple) and len(picked) == 2:
            date_from, date_to = picked
        else:
            date_from, date_to = min_d, max_d

    st.sidebar.caption(f"📅 {date_from} → {date_to}")
    return mode, selected, date_from, date_to, reactors_sorted


# ─────────────────────────────────────────────────────────────────────────────
# Vista: Reattore singolo
# ─────────────────────────────────────────────────────────────────────────────

def render_main_map(reactors_sorted, chosen):
    """
    Mappa interattiva del parco: clic su un pallino → seleziona il reattore.

    NOTA: `px.scatter_mapbox` è stato RIMOSSO in Plotly 6 (Streamlit Cloud usa
    la 6.x) → AttributeError. Qui si usa `px.scatter_map` (MapLibre, Plotly
    ≥5.24) con fallback automatico a `scatter_mapbox` sulle versioni vecchie.
    """
    import plotly.express as px

    map_rows = []
    for r in reactors_sorted:
        coords = REACTOR_COORDS.get(r)
        if coords:
            map_rows.append({
                "Reattore": r, "lat": coords[0], "lon": coords[1],
                "Stato": "Selezionato" if r == chosen else "Altri reattori",
            })
    if not map_rows:
        return

    df_map = pd.DataFrame(map_rows)
    common = dict(
        lat="lat", lon="lon", hover_name="Reattore",
        custom_data=["Reattore"], color="Stato",
        color_discrete_map={"Selezionato": "#EF4444", "Altri reattori": "#3B82F6"},
        zoom=4.6, center={"lat": 46.6033, "lon": 2.2}, height=600,
    )

    if hasattr(px, "scatter_map"):          # Plotly ≥ 5.24 (incl. 6.x)
        fig_map = px.scatter_map(df_map, map_style="open-street-map", **common)
    else:                                   # Plotly < 5.24
        fig_map = px.scatter_mapbox(df_map, mapbox_style="open-street-map", **common)

    fig_map.update_traces(marker=dict(size=13, opacity=0.95))
    fig_map.update_layout(
        margin={"r": 0, "t": 10, "l": 0, "b": 10},
        legend=dict(title=None, yanchor="top", y=0.97, xanchor="left", x=0.01,
                    bgcolor="white", bordercolor="black", borderwidth=2,
                    font=dict(color="black", size=13)),
        clickmode="event+select",
    )

    with st.expander("🗺️ **Mappa interattiva del parco** (clicca un pallino per selezionare)",
                     expanded=False):
        event = st.plotly_chart(
            fig_map, use_container_width=True, on_select="rerun",
            key="main_map_click_event", config={"scrollZoom": True},
        )

    # Il clic arriva come evento di selezione: aggiorna lo stato e ricarica
    try:
        points = event["selection"]["points"] if event else []
    except (KeyError, TypeError):
        points = []
    if points:
        clicked = points[0].get("customdata", [None])[0]
        if clicked and clicked != st.session_state.get("selected_reactor"):
            st.session_state["selected_reactor"] = clicked
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Vista: Reattore singolo
# ─────────────────────────────────────────────────────────────────────────────

def render_single(reactor, hourly, unavail_data, date_from, date_to):
    h_full = hourly[reactor]
    h = slice_period(h_full, date_from, date_to)
    if h.empty:
        st.warning("Nessun dato nel periodo selezionato.")
        return

    kpi = compute_kpis(h)
    events = matched_events_in_period(unavail_data.get(reactor), date_from, date_to)

    st.subheader(f"🔬 {reactor}")

    # Badge anagrafica compatto (non molesto): una riga con i metadati
    meta = match(reactor, build_lookup(_metadata_cached()))
    if meta:
        end = int(meta["decommission_year"]) if pd.notna(meta.get("decommission_year")) else pd.Timestamp(date_to).year
        years = end - int(meta["commissioning_year"])
        status = "🟢 in esercizio" if pd.isna(meta.get("decommission_year")) else f"⚫ dismesso {int(meta['decommission_year'])}"
        badge = (
            f"**{meta['reactor_type']} · palier {meta['palier']}** "
            f"({PALIER_DESCR.get(meta['palier'], '')})  ·  "
            f"⚡ {meta['net_MW']:.0f} MW netti  ·  "
            f"🗓️ acceso **{int(meta['commissioning_year'])}** · **{years} anni** di esercizio  ·  {status}"
        )
        st.caption(badge)

    st.caption(
        f"Nominale stimato dai dati ~{kpi['nominal_MW']:.0f} MW · "
        f"{kpi['hours']:,} ore · {date_from} → {date_to}"
    )

    # KPI: limiti di modulazione (il confronto col gas)
    ml = lf.modulation_limits(h)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Rampa max", f"{ml['max_ramp_rate_pct_min']:.2f}% Pnom/min",
              help="Manovra più veloce osservata mentre online (media sul minuto, dato orario). "
                   "Letteratura EDF: fino a ~1–5%/min con le barre grigie.")
    c2.metric("Modulazione più profonda", f"−{ml['max_depth_pct']:.0f}%",
              help="Scesa massima sotto il nominale restando in marcia. EDF: fino a −80% (20% Pnom).")
    c3.metric("Max cicli in un giorno", f"{ml['max_cycles_day']}",
              help="Su/giù nello stesso giorno. EDF: fino a 2/giorno.")
    c4.metric("Tempo tra manovre", f"{ml['median_gap_h']:.0f} h" if pd.notna(ml['median_gap_h']) else "—",
              help="Ore mediane di stabilità tra due manovre (vincolo xeno-135). Il gas può ri-rampare subito.")
    c5.metric("Tempo a piena potenza", f"{ml['pct_baseload']:.0f}%",
              help="Quota di ore in baseload (non modula).")

    st.divider()
    tabs = st.tabs(["🔁 Modulazione", "⚛️ Vincoli fisici", "📉 Produzione & CF",
                    "🔧 Indisponibilità"])

    # --- MODULAZIONE (focus) ---
    with tabs[0]:
        st.markdown("#### Firma giornaliera: quando e quanto modula")
        st.caption(
            "Produzione media e rampe per ora del giorno. L'avvallamento di "
            "mezzogiorno, se presente, è indotto dal fotovoltaico che spinge giù "
            "il nucleare nelle ore centrali."
        )
        st.plotly_chart(charts.lf_diurnal_profile(h), use_container_width=True)

        # Giorno di massima modulazione (punto 8)
        pk = lf.peak_modulation_day(h)
        if pk:
            st.markdown(f"#### Giorno di massima modulazione: **{pk['date'].date()}**")
            # Contesto: quanto è ECCEZIONALE quel giorno rispetto agli altri
            daily_all = lf.daily_load_following(h)
            ctx = ""
            if not daily_all.empty:
                sw = daily_all.loc[daily_all["online_day"], "swing_pct"].dropna()
                if len(sw) > 5:
                    med = sw.median()
                    pct_like = (sw >= pk["swing_pct"] * 0.8).mean() * 100
                    ctx = (
                        f" Per confronto, la **giornata tipica** di questo reattore modula "
                        f"il **{med:.0f}%**, e solo il **{pct_like:.1f}%** dei giorni "
                        f"arriva vicino a questo massimo."
                    )
            st.caption(
                f"Escursione del {pk['swing_pct']:.0f}% Pnom in giornata, "
                f"{pk['n_cycles']} ciclo/i — il massimo osservato nel periodo."
                + ctx +
                " ⚠️ Un singolo giorno record non descrive il funzionamento normale: "
                "guarda la mediana."
            )
            fig = charts.peak_day_profile(pk, reactor)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

        st.info(
            f"**Limiti di modulazione di {reactor}** — rampa max "
            f"{ml['max_ramp_rate_pct_min']:.2f}% Pnom/min · profondità fino a −{ml['max_depth_pct']:.0f}% · "
            f"al più {ml['max_cycles_day']} cicli/giorno · "
            + (f"~{ml['median_gap_h']:.0f} h di stabilità tra manovre · "
               if pd.notna(ml['median_gap_h']) else "")
            + f"a piena potenza il {ml['pct_baseload']:.0f}% del tempo."
        )

    # --- VINCOLI FISICI (xeno) ---
    with tabs[1]:
        st.caption(
            "Cosa limita davvero la modulazione. Lo **xeno-135** (prodotto di fissione "
            "che assorbe neutroni) si accumula quando abbassi la potenza e raggiunge il "
            "picco 6–9 ore dopo: penalizza le riduzioni **profonde e prolungate**. "
            "Se invece il rientro è rapido, lo xeno non fa in tempo ad accumularsi — "
            "e infatti nei dati la maggior parte delle risalite è veloce."
        )
        rec = lf.xenon_recovery(h, threshold_pct=40)
        deep = lf.deep_modulations(h, threshold_pct=40)
        rb = lf.recovery_breakdown(rec)

        c1, c2, c3 = st.columns(3)
        c1.metric("Recupero mediano", f"{rb['median_h']:.0f} h" if rb else "—",
                  help="Tempo tra un ramp-down >40% e la successiva risalita")
        c2.metric("Max discese profonde/giorno",
                  f"{int(deep['n_deep_down'].max())}" if not deep.empty else "0",
                  help="Massimo di ramp-down >40% Pnom nello stesso giorno")
        c3.metric("Risalite entro 6 h", f"{rb['pct_under_6h']:.0f}%" if rb else "—",
                  help="Rientri rapidi, prima che lo xeno si accumuli")

        st.markdown("#### Quante discese profonde nello stesso giorno")
        st.caption(
            "È il dato più solido: la domanda ha **due** avvallamenti giornalieri "
            "(notte e mezzogiorno solare), ma il reattore ne segue quasi sempre **uno**."
        )
        fig = charts.deep_modulations_hist(deep)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Nel periodo non ci sono discese profonde (>40%) per questo reattore. "
                    "Prova un forte modulatore (Cattenom 2/3, Belleville 1) o un periodo più ampio.")

        st.markdown("#### Tempo di recupero dopo una discesa profonda")
        st.caption("La banda rossa è la finestra del picco di xeno (6–16 h).")
        fig = charts.xenon_recovery_hist(rec)
        if fig:
            st.plotly_chart(fig, use_container_width=True)

        if rb:
            st.info(
                f"**Come leggerlo** — {reactor}: risalita mediana in **{rb['median_h']:.0f} h**, "
                f"il **{rb['pct_under_6h']:.0f}%** entro 6 ore, il {rb['pct_6_16h']:.0f}% "
                f"nella finestra 6–16 h. Le risalite rapide sono la norma, quindi **non** "
                "si può dire che lo xeno impedisca di rientrare: il vincolo è sulle "
                "riduzioni profonde e prolungate. Il limite osservabile è un altro — "
                f"**massimo {int(deep['n_deep_down'].max()) if not deep.empty else 0} "
                "discese profonde in un giorno**, e quasi sempre una sola."
            )

    # --- PRODUZIONE & CF ---
    with tabs[2]:
        st.markdown("#### Produzione vs capacità disponibile (orario)")
        st.caption("Area blu = produzione · verde = disponibile · bande = manutenzione/guasto")
        st.plotly_chart(
            charts.hourly_prod_vs_avail(h, events, show_nominal=True),
            use_container_width=True,
        )
        cc = st.columns(3)
        cc[0].metric("CF su nominale", f"{kpi['cf_nominal']:.1f}%")
        cc[1].metric("CF su disponibile", f"{kpi['cf_available']:.1f}%",
                     help="Quanto produce quando è dichiarato disponibile")
        cc[2].metric("Fattore disponibilità", f"{kpi['availability_factor']:.1f}%")

        st.markdown("#### Capacity factor annuale")
        st.plotly_chart(charts.cf_annual(h), use_container_width=True)

    # --- INDISPONIBILITÀ ---
    with tabs[3]:
        if events.empty:
            st.info("Nessun evento di indisponibilità nel periodo.")
        else:
            planned = events[events["type"] == "planned_maintenance"]
            forced = events[events["type"] == "forced_unavailability"]
            c1, c2, c3 = st.columns(3)
            c1.metric("Manutenzioni pianificate", len(planned))
            c2.metric("Guasti", len(forced))
            c3.metric("Durata media", f"{events['duration_h'].mean():.0f} h")

            # Nota sui vincoli ambientali (siccità/caldo) per questo reattore
            env_ev = events[env.is_environmental(events["reason"])] if "reason" in events.columns else events.iloc[0:0]
            cool, water = env.cooling_of(reactor)
            if not env_ev.empty:
                summer = env_ev["start"].dt.month.isin([6, 7, 8, 9]).mean() * 100
                st.warning(
                    f"🌡️ **{len(env_ev)} eventi per cause ambientali** "
                    f"(raffreddamento: {cool} — {water}) · "
                    f"{summer:.0f}% tra giugno e settembre. "
                    "Sono i vincoli da temperatura/portata del corpo idrico: "
                    "caldo e siccità. Dettaglio di flotta nel tab *Siccità* della vista aggregata."
                )
            elif cool == "mare":
                st.caption(f"🌊 Raffreddamento: {cool} ({water}) — nessun vincolo "
                           "ambientale registrato: gli impianti costieri sono immuni a siccità e magre.")

            st.markdown("#### Capacità disponibile nel tempo")
            st.caption("Gli outage si vedono come crolli dell'area verde. "
                       "La linea blu è la produzione effettiva.")
            st.plotly_chart(charts.availability_band(h, events), use_container_width=True)

            st.markdown("#### Indisponibilità per mese (pianificata vs guasti)")
            fig = charts.outage_monthly_bars(events, h)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            with st.expander("Dettaglio eventi"):
                cols = [c for c in ["start", "end", "duration_h", "type", "value", "reason"]
                        if c in events.columns]
                st.dataframe(events[cols].sort_values("start", ascending=False),
                             use_container_width=True, height=300)


# ─────────────────────────────────────────────────────────────────────────────
# Vista: Aggregata (flotta)
# ─────────────────────────────────────────────────────────────────────────────

def render_fleet(selected, hourly, nominal, date_from, date_to, unavail_all=None):
    if not selected:
        st.warning("Seleziona almeno un reattore.")
        return

    fleet = aggregate_fleet(hourly, selected, date_from, date_to)
    if fleet.empty:
        st.warning("Nessun dato nel periodo per i reattori selezionati.")
        return

    kpi = fleet_kpis(fleet)
    st.subheader(f"🗺️ Flotta — {len(selected)} reattori")
    st.caption(
        f"Capacità installata ~{kpi['installed_MW']/1000:.1f} GW · "
        f"{kpi['hours']:,} ore · {date_from} → {date_to}"
    )

    # KPI flotta: modulazione simultanea (helper memory-light → niente crash)
    ml = lf.modulation_limits(fleet)
    simul = lf.simultaneous_modulating(hourly, selected, date_from, date_to)
    max_simul = int(simul.max()) if len(simul) else 0
    mean_simul = float(simul.mean()) if len(simul) else 0
    # quota di tempo in cui almeno metà dei reattori modula insieme
    half = len(selected) / 2
    pct_high_simul = float((simul >= half).mean() * 100) if len(simul) else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Capacità installata", f"{kpi['installed_MW']/1000:.1f} GW")
    c2.metric("Max modulanti insieme", f"{max_simul}/{len(selected)}",
              help="Picco di reattori simultaneamente in load-following")
    c3.metric("In media modulano", f"{mean_simul:.0f}")
    c4.metric("CF flotta", f"{kpi['cf_nominal']:.1f}%")
    c5.metric("Energia", f"{kpi['energy_produced_TWh']:.1f} TWh")

    st.divider()
    tabs = st.tabs(["🔁 Modulazione flotta", "📐 Capacità di modulazione",
                    "🏭 Confronto per palier", "🌡️ Siccità & vincoli ambientali",
                    "📊 Reattori & anagrafica"])

    # Calcolo per-reattore UNA volta sola (condiviso da palier e tabella)
    as_of = pd.Timestamp(date_to).year
    enriched = enrich_reactor_list(selected, _metadata_cached(), as_of=as_of)
    einfo = {r["reactor"]: r for _, r in enriched.iterrows()}
    per_reactor = {}
    for r in selected:
        h = slice_period(hourly[r], date_from, date_to)
        if h.empty:
            continue
        per_reactor[r] = {"kpi": compute_kpis(h), "ml": lf.modulation_limits(h),
                          "meta": einfo.get(r, {})}

    # --- MODULAZIONE FLOTTA (focus) ---
    with tabs[0]:
        st.markdown("#### Quanti reattori modulano contemporaneamente")
        st.caption(
            f"Su {len(selected)} reattori, al più **{max_simul}** hanno modulato "
            f"nella stessa ora; in media **{mean_simul:.0f}**. "
            f"Almeno metà del parco modula insieme solo il **{pct_high_simul:.0f}%** del tempo."
        )
        fig = charts.fleet_reactors_modulating(hourly, selected, date_from, date_to, "D")
        if fig:
            st.plotly_chart(fig, use_container_width=True)

        # REALITY CHECK: il picco non basta, conta quanto è raro
        ss = lf.simultaneity_stats(simul, len(selected))
        if ss:
            st.markdown("#### 🔍 Reality check: il picco non è la normalità")
            st.caption(
                "Un singolo giorno favorevole (domenica di primavera, molto solare, "
                "domanda bassa) mostra molti reattori che modulano insieme. Ma su "
                "tutto il periodo la situazione tipica è un'altra."
            )
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Picco (max)", f"{ss['max']}/{ss['n_reactors']}")
            r2.metric("Situazione tipica (mediana)", f"{ss['median']:.0f}/{ss['n_reactors']}")
            r3.metric("Ore con ≥¼ del parco", f"{ss['pct_hours_over_quarter']:.1f}%")
            r4.metric("Ore con ≥½ del parco", f"{ss['pct_hours_over_half']:.1f}%")
            st.caption(
                f"Il 99° percentile è {ss['p99']:.0f} reattori: anche nelle ore migliori "
                f"si resta lontani dal picco assoluto. In media modulano {ss['mean']:.0f} "
                f"reattori su {ss['n_reactors']}."
            )
            st.divider()

        st.markdown("#### Distribuzione: per quante ore N reattori modulano insieme")
        st.caption("Il picco a sinistra mostra che nella maggior parte delle ore modulano "
                   "pochi reattori: la flessibilità simultanea del parco ha un tetto.")
        fig = charts.fleet_simultaneous_hist(hourly, selected, date_from, date_to)
        if fig:
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Quante discese profonde fa un reattore nello stesso giorno")
        st.caption(
            "La domanda elettrica ha due avvallamenti al giorno (notte e mezzogiorno "
            "solare), ma i reattori ne seguono sistematicamente uno solo."
        )
        dist = lf.deep_modulations_fleet(hourly, selected, date_from, date_to)
        fig = charts.deep_modulations_fleet_hist(dist)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
            if len(dist):
                tot = dist.sum(); one = dist.get(1, 0)
                st.caption(
                    f"**{one/tot*100:.0f}%** dei giorni con una modulazione profonda "
                    f"ne ha **una sola**; massimo osservato: **{int(dist.index.max())}**."
                )

        # Riquadro data-driven: i limiti di flotta, senza editorializzare
        gw_inst = kpi["installed_MW"] / 1000
        gw_flex = max_simul / len(selected) * gw_inst if len(selected) else 0
        st.info(
            f"**Limiti di modulazione della flotta (osservati nel periodo)**  \n"
            f"• Reattori manovrabili insieme: max **{max_simul}/{len(selected)}**, "
            f"in media {mean_simul:.0f}  \n"
            f"• Flessibilità simultanea di picco: ~**{gw_flex:.0f} GW** su {gw_inst:.0f} GW installati  \n"
            f"• Rampa aggregata massima: **{ml['max_ramp_rate_pct_min']:.2f}%** dell'installato/min  \n"
            f"• Tempo a piena potenza (baseload): **{ml['pct_baseload']:.0f}%**  \n"
            f"• Metà parco modula insieme solo il **{pct_high_simul:.0f}%** delle ore"
        )
        st.caption(
            "💡 Perché servono *tanti* reattori e non pochi: la modulazione fine "
            "emerge dalla somma di molte piccole manovre sfalsate. Con pochi reattori "
            "la curva sarebbe 'a gradoni', e ognuno avrebbe bisogno di tempi di recupero "
            "(xeno) tra le manovre — vedi il tab Vincoli fisici del singolo reattore. "
            "Seleziona 4 reattori nella sidebar per vedere quanto si riduce la flessibilità."
        )

    # --- CAPACITÀ DI MODULAZIONE (tre scale) ---
    with tabs[1]:
        st.caption(
            "La domanda chiave: **quanto può modulare il parco?** Ma \"quanto\" ha tre "
            "risposte diverse a seconda della scala temporale. Ore con dati mancanti "
            "sono escluse per non falsare i numeri."
        )
        cap = lf.fleet_modulation_capacity(hourly, selected, date_from, date_to)
        if not cap:
            st.info("Dati insufficienti nel periodo selezionato.")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Sostenibile (ogni giorno)", f"{cap['sustained_GW']:.1f} GW",
                      help=f"Escursione giornaliera mediana. Range abituale "
                           f"{cap['sustained_q25_GW']:.1f}–{cap['sustained_q75_GW']:.1f} GW. "
                           "È il livello che la flotta regge in continuo.")
            c2.metric("Picco assoluto (una tantum)", f"{cap['peak_swing_GW']:.1f} GW",
                      help=f"Escursione intra-giornaliera massima osservata "
                           f"(99°p: {cap['peak_swing_p99_GW']:.1f} GW). Eccezionale, non ripetibile.")
            c3.metric("Stagionale (su mesi)", f"{cap['seasonal_GW']:.1f} GW",
                      help="Differenza tra il mese più alto e più basso: modulazione lenta, "
                           "guidata soprattutto dai fermi ricarica.")

            st.markdown("#### I tre livelli di modulazione a confronto")
            fig = charts.modulation_capacity_bars(cap)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            st.markdown("#### Distribuzione delle escursioni giornaliere")
            st.caption("Quasi tutti i giorni la flotta modula poco; i giorni da picco sono la "
                       "coda destra, rara. La distanza tra mediana e picco è il margine "
                       "non sostenibile.")
            fig = charts.daily_swing_distribution(cap)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            ratio = cap["sustained_GW"] / cap["peak_swing_GW"] * 100 if cap["peak_swing_GW"] else 0
            st.info(
                f"**In sintesi (su {cap['installed_GW']:.0f} GW installati)**  \n"
                f"• Modulazione **sostenibile** giorno dopo giorno: **~{cap['sustained_GW']:.1f} GW** "
                f"({cap['sustained_GW']/cap['installed_GW']*100:.0f}% dell'installato), "
                f"fino a ~{cap['week_best_GW']:.1f} GW/giorno nelle settimane più intense  \n"
                f"• **Picco** assoluto in un giorno: **~{cap['peak_swing_GW']:.1f} GW** "
                f"({cap['peak_swing_GW']/cap['installed_GW']*100:.0f}%), ma una tantum  \n"
                f"• Rampa oraria aggregata: fino a **{abs(cap['ramp_down_GW_h']):.1f} GW/h** in discesa  \n\n"
                f"La modulazione *affidabile e continua* è solo il **~{ratio:.0f}% del picco massimo**: "
                "il parco può dare una spallata forte un giorno, ma non ripeterla ogni giorno "
                "(xeno + non tutti i reattori possono ciclare insieme)."
            )

    # --- CONFRONTO PER PALIER (blocco) ---
    with tabs[2]:
        st.caption("Ragionamento per **blocco di palier**: ogni generazione di progetto "
                   "confrontata come gruppo. I numeri sopra ogni barra sono le medie di gruppo.")
        # aggrega per palier dai calcoli già fatti
        prows = []
        for r, d in per_reactor.items():
            m = d["meta"]
            if not m.get("matched"):
                continue
            prows.append({
                "palier": m["palier"], "net_MW": m["net_MW"],
                "cf": d["kpi"]["cf_nominal"], "ramp_max": d["ml"]["max_ramp_rate_pct_min"],
                "depth": d["ml"]["max_depth_pct"], "cycles": d["ml"]["max_cycles_day"],
                "baseload": d["ml"]["pct_baseload"],
            })
        if not prows:
            st.info("Anagrafica non disponibile per i reattori selezionati.")
        else:
            pdf = pd.DataFrame(prows)
            pal = pdf.groupby("palier").agg(
                n_reactors=("cf", "size"), total_GW=("net_MW", lambda x: x.sum() / 1000),
                mean_cf=("cf", "mean"), mean_ramp_max=("ramp_max", "mean"),
                mean_depth=("depth", "mean"), max_cycles=("cycles", "max"),
                mean_baseload=("baseload", "mean"),
            ).reset_index()

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Capacity factor medio per palier**")
                fig = charts.palier_block_comparison(pal, "mean_cf", "CF medio (%)")
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
            with c2:
                st.markdown("**Rampa massima media per palier**")
                fig = charts.palier_block_comparison(pal, "mean_ramp_max", "Rampa max media (%/min)")
                if fig:
                    st.plotly_chart(fig, use_container_width=True)

            st.markdown("#### Tabella per palier")
            show = pal.copy()
            show.columns = ["Palier", "N reattori", "GW totali", "CF medio %",
                            "Rampa max media %/min", "Profondità media %",
                            "Max cicli/gg", "Baseload medio %"]
            for c in show.columns[2:]:
                show[c] = show[c].round(1)
            st.dataframe(show, use_container_width=True, hide_index=True)
            st.caption("Palier ordinati per generazione: CP0→CP1→CP2 (900 MW), "
                       "P4→P'4 (1300 MW), N4 (1450 MW), EPR (1600 MW).")

    # --- SICCITÀ & VINCOLI AMBIENTALI ---
    with tabs[3]:
        st.caption(
            "Indisponibilità dovute a **cause ambientali**: temperatura e portata "
            "dei fiumi, ondate di calore, siccità. I dati non hanno un'etichetta "
            "esplicita \"siccità\": si usa la categoria *Environmental issues*, "
            "che però mostra entrambe le firme attese (picco estivo e soli "
            "reattori fluviali)."
        )
        ev_env = env.environmental_events(unavail_all, nominal, date_from, date_to)
        ev_env = ev_env[ev_env["reactor"].isin(selected)] if not ev_env.empty else ev_env
        if ev_env.empty:
            st.info("Nessun evento ambientale per i reattori/periodo selezionati.")
        else:
            prod_TWh = kpi.get("energy_produced_TWh")
            es = env.environmental_summary(ev_env, prod_TWh)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Energia persa", f"{es['lost_GWh']:.0f} GWh",
                      help="(nominale − capacità disponibile) × durata dell'evento")
            c2.metric("Quota su produzione",
                      f"{es['pct_of_production']:.2f}%" if "pct_of_production" in es else "—")
            c3.metric("Eventi in estate (giu–set)", f"{es['pct_summer']:.0f}%",
                      help="La firma stagionale di caldo e siccità")
            c4.metric("Su impianti fluviali", f"{es['pct_river']:.0f}%",
                      help="I costieri (mare) sono praticamente immuni")

            st.markdown("#### Stagionalità: la firma estiva")
            fig = charts.env_seasonality(ev_env)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            st.markdown("#### Chi paga il conto: fiume vs mare")
            st.caption("I siti raffreddati da fiumi soffrono i limiti di temperatura "
                       "allo scarico e le magre; quelli sul mare no.")
            fig = charts.env_by_cooling(ev_env)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            st.info(
                f"**In sintesi** — {es['n_events']} eventi ambientali su "
                f"{es['n_reactors']} reattori, **{es['lost_GWh']:.0f} GWh** persi"
                + (f" (**{es['pct_of_production']:.2f}%** della produzione del periodo)"
                   if "pct_of_production" in es else "")
                + f". Anno peggiore: **{es['worst_year']}** ({es['worst_year_GWh']:.0f} GWh). "
                f"Il {es['pct_summer']:.0f}% degli eventi cade tra giugno e settembre e il "
                f"{es['pct_river']:.0f}% riguarda impianti fluviali o d'estuario: è il "
                "profilo tipico dei vincoli da caldo e magra dei fiumi, non di guasti casuali."
            )
            with st.expander("Dettaglio eventi ambientali"):
                show = ev_env[["reactor", "water", "start", "end", "duration_h", "lost_GWh"]].copy()
                show.columns = ["Reattore", "Corpo idrico", "Inizio", "Fine", "Ore", "GWh persi"]
                show["Ore"] = show["Ore"].round(0); show["GWh persi"] = show["GWh persi"].round(1)
                st.dataframe(show.sort_values("Inizio", ascending=False),
                             use_container_width=True, height=300, hide_index=True)

    # --- REATTORI & ANAGRAFICA ---
    with tabs[4]:
        st.markdown("#### Anagrafica: età e vita operativa (colore = palier)")
        fig = charts.fleet_timeline(enriched, as_of=as_of)
        if fig:
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Riepilogo per reattore")
        rows = []
        for r, d in per_reactor.items():
            e = d["meta"]
            rows.append({
                "Reattore": r,
                "Palier": e.get("palier", "—") if e.get("matched") else "—",
                "Anno": int(e["commissioning_year"]) if e.get("matched") and pd.notna(e.get("commissioning_year")) else None,
                "CF %": round(d["kpi"]["cf_nominal"], 1),
                "Rampa max %/min": round(d["ml"]["max_ramp_rate_pct_min"], 2),
                "Profondità %": round(d["ml"]["max_depth_pct"], 0),
                "Max cicli/gg": d["ml"]["max_cycles_day"],
                "Baseload %": round(d["ml"]["pct_baseload"], 0),
            })
        if rows:
            summary = pd.DataFrame(rows).sort_values("Anno")
            st.dataframe(
                _style_gradient(summary, subset=["CF %"], vmin=0, vmax=100),
                use_container_width=True, height=440, hide_index=True,
            )
            st.download_button("⬇️ Scarica CSV", summary.to_csv(index=False).encode(),
                               file_name="fleet_modulation.csv", mime="text/csv")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    prod, unavail, hourly, nominal, errors = sidebar_controls()

    if not hourly:
        st.title("⚛️ Nuclear Fleet Analyzer")
        st.markdown(
            "Metti lo **ZIP** dei CSV nel repo (root o `data/`) e l'app lo carica "
            "**da sola** — nessun upload manuale.\n\n"
            "L'app misura **quanto e quanto spesso il nucleare modula**: limiti di "
            "rampa, profondità, cicli/giorno e tempi di recupero per singolo "
            "reattore, e quanti reattori possono modulare insieme a livello di flotta "
            "— per confrontare la flessibilità del nucleare con quella del gas."
        )
        return

    if errors:
        st.sidebar.warning(f"{len(errors)} file con errori")
        with st.sidebar.expander("Dettagli errori"):
            for e in errors[:20]:
                st.text(e)

    mode, selected, date_from, date_to, reactors_sorted = period_and_reactor_controls(hourly, nominal)
    if date_from is None:
        st.warning("Nessun dato disponibile.")
        return

    if mode == "Reattore singolo":
        render_main_map(reactors_sorted, selected[0])
        render_single(selected[0], hourly, unavail, date_from, date_to)
    else:
        render_fleet(selected, hourly, nominal, date_from, date_to, unavail)


if __name__ == "__main__":
    main()
