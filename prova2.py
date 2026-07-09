"""
Nuclear Fleet Analyzer — Analisi della modulazione del parco nucleare francese
Capacity factor, load-following e limiti di modulazione (reattore singolo e flotta).

Sviluppato da Matteo De Piccoli — Ci Sarà un Bel Clima (https://unbelclima.it/)

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
    #page_icon="⚛️",
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
    elif kind == "folder":
        try:
            with st.spinner("Carico i CSV…"):
                prod, unavail, hourly, nominal, errors = _load_folder_cached(str(path))
        except Exception as exc:  # noqa: BLE001
            load_error = f"Errore leggendo i CSV: {exc}"

    n_react = len(hourly) if hourly else 0

    # Esiti possibili:
    if n_react > 0:
        st.sidebar.success(
            f"📦 `{path.name if kind=='zip' else path}` · **{n_react} reattori**"
        )
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
        chosen = st.sidebar.selectbox("Reattore", reactors_sorted, format_func=label)
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
        return mode, selected, None, None
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
    return mode, selected, date_from, date_to


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
    tabs = st.tabs(["🔁 Modulazione", "📉 Produzione & CF", "🔧 Indisponibilità"])

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
            st.caption(
                f"Escursione del {pk['swing_pct']:.0f}% Pnom in giornata, "
                f"{pk['n_cycles']} ciclo/i. È il massimo che questo reattore ha modulato "
                "restando in marcia nel periodo — il suo limite pratico osservato."
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

    # --- PRODUZIONE & CF ---
    with tabs[1]:
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
    with tabs[2]:
        if events.empty:
            st.info("Nessun evento di indisponibilità nel periodo.")
        else:
            planned = events[events["type"] == "planned_maintenance"]
            forced = events[events["type"] == "forced_unavailability"]
            c1, c2, c3 = st.columns(3)
            c1.metric("Manutenzioni pianificate", len(planned))
            c2.metric("Guasti", len(forced))
            c3.metric("Durata media", f"{events['duration_h'].mean():.0f} h")

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

def render_fleet(selected, hourly, nominal, date_from, date_to):
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
    tabs = st.tabs(["🔁 Modulazione flotta", "🏭 Confronto per palier",
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

        st.markdown("#### Distribuzione: per quante ore N reattori modulano insieme")
        st.caption("Il picco a sinistra mostra che nella maggior parte delle ore modulano "
                   "pochi reattori: la flessibilità simultanea del parco ha un tetto.")
        fig = charts.fleet_simultaneous_hist(hourly, selected, date_from, date_to)
        if fig:
            st.plotly_chart(fig, use_container_width=True)

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

    # --- CONFRONTO PER PALIER (blocco) ---
    with tabs[1]:
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

    # --- REATTORI & ANAGRAFICA ---
    with tabs[2]:
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

    mode, selected, date_from, date_to = period_and_reactor_controls(hourly, nominal)
    if date_from is None:
        st.warning("Nessun dato disponibile.")
        return

    if mode == "Reattore singolo":
        render_single(selected[0], hourly, unavail, date_from, date_to)
    else:
        render_fleet(selected, hourly, nominal, date_from, date_to)


if __name__ == "__main__":
    main()
