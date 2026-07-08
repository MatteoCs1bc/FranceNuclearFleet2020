"""
streamlit_app.py — Nuclear Fleet Analyzer
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
    reactor_modulation_metrics,
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

    # Pannello diagnostico (sempre disponibile)
    with st.sidebar.expander("🔎 Diagnostica dati", expanded=(n_react == 0)):
        st.caption(f"Cartella app: `{diag['cartella_app']}`")
        st.caption(f"`data/` esiste: {diag['data_esiste']}")
        st.write("**File nella root del repo:**")
        st.write(diag["contenuto_root"] or "—")
        if diag["data_esiste"]:
            st.write("**File in `data/`:**")
            st.write(diag["contenuto_data"] or "—")
        st.write("**ZIP trovati:**")
        st.write(diag["zip_trovati"] or "nessuno")

        # Ispezione del contenuto dello ZIP col loader ATTUALE
        if kind == "zip" and n_react == 0 and diag["zip_trovati"]:
            st.divider()
            st.write("**Dentro lo ZIP (riconoscimento loader attuale):**")
            try:
                import zipfile
                from src.loader import get_file_type, extract_reactor_name
                with zipfile.ZipFile(diag["zip_trovati"][0]) as zf:
                    names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                st.caption(f"CSV nello ZIP: {len(names)}")
                types = {}
                for n in names:
                    t = get_file_type(n)
                    types[t] = types.get(t, 0) + 1
                st.write("Tipi rilevati:", types)
                st.caption("Esempi (nome → tipo / reattore):")
                for n in names[:4]:
                    base = Path(n).name
                    st.text(f"{base[:38]}…\n  → {get_file_type(n)} / {extract_reactor_name(n)}")
                if types.get("unknown", 0) == len(names) and names:
                    st.error(
                        "Tutti 'unknown' → il `src/loader.py` sul server è la "
                        "versione VECCHIA. Ricarica il loader aggiornato."
                    )
            except Exception as exc:  # noqa: BLE001
                st.caption(f"Impossibile ispezionare lo ZIP: {exc}")

    # 2) Override: caricare uno ZIP al volo
    with st.sidebar.expander("📂 Carica uno ZIP manualmente", expanded=(n_react == 0)):
        zf = st.file_uploader("ZIP con i CSV", type=["zip"], key="override_zip")
        if zf is not None:
            with st.spinner("Parsing dello ZIP caricato…"):
                prod, unavail, hourly, nominal, errors = _load_zip_cached(zf.read())
            if hourly:
                st.success(f"Caricati {len(hourly)} reattori dal file.")
            else:
                st.error("0 reattori: nomi file non riconosciuti nello ZIP.")

    return prod, unavail, hourly, nominal, errors


def period_and_reactor_controls(hourly: dict, nominal: dict):
    reactors = sorted(hourly.keys())
    st.sidebar.divider()
    st.sidebar.subheader("🎛️ Selezione")

    mode = st.sidebar.radio("Modalità analisi",
                            ["Reattore singolo", "Aggregata (flotta)"])

    if mode == "Reattore singolo":
        selected = [st.sidebar.selectbox("Reattore", reactors)]
    else:
        default = reactors[: min(10, len(reactors))]
        selected = st.sidebar.multiselect("Reattori", reactors, default=default)

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

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("CF su nominale", f"{kpi['cf_nominal']:.1f}%")
    c2.metric("CF su disponibile", f"{kpi['cf_available']:.1f}%",
              help="Quanto produce quando è dichiarato disponibile (load factor)")
    c3.metric("Fattore disponibilità", f"{kpi['availability_factor']:.1f}%",
              help="Capacità disponibile / capacità nominale nel periodo")
    c4.metric("Max Ramp Up", f"+{kpi['max_ramp_up']:.0f} MW/h")
    c5.metric("Max Ramp Down", f"{kpi['max_ramp_down']:.0f} MW/h")

    st.divider()

    tabs = st.tabs(["⏱️ Orario", "🔁 Load Following", "⚡ Capacity Factor",
                    "🔀 Ramp", "🔧 Indisponibilità"])

    # --- ORARIO (centrale) ---
    with tabs[0]:
        st.markdown("#### Produzione vs Capacità Disponibile (orario)")
        st.caption(
            "Area blu = produzione · linea verde = capacità disponibile "
            "ricostruita dagli eventi · bande arancio/rosso = manutenzione/guasto"
        )
        st.plotly_chart(
            charts.hourly_prod_vs_avail(h, events, show_nominal=True),
            use_container_width=True,
        )
        st.markdown("#### Ramp orario")
        st.plotly_chart(charts.hourly_ramp(h), use_container_width=True)

        # Margine non utilizzato
        unused = h["unused_MW"].clip(lower=0)
        e1, e2, e3 = st.columns(3)
        e1.metric("Energia prodotta", f"{kpi['energy_produced_GWh']:.0f} GWh")
        e2.metric("Energia disponibile", f"{kpi['energy_available_GWh']:.0f} GWh")
        e3.metric("Margine medio non usato", f"{unused.mean():.0f} MW",
                  help="Capacità disponibile ma non prodotta (load-following)")

    # --- LOAD FOLLOWING ---
    with tabs[1]:
        s = lf.lf_summary(h)
        st.caption(
            "Quanto e quanto **spesso** il reattore modula *mentre è in marcia* "
            "(escludendo avvii/arresti per ricarica). Confronto coi benchmark di "
            "letteratura: EDF 2019 (20–100% Pnom, 2 cicli/giorno), "
            "Argonne/MIT 2018 (~20% Pnom/h), OECD/NEA 2011."
        )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Giorni di load-following", f"{s['pct_lf_days']:.0f}%",
                  help="% di giorni in cui il reattore, restando online, ha modulato ≥8% Pnom")
        c2.metric("Rampe online / mese", f"{s['online_ramps_per_month']:.0f}")
        c3.metric("Cicli per giorno di LF", f"{s['cycles_per_lf_day']:.1f}",
                  help="Letteratura EDF: fino a 2/giorno")
        c4.metric("Range operativo osservato",
                  f"{s['obs_range_low_pct']:.0f}–{s['obs_range_high_pct']:.0f}%",
                  help="EDF: modulazione tra 20% e 100% Pnom")

        # Ripartizione del tempo negli stati operativi
        st.markdown("#### Ripartizione del tempo per stato operativo")
        cc = st.columns(4)
        cc[0].metric("Piena potenza", f"{s['pct_full']:.0f}%")
        cc[1].metric("Load-following", f"{s['pct_load_follow']:.0f}%")
        cc[2].metric("Bassa/transitorio", f"{s['pct_low']:.1f}%")
        cc[3].metric("Fermo", f"{s['pct_off']:.1f}%")
        st.plotly_chart(charts.lf_state_stack(h), use_container_width=True)

        st.markdown("#### Firma giornaliera del load-following")
        st.caption(
            "Se il reattore segue la domanda, la produzione media cala in certe "
            "ore e le rampe hanno un pattern orario. In Francia oggi si vede spesso "
            "l'avvallamento di mezzogiorno indotto dal fotovoltaico."
        )
        st.plotly_chart(charts.lf_diurnal_profile(h), use_container_width=True)

        st.markdown("#### Quando modula: ora del giorno × mese")
        st.plotly_chart(charts.lf_diurnal_heatmap(h), use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Frequenza delle rampe (eventi online)")
            st.plotly_chart(charts.lf_ramp_frequency(h), use_container_width=True)
        with c2:
            st.markdown("#### Cicli di LF per mese")
            st.plotly_chart(charts.lf_cycles_per_month(h), use_container_width=True)

        st.markdown("#### Velocità delle rampe vs limite di letteratura")
        st.plotly_chart(charts.lf_ramp_rate_hist(h), use_container_width=True)

    # --- CAPACITY FACTOR ---
    with tabs[2]:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### CF annuale")
            st.plotly_chart(charts.cf_annual(h), use_container_width=True)
        with c2:
            st.markdown("#### CF per mese (stagionalità)")
            st.plotly_chart(charts.cf_monthly_box(h), use_container_width=True)

        st.markdown("#### Heatmap CF (Anno × Mese)")
        st.plotly_chart(charts.cf_heatmap(h), use_container_width=True)

        st.markdown("#### Tabella CF mensile")
        monthly = h.resample("ME").agg(
            prod=("production_MW_pos", "mean"),
            avail=("availability_MW", "mean"),
        )
        monthly["CF nom %"] = (monthly["prod"] / kpi["nominal_MW"] * 100).round(1)
        monthly["CF disp %"] = (monthly["prod"] / monthly["avail"] * 100).round(1)
        monthly.index = monthly.index.strftime("%Y-%m")
        st.dataframe(
            _style_gradient(monthly[["CF nom %", "CF disp %"]], vmin=0, vmax=100),
            use_container_width=True, height=320,
        )

    # --- RAMP ---
    with tabs[3]:
        st.markdown("#### Distribuzione ramp rates")
        st.plotly_chart(charts.ramp_distribution(h), use_container_width=True)

        ramp = h["ramp_MW_h"].dropna()
        ramp = ramp[ramp.abs() > 1]
        ups, downs = ramp[ramp > 0], ramp[ramp < 0]
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Ramp Up (MW/h)**")
            st.dataframe(pd.DataFrame({
                "Metrica": ["Max", "95°p", "75°p", "Mediana", "N ore"],
                "Valore": [f"+{ups.max():.0f}" if len(ups) else "—",
                           f"+{ups.quantile(.95):.0f}" if len(ups) else "—",
                           f"+{ups.quantile(.75):.0f}" if len(ups) else "—",
                           f"+{ups.median():.0f}" if len(ups) else "—",
                           f"{len(ups):,}"],
            }), hide_index=True, use_container_width=True)
        with c2:
            st.markdown("**Ramp Down (MW/h)**")
            st.dataframe(pd.DataFrame({
                "Metrica": ["Min", "5°p", "25°p", "Mediana", "N ore"],
                "Valore": [f"{downs.min():.0f}" if len(downs) else "—",
                           f"{downs.quantile(.05):.0f}" if len(downs) else "—",
                           f"{downs.quantile(.25):.0f}" if len(downs) else "—",
                           f"{downs.median():.0f}" if len(downs) else "—",
                           f"{len(downs):,}"],
            }), hide_index=True, use_container_width=True)

        st.markdown("#### Ramp medio per ora del giorno")
        st.plotly_chart(charts.ramp_by_hour(h), use_container_width=True)

    # --- INDISPONIBILITÀ ---
    with tabs[4]:
        if events.empty:
            st.info("Nessun evento di indisponibilità nel periodo.")
        else:
            planned = events[events["type"] == "planned_maintenance"]
            forced = events[events["type"] == "forced_unavailability"]
            full = events[events["value"] == 0]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Manutenzioni pianificate", len(planned))
            c2.metric("Guasti", len(forced))
            c3.metric("Outage completi (0 MW)", len(full))
            c4.metric("Durata media", f"{events['duration_h'].mean():.0f} h")

            st.markdown("#### Timeline eventi")
            fig = charts.outage_timeline(events)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### Stagionalità")
                fig = charts.outage_seasonality(events)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
            with c2:
                st.markdown("#### Durata per tipo")
                import plotly.express as px
                fig = px.histogram(
                    events, x="duration_h", color="type", nbins=40,
                    color_discrete_map={
                        "planned_maintenance": charts.COLORS["planned"],
                        "forced_unavailability": charts.COLORS["forced"],
                    },
                    labels={"duration_h": "Durata (h)", "type": "Tipo"},
                )
                fig.update_layout(height=300, margin=dict(t=10, b=30))
                st.plotly_chart(fig, use_container_width=True)

            st.markdown("#### Dettaglio eventi")
            cols = ["start", "end", "duration_h", "type", "value", "reason"]
            cols = [c for c in cols if c in events.columns]
            st.dataframe(
                events[cols].sort_values("start", ascending=False),
                use_container_width=True, height=320,
            )


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

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("CF su nominale", f"{kpi['cf_nominal']:.1f}%")
    c2.metric("CF su disponibile", f"{kpi['cf_available']:.1f}%")
    c3.metric("Fattore disponibilità", f"{kpi['availability_factor']:.1f}%")
    c4.metric("Energia prodotta", f"{kpi['energy_produced_TWh']:.1f} TWh")
    c5.metric("Picco flotta", f"{kpi['peak_prod_MW']/1000:.1f} GW")

    st.divider()

    tabs = st.tabs(["⏱️ Orario aggregato", "🔁 Load Following flotta",
                    "📊 Confronto reattori", "🔀 Ramp flotta",
                    "🏭 Modulazione & Anagrafica"])

    # --- ORARIO AGGREGATO ---
    with tabs[0]:
        st.markdown("#### Produzione vs Disponibilità aggregata (orario)")
        st.caption("Somma oraria di tutti i reattori selezionati")
        st.plotly_chart(
            charts.hourly_prod_vs_avail(fleet, None, show_nominal=True),
            use_container_width=True,
        )
        c1, c2, c3 = st.columns(3)
        gap = (fleet["availability_MW"] - fleet["production_MW_pos"]).clip(lower=0)
        c1.metric("Margine medio non usato", f"{gap.mean()/1000:.1f} GW",
                  help="Capacità disponibile ma non prodotta a livello flotta")
        c2.metric("Produzione minima", f"{kpi['min_prod_MW']/1000:.1f} GW")
        c3.metric("Range ramp", f"{kpi['max_ramp_down']:.0f} / +{kpi['max_ramp_up']:.0f} MW/h")

    # --- LOAD FOLLOWING FLOTTA ---
    with tabs[1]:
        st.caption(
            "Load-following a livello di **flotta**: quanti reattori modulano "
            "insieme e con che struttura oraria. Benchmark: EDF 2019, "
            "Argonne/MIT 2018, OECD/NEA 2011."
        )
        s = lf.lf_summary(fleet)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Ore flotta in modulazione", f"{s['pct_load_follow']:.0f}%",
                  help="Quota di ore in cui la produzione aggregata è tra 20% e 92% dell'installato")
        c2.metric("Rampe online / mese", f"{s['online_ramps_per_month']:.0f}")
        c3.metric("Giorni di LF", f"{s['pct_lf_days']:.0f}%")
        c4.metric("Range aggregato osservato",
                  f"{s['obs_range_low_pct']:.0f}–{s['obs_range_high_pct']:.0f}%")

        st.markdown("#### Quanti reattori modulano contemporaneamente")
        fig = charts.fleet_reactors_modulating(hourly, selected, date_from, date_to, "D")
        if fig:
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Firma giornaliera aggregata")
        st.caption("La modulazione della flotta segue la curva di domanda netta "
                   "(domanda − solare/eolico): avvallamento di mezzogiorno da FV.")
        st.plotly_chart(charts.lf_diurnal_profile(fleet), use_container_width=True)

        st.markdown("#### Quando modula la flotta: ora × mese")
        st.plotly_chart(charts.lf_diurnal_heatmap(fleet), use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Ripartizione tempo per stato")
            st.plotly_chart(charts.lf_state_stack(fleet), use_container_width=True)
        with c2:
            st.markdown("#### Frequenza rampe aggregate")
            st.plotly_chart(charts.lf_ramp_frequency(fleet), use_container_width=True)

    # --- CONFRONTO REATTORI ---
    with tabs[2]:
        st.markdown("#### Ranking CF medio nel periodo")
        fig = charts.fleet_cf_ranking(hourly, selected, date_from, date_to)
        if fig:
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Heatmap CF (Reattore × Mese)")
        fig = charts.fleet_cf_heatmap(hourly, selected, date_from, date_to, "ME")
        if fig:
            st.plotly_chart(fig, use_container_width=True)

        # Tabella riepilogo
        st.markdown("#### Riepilogo per reattore")
        rows = []
        for r in selected:
            h = slice_period(hourly[r], date_from, date_to)
            if h.empty:
                continue
            k = compute_kpis(h)
            rows.append({
                "Reattore": r,
                "Nominale MW": round(k["nominal_MW"]),
                "CF nom %": round(k["cf_nominal"], 1),
                "CF disp %": round(k["cf_available"], 1),
                "Disp. %": round(k["availability_factor"], 1),
                "Outage h": k["outage_hours"],
                "Energia GWh": round(k["energy_produced_GWh"]),
            })
        if rows:
            summary = pd.DataFrame(rows).sort_values("CF nom %", ascending=False)
            st.dataframe(
                _style_gradient(summary,
                                subset=["CF nom %", "CF disp %", "Disp. %"],
                                vmin=0, vmax=100),
                use_container_width=True, height=400, hide_index=True,
            )
            st.download_button(
                "⬇️ Scarica riepilogo CSV",
                summary.to_csv(index=False).encode(),
                file_name="fleet_summary.csv", mime="text/csv",
            )

    # --- RAMP FLOTTA ---
    with tabs[3]:
        st.markdown("#### Distribuzione ramp aggregati")
        st.plotly_chart(charts.ramp_distribution(fleet), use_container_width=True)
        st.markdown("#### Ramp medio per ora del giorno (flotta)")
        st.plotly_chart(charts.ramp_by_hour(fleet), use_container_width=True)

    # --- MODULAZIONE & ANAGRAFICA ---
    with tabs[4]:
        meta_df = _metadata_cached()
        as_of = pd.Timestamp(date_to).year
        enriched = enrich_reactor_list(selected, meta_df, as_of=as_of)
        mod = reactor_modulation_metrics(hourly, selected, date_from, date_to)

        n_matched = int(enriched["matched"].sum())
        if n_matched < len(selected):
            missing = enriched[~enriched["matched"]]["reactor"].tolist()
            st.info(f"Anagrafica non trovata per {len(missing)} reattori: "
                    f"{', '.join(missing[:8])}{'…' if len(missing) > 8 else ''}. "
                    "Puoi correggere `data/reactors_metadata.csv`.")

        st.markdown("#### Potenziale di modulazione per palier")
        st.caption(
            "Velocità di modulazione = 95° percentile di |ramp| in % del nominale/ora. "
            "I palier più recenti (N4, EPR) e i 900 MW sono progettati per load-following più spinto."
        )
        merged = mod.merge(enriched[enriched["matched"]], on="reactor", how="inner")
        if not merged.empty:
            fig = charts.fleet_age_scatter(
                enriched, metric_df=mod,
                y_col="ramp_rate_pct",
                y_label="Velocità modulazione (% Pnom/h)",
            )
            if fig:
                st.plotly_chart(fig, use_container_width=True)

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Velocità modulazione per palier**")
                fig = charts.palier_modulation_box(
                    mod, enriched, "ramp_rate_pct", "% Pnom/h")
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
            with c2:
                st.markdown("**Escursione produzione per palier**")
                fig = charts.palier_modulation_box(
                    mod, enriched, "daily_swing_pct", "Escursione giornaliera (% Pnom)")
                if fig:
                    st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Anagrafica flotta — vita operativa")
        st.caption("Barra = anni di esercizio, colore = palier. Fessenheim risulta dismesso nel 2020.")
        fig = charts.fleet_timeline(enriched, as_of=as_of)
        if fig:
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Età vs Capacity Factor")
        st.caption("Un reattore più vecchio modula/produce diversamente? Dimensione = potenza netta.")
        fig = charts.fleet_age_scatter(
            enriched, metric_df=mod, y_col="cf_nominal", y_label="CF su nominale (%)")
        if fig:
            st.plotly_chart(fig, use_container_width=True)

        # Tabella anagrafica + modulazione
        if not merged.empty:
            st.markdown("#### Tabella anagrafica + modulazione")
            show = merged[[
                "reactor", "palier", "net_MW", "commissioning_year",
                "years_operation", "cf_nominal", "ramp_rate_pct", "daily_swing_pct", "n_big_ramps",
            ]].copy()
            show.columns = ["Reattore", "Palier", "MW netti", "Accensione",
                            "Anni", "CF %", "Modul. %Pnom/h", "Swing gg %", "N ramp>5%"]
            for c in ["CF %", "Modul. %Pnom/h", "Swing gg %"]:
                show[c] = show[c].round(1)
            st.dataframe(show.sort_values("Palier"), use_container_width=True,
                         height=380, hide_index=True)
            st.download_button(
                "⬇️ Scarica anagrafica+modulazione CSV",
                show.to_csv(index=False).encode(),
                file_name="fleet_modulation.csv", mime="text/csv")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    prod, unavail, hourly, nominal, errors = sidebar_controls()

    if not hourly:
        st.title("⚛️ Nuclear Fleet Analyzer")
        st.markdown(
            "Metti lo **ZIP** dei CSV nella cartella `data/` del repo e l'app lo "
            "carica **da sola all'avvio** — nessun upload manuale. In alternativa "
            "puoi caricarlo al volo dall'expander in sidebar.\n\n"
            "L'app ricostruisce la **curva di capacità disponibile** dagli eventi di "
            "indisponibilità e la confronta con la produzione oraria, calcolando "
            "capacity factor, ramp up/down e analisi degli outage — sia per singolo "
            "reattore che in forma aggregata sulla flotta, con anagrafica e "
            "potenziale di modulazione per palier."
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
