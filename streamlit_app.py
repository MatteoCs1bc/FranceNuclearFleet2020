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


@st.cache_data(show_spinner=False)
def _metadata_cached():
    return load_metadata()

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


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar: caricamento + filtri
# ─────────────────────────────────────────────────────────────────────────────

def sidebar_controls():
    st.sidebar.title("⚛️ Fleet Analyzer")

    st.sidebar.subheader("📂 Sorgente dati")
    source = st.sidebar.radio(
        "Da dove leggo i CSV?",
        ["Upload ZIP", "Cartella locale ./data"],
        help="In locale puoi mettere i CSV in ./data ed evitare l'upload ogni volta.",
    )

    prod = unavail = hourly = nominal = errors = None

    if source == "Upload ZIP":
        zf = st.sidebar.file_uploader("ZIP con i CSV", type=["zip"])
        if zf is not None:
            with st.spinner("Parsing dei CSV…"):
                prod, unavail, hourly, nominal, errors = _load_zip_cached(zf.read())
    else:
        folder = st.sidebar.text_input("Percorso cartella", value="data")
        if Path(folder).exists() and any(Path(folder).glob("*.csv")):
            with st.spinner("Parsing dei CSV…"):
                prod, unavail, hourly, nominal, errors = _load_folder_cached(folder)
        else:
            st.sidebar.info("Metti i CSV in questa cartella e aggiorna.")

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

    tabs = st.tabs(["⏱️ Orario", "⚡ Capacity Factor", "🔀 Ramp", "🔧 Indisponibilità"])

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

    # --- CAPACITY FACTOR ---
    with tabs[1]:
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
            monthly[["CF nom %", "CF disp %"]].style.background_gradient(
                cmap="RdYlGn", vmin=0, vmax=100),
            use_container_width=True, height=320,
        )

    # --- RAMP ---
    with tabs[2]:
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
    with tabs[3]:
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

    tabs = st.tabs(["⏱️ Orario aggregato", "📊 Confronto reattori",
                    "🔀 Ramp flotta", "🏭 Modulazione & Anagrafica"])

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

    # --- CONFRONTO REATTORI ---
    with tabs[1]:
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
                summary.style.background_gradient(
                    subset=["CF nom %", "CF disp %", "Disp. %"],
                    cmap="RdYlGn", vmin=0, vmax=100),
                use_container_width=True, height=400, hide_index=True,
            )
            st.download_button(
                "⬇️ Scarica riepilogo CSV",
                summary.to_csv(index=False).encode(),
                file_name="fleet_summary.csv", mime="text/csv",
            )

    # --- RAMP FLOTTA ---
    with tabs[2]:
        st.markdown("#### Distribuzione ramp aggregati")
        st.plotly_chart(charts.ramp_distribution(fleet), use_container_width=True)
        st.markdown("#### Ramp medio per ora del giorno (flotta)")
        st.plotly_chart(charts.ramp_by_hour(fleet), use_container_width=True)

    # --- MODULAZIONE & ANAGRAFICA ---
    with tabs[3]:
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
                    mod, enriched, "swing_pct", "Swing p95−p5 (% Pnom)")
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
                "years_operation", "cf_nominal", "ramp_rate_pct", "swing_pct", "n_big_ramps",
            ]].copy()
            show.columns = ["Reattore", "Palier", "MW netti", "Accensione",
                            "Anni", "CF %", "Modul. %Pnom/h", "Swing %", "N ramp>5%"]
            for c in ["CF %", "Modul. %Pnom/h", "Swing %"]:
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
            "Carica lo **ZIP** dei CSV (o punta a `./data`) dalla sidebar per iniziare.\n\n"
            "L'app ricostruisce la **curva di capacità disponibile** dagli eventi di "
            "indisponibilità e la confronta con la produzione oraria, calcolando "
            "capacity factor, ramp up/down e analisi degli outage — sia per singolo "
            "reattore che in forma aggregata sulla flotta."
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
