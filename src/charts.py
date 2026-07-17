"""
charts.py — Figure Plotly per l'app.
La vista oraria produzione↔availability è il grafico centrale.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

COLORS = {
    "production": "#2563EB",
    "availability": "#16A34A",
    "nominal": "#94A3B8",
    "ramp_up": "#EA580C",
    "ramp_down": "#9333EA",
    "planned": "#F59E0B",
    "forced": "#DC2626",
    "unused": "#CBD5E1",
}

EVENT_LABELS = {
    "planned_maintenance": "Manutenzione pianificata",
    "forced_unavailability": "Guasto / Forza Maggiore",
    "nominal": "Nominale",
}


# ─────────────────────────────────────────────────────────────────────────────
# VISTA ORARIA (centrale)
# ─────────────────────────────────────────────────────────────────────────────

def hourly_prod_vs_avail(
    hourly: pd.DataFrame,
    unavail_df: pd.DataFrame | None = None,
    title: str = "",
    show_nominal: bool = True,
) -> go.Figure:
    """
    Produzione oraria vs availability ricostruita.
      - area blu: produzione
      - linea verde: capacità disponibile (dagli eventi)
      - linea grigia tratteggiata: capacità nominale
      - bande colorate: eventi (arancio=planned, rosso=forced)
    """
    fig = go.Figure()

    # Bande eventi (dietro a tutto)
    if unavail_df is not None and not unavail_df.empty:
        x0, x1 = hourly.index.min(), hourly.index.max()
        for _, ev in unavail_df.iterrows():
            s = max(ev["start"], x0)
            e = min(ev["end"], x1)
            if s >= e:
                continue
            color = ("rgba(220,38,38,0.12)"
                     if ev["type"] == "forced_unavailability"
                     else "rgba(245,158,11,0.10)")
            fig.add_vrect(x0=s, x1=e, fillcolor=color, line_width=0, layer="below")

    # Nominale (come shape, così NON finisce in legenda)
    if show_nominal and "nominal_MW" in hourly and len(hourly):
        nominal = float(hourly["nominal_MW"].iloc[0])
        fig.add_shape(type="line", x0=hourly.index.min(), x1=hourly.index.max(),
                      y0=nominal, y1=nominal,
                      line=dict(color=COLORS["nominal"], width=1, dash="dash"))
        fig.add_annotation(x=hourly.index.min(), y=nominal,
                           text=f"Nominale {nominal:.0f} MW", showarrow=False,
                           yshift=8, xanchor="left",
                           font=dict(color=COLORS["nominal"], size=10))

    # Availability
    if "availability_MW" in hourly:
        fig.add_trace(go.Scatter(
            x=hourly.index, y=hourly["availability_MW"],
            name="Capacità disponibile",
            line=dict(color=COLORS["availability"], width=1.4),
            hovertemplate="Disponibile: %{y:.0f} MW<extra></extra>",
        ))

    # Produzione (area)
    fig.add_trace(go.Scatter(
        x=hourly.index, y=hourly["production_MW_pos"],
        name="Produzione", fill="tozeroy",
        line=dict(color=COLORS["production"], width=1.2),
        fillcolor="rgba(37,99,235,0.18)",
        hovertemplate="Produzione: %{y:.0f} MW<extra></extra>",
    ))

    fig.update_layout(
        title=title or None,
        yaxis_title="Potenza (MW)",
        hovermode="x unified",
        height=420,
        margin=dict(t=40 if title else 10, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    return fig


def hourly_ramp(hourly: pd.DataFrame, title: str = "") -> go.Figure:
    """Ramp orario (MW/h) come barre colorate up/down."""
    ramp = hourly["ramp_MW_h"]
    colors = np.where(ramp >= 0, COLORS["ramp_up"], COLORS["ramp_down"])
    fig = go.Figure(go.Bar(
        x=hourly.index, y=ramp, marker_color=colors,
        hovertemplate="%{y:+.0f} MW/h<extra></extra>",
    ))
    fig.update_layout(
        title=title or None,
        yaxis_title="Ramp (MW/h)",
        height=220, margin=dict(t=40 if title else 10, b=30),
        showlegend=False,
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# CAPACITY FACTOR
# ─────────────────────────────────────────────────────────────────────────────

def cf_annual(hourly: pd.DataFrame) -> go.Figure:
    """CF annuale (nominale vs disponibile) a barre affiancate."""
    g = hourly.groupby(hourly.index.year).agg(
        prod=("production_MW_pos", "sum"),
        avail=("availability_MW", "sum"),
        nom=("nominal_MW", "mean"),
        n=("production_MW_pos", "size"),
    )
    g["cf_nom"] = g["prod"] / (g["nom"] * g["n"]) * 100
    g["cf_avail"] = g["prod"] / g["avail"] * 100

    fig = go.Figure()
    fig.add_trace(go.Bar(x=g.index, y=g["cf_nom"], name="CF su nominale",
                         marker_color=COLORS["production"],
                         text=g["cf_nom"].round(1), textposition="outside"))
    fig.add_trace(go.Bar(x=g.index, y=g["cf_avail"], name="CF su disponibile",
                         marker_color=COLORS["availability"],
                         text=g["cf_avail"].round(1), textposition="outside"))
    fig.update_layout(barmode="group", yaxis_title="Capacity Factor (%)",
                      xaxis_title="Anno", height=340, margin=dict(t=10, b=30),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


def cf_heatmap(hourly: pd.DataFrame) -> go.Figure:
    """Heatmap CF su nominale, Anno × Mese."""
    daily = (hourly["production_MW_pos"].resample("D").mean()
             / hourly["nominal_MW"].iloc[0] * 100).reset_index()
    daily.columns = ["date", "cf"]
    daily["year"] = daily["date"].dt.year
    daily["month"] = daily["date"].dt.month

    piv = daily.pivot_table(index="year", columns="month", values="cf", aggfunc="mean")
    it_months = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
                 "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
    piv = piv.reindex(columns=range(1, 13))

    fig = px.imshow(
        piv.values,
        x=it_months, y=[str(y) for y in piv.index],
        color_continuous_scale=[[0, "#B91C1C"], [0.5, "#F59E0B"], [1, "#15803D"]],
        range_color=[0, 100], aspect="auto",
        labels=dict(color="CF %"),
    )
    fig.update_layout(height=max(220, len(piv) * 40), margin=dict(t=10, b=20))
    return fig


def cf_monthly_box(hourly: pd.DataFrame) -> go.Figure:
    """Boxplot CF giornaliero per mese (stagionalità)."""
    daily = (hourly["production_MW_pos"].resample("D").mean()
             / hourly["nominal_MW"].iloc[0] * 100).reset_index()
    daily.columns = ["date", "cf"]
    daily["month"] = daily["date"].dt.month
    it_months = {1: "Gen", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mag", 6: "Giu",
                 7: "Lug", 8: "Ago", 9: "Set", 10: "Ott", 11: "Nov", 12: "Dic"}
    fig = px.box(daily, x="month", y="cf",
                 color_discrete_sequence=[COLORS["production"]],
                 labels={"month": "Mese", "cf": "CF (%)"})
    fig.update_xaxes(tickvals=list(range(1, 13)), ticktext=list(it_months.values()))
    fig.update_layout(height=320, margin=dict(t=10, b=30))
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# RAMP
# ─────────────────────────────────────────────────────────────────────────────

def ramp_distribution(hourly: pd.DataFrame) -> go.Figure:
    """Istogramma overlay ramp up/down."""
    ramp = hourly["ramp_MW_h"].dropna()
    ramp = ramp[ramp.abs() > 1]
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=ramp[ramp > 0], nbinsx=60, name="Ramp Up",
                               marker_color=COLORS["ramp_up"], opacity=0.7))
    fig.add_trace(go.Histogram(x=ramp[ramp < 0], nbinsx=60, name="Ramp Down",
                               marker_color=COLORS["ramp_down"], opacity=0.7))
    fig.update_layout(barmode="overlay", xaxis_title="Ramp rate (MW/h)",
                      yaxis_title="Ore", height=320, margin=dict(t=10, b=30),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


def ramp_by_hour(hourly: pd.DataFrame) -> go.Figure:
    """Ramp medio up/down per ora del giorno."""
    df = hourly.copy()
    df["hour"] = df.index.hour
    agg = df.groupby("hour")["ramp_MW_h"].agg(
        up=lambda x: x[x > 0].mean(),
        down=lambda x: x[x < 0].mean(),
    ).reset_index()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=agg["hour"], y=agg["up"], name="Ramp Up medio",
                         marker_color=COLORS["ramp_up"]))
    fig.add_trace(go.Bar(x=agg["hour"], y=agg["down"], name="Ramp Down medio",
                         marker_color=COLORS["ramp_down"]))
    fig.update_layout(barmode="group", xaxis_title="Ora del giorno",
                      yaxis_title="MW/h", height=300, margin=dict(t=10, b=30),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# INDISPONIBILITÀ
# ─────────────────────────────────────────────────────────────────────────────

def outage_timeline(unavail_df: pd.DataFrame) -> go.Figure | None:
    """Gantt degli eventi."""
    if unavail_df is None or unavail_df.empty:
        return None
    df = unavail_df.copy()
    df["label"] = df["type"].map(EVENT_LABELS).fillna(df["type"])
    fig = px.timeline(
        df, x_start="start", x_end="end", y="id", color="label",
        color_discrete_map={
            EVENT_LABELS["planned_maintenance"]: COLORS["planned"],
            EVENT_LABELS["forced_unavailability"]: COLORS["forced"],
        },
        hover_data={"value": True, "duration_h": ":.0f"},
        labels={"id": "Evento", "value": "MW disp.", "duration_h": "Durata h"},
    )
    fig.update_yaxes(autorange="reversed", showticklabels=False)
    fig.update_layout(height=360, margin=dict(t=10, b=30),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


def outage_seasonality(unavail_df: pd.DataFrame) -> go.Figure | None:
    """Eventi per mese, per tipo."""
    if unavail_df is None or unavail_df.empty:
        return None
    df = unavail_df.copy()
    df["month"] = df["start"].dt.month
    df["label"] = df["type"].map(EVENT_LABELS).fillna(df["type"])
    g = df.groupby(["month", "label"]).size().reset_index(name="n")
    fig = px.bar(g, x="month", y="n", color="label",
                 color_discrete_map={
                     EVENT_LABELS["planned_maintenance"]: COLORS["planned"],
                     EVENT_LABELS["forced_unavailability"]: COLORS["forced"],
                 },
                 labels={"month": "Mese", "n": "N. eventi", "label": "Tipo"})
    fig.update_xaxes(tickvals=list(range(1, 13)),
                     ticktext=["Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
                               "Lug", "Ago", "Set", "Ott", "Nov", "Dic"])
    fig.update_layout(height=300, margin=dict(t=10, b=30),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# FLOTTA
# ─────────────────────────────────────────────────────────────────────────────

def fleet_cf_heatmap(hourly_by_reactor: dict, reactors: list[str],
                     date_from, date_to, freq: str = "ME") -> go.Figure | None:
    """Heatmap flotta: reattore × mese → CF nominale."""
    rows = []
    for r in reactors:
        if r not in hourly_by_reactor:
            continue
        h = hourly_by_reactor[r]
        h = h.loc[(h.index >= pd.Timestamp(date_from)) &
                  (h.index <= pd.Timestamp(date_to) + pd.Timedelta(days=1))]
        if h.empty:
            continue
        cf = (h["production_MW_pos"].resample(freq).mean()
              / h["nominal_MW"].iloc[0] * 100)
        cf.name = r
        rows.append(cf)
    if not rows:
        return None
    matrix = pd.concat(rows, axis=1).T
    matrix.columns = [str(c)[:7] for c in matrix.columns]
    fig = px.imshow(
        matrix.values, x=list(matrix.columns), y=list(matrix.index),
        color_continuous_scale=[[0, "#B91C1C"], [0.5, "#F59E0B"], [1, "#15803D"]],
        range_color=[0, 100], aspect="auto", labels=dict(color="CF %"),
    )
    fig.update_layout(height=max(300, len(matrix) * 20), margin=dict(t=10, b=30))
    return fig


def fleet_cf_ranking(hourly_by_reactor: dict, reactors: list[str],
                     date_from, date_to) -> go.Figure | None:
    """Barre orizzontali: CF medio per reattore nel periodo, ordinato."""
    data = []
    for r in reactors:
        if r not in hourly_by_reactor:
            continue
        h = hourly_by_reactor[r]
        h = h.loc[(h.index >= pd.Timestamp(date_from)) &
                  (h.index <= pd.Timestamp(date_to) + pd.Timedelta(days=1))]
        if h.empty:
            continue
        cf = h["production_MW_pos"].mean() / h["nominal_MW"].iloc[0] * 100
        data.append({"reactor": r, "cf": cf})
    if not data:
        return None
    df = pd.DataFrame(data).sort_values("cf")
    fig = px.bar(df, x="cf", y="reactor", orientation="h",
                 color="cf",
                 color_continuous_scale=[[0, "#B91C1C"], [0.5, "#F59E0B"], [1, "#15803D"]],
                 range_color=[0, 100],
                 labels={"cf": "CF medio (%)", "reactor": ""})
    fig.update_layout(height=max(300, len(df) * 22), margin=dict(t=10, b=30),
                      coloraxis_showscale=False)
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# ANAGRAFICA / MODULAZIONE
# ─────────────────────────────────────────────────────────────────────────────

from src.metadata import PALIER_COLORS, PALIER_ORDER  # noqa: E402


def fleet_age_scatter(enriched: pd.DataFrame, metric_df: pd.DataFrame | None = None,
                      y_col: str = "years_operation",
                      y_label: str = "Anni di esercizio") -> go.Figure | None:
    """
    Scatter flotta: x = anno accensione, y = metrica (età o, se fornito
    metric_df, una metrica calcolata come ramp/CF). Colore = palier,
    dimensione = potenza. Vista compatta e leggibile.
    """
    df = enriched[enriched["matched"]].copy()
    if df.empty:
        return None
    if metric_df is not None:
        df = df.merge(metric_df, on="reactor", how="left")

    fig = go.Figure()
    for palier in PALIER_ORDER:
        sub = df[df["palier"] == palier]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["commissioning_year"], y=sub[y_col],
            mode="markers", name=palier,
            marker=dict(
                size=sub["net_MW"] / 45,
                color=PALIER_COLORS.get(palier, "#888"),
                line=dict(width=1, color="white"),
                opacity=0.85,
            ),
            text=sub["reactor"],
            customdata=sub[["net_MW", "palier"]].values,
            hovertemplate="<b>%{text}</b><br>Accensione: %{x}<br>"
                          + y_label + ": %{y}<br>%{customdata[0]:.0f} MW · "
                          "%{customdata[1]}<extra></extra>",
        ))
    fig.update_layout(
        xaxis_title="Anno di accensione", yaxis_title=y_label,
        height=420, margin=dict(t=10, b=30),
        legend=dict(title="Palier", orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    return fig


def fleet_timeline(enriched: pd.DataFrame, as_of: int) -> go.Figure | None:
    """Timeline orizzontale: barra di vita operativa per reattore, per palier."""
    df = enriched[enriched["matched"]].copy()
    if df.empty:
        return None
    df["end_year"] = df["decommission_year"].fillna(as_of)
    # ordina per palier (generazione) poi per anno
    df["_po"] = df["palier"].map({p: i for i, p in enumerate(PALIER_ORDER)})
    df = df.sort_values(["_po", "commissioning_year"])

    fig = go.Figure()
    for palier in PALIER_ORDER:
        sub = df[df["palier"] == palier]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            base=sub["commissioning_year"],
            x=sub["end_year"] - sub["commissioning_year"],
            y=sub["reactor"], orientation="h",
            marker_color=PALIER_COLORS.get(palier, "#888"),
            name=palier,
            customdata=sub[["commissioning_year", "years_operation", "net_MW"]].values,
            hovertemplate="<b>%{y}</b><br>%{customdata[0]}–ora · "
                          "%{customdata[1]} anni · %{customdata[2]:.0f} MW<extra></extra>",
        ))
    fig.update_layout(
        barmode="stack", xaxis_title="Anno",
        height=max(320, len(df) * 16), margin=dict(t=10, b=30),
        legend=dict(title="Palier", orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_yaxes(autorange="reversed")
    return fig


def palier_modulation_box(metric_df: pd.DataFrame, enriched: pd.DataFrame,
                          value_col: str, value_label: str) -> go.Figure | None:
    """
    Boxplot di una metrica (es. ampiezza ramp, CF) raggruppata per palier,
    per confrontare la modulazione tra generazioni di reattori.
    """
    df = metric_df.merge(
        enriched[["reactor", "palier"]], on="reactor", how="inner"
    ).dropna(subset=[value_col, "palier"])
    if df.empty:
        return None
    order = [p for p in PALIER_ORDER if p in df["palier"].unique()]
    fig = px.box(df, x="palier", y=value_col, category_orders={"palier": order},
                 color="palier", color_discrete_map=PALIER_COLORS,
                 labels={"palier": "Palier", value_col: value_label})
    fig.update_layout(height=340, margin=dict(t=10, b=30), showlegend=False)
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# LOAD FOLLOWING
# ─────────────────────────────────────────────────────────────────────────────

from src import loadfollowing as _lf  # noqa: E402

STATE_COLORS = {
    "full": "#16A34A",         # verde: piena potenza
    "load_follow": "#F59E0B",  # arancio: modulazione
    "low": "#F97316",          # arancio scuro: bassa/transitorio
    "off": "#DC2626",          # rosso: fermo
}
STATE_LABELS = {
    "full": "Piena potenza (≥92%)",
    "load_follow": "Load-following (20–92%)",
    "low": "Bassa/transitorio (3–20%)",
    "off": "Fermo (<3%)",
}


def peak_day_profile(pk: dict, reactor: str = "") -> go.Figure | None:
    """Profilo orario del giorno di massima modulazione."""
    if not pk or "profile" not in pk:
        return None
    prof = pk["profile"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=prof["hour"], y=prof["prod_pct"], mode="lines+markers",
        line=dict(color=COLORS["production"], width=2.5),
        fill="tozeroy", fillcolor="rgba(37,99,235,0.15)",
        name="Produzione", hovertemplate="%{x}:00 → %{y:.0f}% Pnom<extra></extra>",
    ))
    fig.add_hline(y=100, line=dict(color=COLORS["nominal"], width=1, dash="dash"))
    fig.update_layout(
        xaxis_title="Ora del giorno", yaxis_title="Produzione (% Pnom)",
        yaxis_range=[0, 105], height=340, margin=dict(t=10, b=30),
        showlegend=False,
    )
    return fig


def palier_block_comparison(palier_df: pd.DataFrame, metric: str,
                            label: str, ascending: bool = False) -> go.Figure | None:
    """Barre per palier di una metrica aggregata (confronto tra generazioni)."""
    if palier_df.empty or metric not in palier_df:
        return None
    df = palier_df.sort_values(metric, ascending=ascending)
    fig = go.Figure(go.Bar(
        x=df["palier"], y=df[metric],
        marker_color=[PALIER_COLORS.get(p, "#888") for p in df["palier"]],
        text=df[metric].round(1), textposition="outside",
        customdata=df[["n_reactors"]].values,
        hovertemplate="%{x}: %{y:.1f}<br>%{customdata[0]} reattori<extra></extra>",
    ))
    fig.update_layout(xaxis_title="Palier", yaxis_title=label,
                      height=340, margin=dict(t=10, b=30),
                      xaxis=dict(categoryorder="array",
                                 categoryarray=[p for p in PALIER_ORDER if p in df["palier"].values]))
    return fig


def outage_monthly_bars(unavail_df: pd.DataFrame, hourly: pd.DataFrame) -> go.Figure | None:
    """
    Alternativa chiara al Gantt: ore di indisponibilità per mese, per tipo,
    ricostruite dalla curva di disponibilità (capacità persa vs nominale).
    """
    if hourly.empty:
        return None
    nominal = float(hourly["nominal_MW"].iloc[0])
    df = hourly.copy()
    # capacità persa = nominale − disponibile (in "unità reattore": frazione persa)
    lost_frac = ((nominal - df["availability_MW"]).clip(lower=0) / nominal)
    df["planned_h"] = 0.0
    df["forced_h"] = 0.0
    df.loc[df["event_type"] == "planned_maintenance", "planned_h"] = lost_frac
    df.loc[df["event_type"] == "forced_unavailability", "forced_h"] = lost_frac
    m = df.resample("ME")[["planned_h", "forced_h"]].sum()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=m.index, y=m["planned_h"], name="Manutenzione pianificata",
                         marker_color=COLORS["planned"]))
    fig.add_trace(go.Bar(x=m.index, y=m["forced_h"], name="Guasto / Forza Maggiore",
                         marker_color=COLORS["forced"]))
    fig.update_layout(barmode="stack", yaxis_title="Ore-equivalenti di indisponibilità",
                      height=340, margin=dict(t=10, b=30),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


def availability_band(hourly: pd.DataFrame, unavail_df: pd.DataFrame | None = None) -> go.Figure:
    """
    Disponibilità nel tempo come area (capacità disponibile in % del nominale),
    con la produzione sovrapposta. Gli outage si vedono come crolli dell'area.
    Più leggibile del Gantt.
    """
    nominal = float(hourly["nominal_MW"].iloc[0])
    avail_pct = hourly["availability_MW"] / nominal * 100
    prod_pct = hourly["production_MW_pos"] / nominal * 100
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hourly.index, y=avail_pct, name="Capacità disponibile",
        fill="tozeroy", line=dict(color=COLORS["availability"], width=0.8),
        fillcolor="rgba(22,163,74,0.15)",
        hovertemplate="Disponibile: %{y:.0f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=hourly.index, y=prod_pct, name="Produzione",
        line=dict(color=COLORS["production"], width=1),
        hovertemplate="Produzione: %{y:.0f}%<extra></extra>",
    ))
    fig.update_layout(yaxis_title="% del nominale", yaxis_range=[0, 105],
                      hovermode="x unified", height=340, margin=dict(t=10, b=30),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


def xenon_recovery_hist(recovery: pd.Series) -> go.Figure | None:
    """Distribuzione dei tempi di recupero dopo un ramp-down profondo, con la
    finestra del transitorio da xeno (6-16 h) evidenziata."""
    if recovery is None or recovery.empty:
        return None
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=recovery, nbinsx=48, marker_color=COLORS["production"],
                               name="Risalite"))
    # finestra xeno
    fig.add_vrect(x0=6, x1=16, fillcolor="rgba(220,38,38,0.12)", line_width=0,
                  annotation_text="finestra xeno-135 (6–16 h)",
                  annotation_position="top")
    med = float(recovery.median())
    fig.add_vline(x=med, line=dict(color="#111", width=2, dash="dash"),
                  annotation_text=f"mediana {med:.0f} h", annotation_position="top left")
    fig.update_layout(xaxis_title="Ore prima della risalita di potenza",
                      yaxis_title="N. manovre", height=340, margin=dict(t=30, b=30),
                      showlegend=False)
    return fig


def deep_modulations_hist(deep_df: pd.DataFrame) -> go.Figure | None:
    """Quante volte capita di avere 1, 2, 3... ramp-down profondi (>40%) in un
    singolo giorno. Mostra il tetto fisico giornaliero."""
    if deep_df is None or deep_df.empty:
        return None
    counts = deep_df["n_deep_down"].value_counts().sort_index()
    fig = go.Figure(go.Bar(
        x=counts.index.astype(int).astype(str), y=counts.values,
        marker_color=COLORS["ramp_down"],
        text=counts.values, textposition="outside",
    ))
    fig.update_layout(xaxis_title="Ramp-down profondi (>40% Pnom) nello stesso giorno",
                      yaxis_title="N. giorni", height=320, margin=dict(t=10, b=30),
                      showlegend=False)
    return fig


def modulation_capacity_bars(cap: dict) -> go.Figure | None:
    """Confronto a barre dei tre livelli di modulazione + installato di riferimento."""
    if not cap:
        return None
    labels = ["Sostenibile<br>(ogni giorno)", "Settimana<br>più intensa",
              "Stagionale<br>(su mesi)", "Picco assoluto<br>(una tantum)"]
    vals = [cap["sustained_GW"], cap["week_best_GW"],
            cap["seasonal_GW"], cap["peak_swing_GW"]]
    cols = [COLORS["availability"], "#F59E0B", "#0891B2", COLORS["ramp_down"]]
    fig = go.Figure(go.Bar(
        x=vals, y=labels, orientation="h", marker_color=cols,
        text=[f"{v:.1f} GW" for v in vals], textposition="outside",
    ))
    fig.add_vline(x=cap["installed_GW"], line=dict(color="#94A3B8", width=1.5, dash="dash"),
                  annotation_text=f"installato {cap['installed_GW']:.0f} GW",
                  annotation_position="top")
    fig.update_layout(xaxis_title="GW di modulazione", height=320,
                      margin=dict(t=30, b=30), showlegend=False,
                      xaxis_range=[0, cap["installed_GW"] * 1.05])
    fig.update_yaxes(autorange="reversed")
    return fig


def daily_swing_distribution(cap: dict) -> go.Figure | None:
    """Distribuzione delle escursioni giornaliere della flotta, con mediana e picco."""
    if not cap or "swing_series" not in cap or cap["swing_series"].empty:
        return None
    sw = cap["swing_series"]
    fig = go.Figure(go.Histogram(x=sw, nbinsx=40, marker_color=COLORS["production"]))
    fig.add_vline(x=cap["sustained_GW"], line=dict(color=COLORS["availability"], width=2),
                  annotation_text=f"sostenibile {cap['sustained_GW']:.1f} GW",
                  annotation_position="top")
    fig.add_vline(x=cap["peak_swing_GW"], line=dict(color=COLORS["ramp_down"], width=2, dash="dash"),
                  annotation_text=f"picco {cap['peak_swing_GW']:.1f} GW",
                  annotation_position="top right")
    fig.update_layout(xaxis_title="Escursione giornaliera della flotta (GW)",
                      yaxis_title="N. giorni", height=320, margin=dict(t=30, b=30),
                      showlegend=False)
    return fig


def lf_ramp_envelope(hourly: pd.DataFrame) -> go.Figure:
    """
    Inviluppo degli eventi-rampa online: ogni punto è una manovra
    (x = durata in ore, y = ampiezza in % Pnom), colore = su/giù, dimensione =
    velocità. Mostra i LIMITI: fino a dove e quanto in fretta il reattore modula.
    """
    ev = _lf.ramp_events(hourly)
    if ev.empty:
        return go.Figure()
    ev = ev[ev["online"]].copy()
    if ev.empty:
        return go.Figure()
    ev["abs_pct"] = ev["delta_pct"].abs()
    fig = go.Figure()
    for d, col, name in [("up", COLORS["ramp_up"], "Rampa su"),
                         ("down", COLORS["ramp_down"], "Rampa giù")]:
        sub = ev[ev["direction"] == d]
        fig.add_trace(go.Scatter(
            x=sub["duration_h"], y=sub["abs_pct"], mode="markers", name=name,
            marker=dict(size=6, color=col, opacity=0.45,
                        line=dict(width=0)),
            hovertemplate="Durata: %{x} h<br>Ampiezza: %{y:.0f}% Pnom<extra></extra>",
        ))
    # evidenzia la manovra massima
    mx = ev.loc[ev["abs_pct"].idxmax()]
    fig.add_trace(go.Scatter(
        x=[mx["duration_h"]], y=[mx["abs_pct"]], mode="markers+text",
        marker=dict(size=14, color="#111", symbol="star"),
        text=["max"], textposition="top center", showlegend=False,
        hovertemplate=f"MAX: {mx['abs_pct']:.0f}% Pnom in {int(mx['duration_h'])}h<extra></extra>",
    ))
    fig.update_layout(xaxis_title="Durata manovra (ore)",
                      yaxis_title="Ampiezza (% Pnom)",
                      height=380, margin=dict(t=10, b=30),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


def fleet_simultaneous_hist(hourly_by_reactor: dict, reactors: list[str],
                            date_from, date_to) -> go.Figure | None:
    """Distribuzione: per quante ore N reattori modulano contemporaneamente."""
    frames = []
    for r in reactors:
        if r not in hourly_by_reactor:
            continue
        h = hourly_by_reactor[r]
        h = h.loc[(h.index >= pd.Timestamp(date_from)) &
                  (h.index <= pd.Timestamp(date_to) + pd.Timedelta(days=1))]
        if h.empty:
            continue
        frames.append((_lf.classify_states(h) == "load_follow").astype(int).rename(r))
    if not frames:
        return None
    mat = pd.concat(frames, axis=1).fillna(0)
    simul = mat.sum(axis=1)
    fig = go.Figure(go.Histogram(x=simul, marker_color=COLORS["planned"],
                                 nbinsx=int(simul.max()) + 1))
    fig.add_vline(x=simul.max(), line=dict(color="#DC2626", width=2, dash="dash"),
                  annotation_text=f"max {int(simul.max())}", annotation_position="top")
    fig.update_layout(xaxis_title="N. reattori in modulazione simultanea",
                      yaxis_title="N. ore", height=340, margin=dict(t=10, b=30),
                      showlegend=False)
    return fig


def lf_state_stack(hourly: pd.DataFrame, freq: str = "ME") -> go.Figure:
    """Quota di ore in ciascuno stato operativo nel tempo (area impilata)."""
    states = _lf.classify_states(hourly)
    df = pd.DataFrame({"state": states})
    grp = df.groupby([pd.Grouper(freq=freq), "state"]).size().unstack(fill_value=0)
    grp = grp.div(grp.sum(axis=1), axis=0) * 100
    for s in ["off", "low", "load_follow", "full"]:
        if s not in grp:
            grp[s] = 0

    fig = go.Figure()
    for s in ["full", "load_follow", "low", "off"]:
        fig.add_trace(go.Scatter(
            x=grp.index, y=grp[s], name=STATE_LABELS[s], stackgroup="one",
            mode="lines", line=dict(width=0.5, color=STATE_COLORS[s]),
            fillcolor=STATE_COLORS[s],
            hovertemplate=STATE_LABELS[s] + ": %{y:.0f}%<extra></extra>",
        ))
    fig.update_layout(yaxis_title="% delle ore", yaxis_range=[0, 100],
                      height=340, margin=dict(t=10, b=30),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


def lf_ramp_frequency(hourly: pd.DataFrame, freq: str = "ME") -> go.Figure:
    """Numero di eventi-rampa di load-following (online) nel tempo, su/giù."""
    ev = _lf.ramp_events(hourly)
    if ev.empty:
        return go.Figure()
    ev = ev[ev["online"]].copy()
    ev["period"] = ev["start"].dt.to_period(
        {"ME": "M", "W": "W", "D": "D"}.get(freq, "M")).dt.to_timestamp()
    g = ev.groupby(["period", "direction"]).size().unstack(fill_value=0)
    for d in ["up", "down"]:
        if d not in g:
            g[d] = 0
    fig = go.Figure()
    fig.add_trace(go.Bar(x=g.index, y=g["up"], name="Rampe su",
                         marker_color=COLORS["ramp_up"]))
    fig.add_trace(go.Bar(x=g.index, y=-g["down"], name="Rampe giù",
                         marker_color=COLORS["ramp_down"]))
    fig.update_layout(barmode="relative", yaxis_title="N. eventi-rampa (online)",
                      height=320, margin=dict(t=10, b=30),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


def lf_diurnal_profile(hourly: pd.DataFrame) -> go.Figure:
    """Profilo medio per ora del giorno: produzione (% Pnom) + rampa media."""
    d = _lf.diurnal_signature(hourly)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(
        x=d["hour"], y=d["prod_pct"], name="Produzione media (% Pnom)",
        line=dict(color=COLORS["production"], width=2.5),
        fill="tozeroy", fillcolor="rgba(37,99,235,0.12)",
    ), secondary_y=False)
    fig.add_trace(go.Bar(
        x=d["hour"], y=d["ramp_pct_min"], name="Rampa media (% Pnom/min)",
        marker_color=["#EA580C" if v >= 0 else "#9333EA" for v in d["ramp_pct_min"]],
        opacity=0.6,
    ), secondary_y=True)
    fig.update_xaxes(title_text="Ora del giorno", tickmode="linear", dtick=2)
    fig.update_yaxes(title_text="Produzione (% Pnom)", secondary_y=False, range=[0, 100])
    fig.update_yaxes(title_text="Rampa media (% Pnom/min)", secondary_y=True)
    fig.update_layout(height=340, margin=dict(t=10, b=30),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


def lf_diurnal_heatmap(hourly: pd.DataFrame) -> go.Figure:
    """Heatmap ora-del-giorno × mese della produzione media (% Pnom).
    Rende visibile *quando* nell'anno e nella giornata il reattore modula."""
    nominal = float(hourly["nominal_MW"].iloc[0])
    df = hourly.copy()
    df["hour"] = df.index.hour
    df["month"] = df.index.month
    piv = df.pivot_table(index="hour", columns="month",
                         values="production_MW_pos", aggfunc="mean") / nominal * 100
    it_months = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
                 "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
    piv = piv.reindex(columns=range(1, 13))
    fig = px.imshow(
        piv.values, x=it_months, y=[f"{h:02d}h" for h in piv.index],
        color_continuous_scale=[[0, "#B91C1C"], [0.6, "#F59E0B"], [1, "#15803D"]],
        range_color=[0, 100], aspect="auto", origin="lower",
        labels=dict(x="Mese", y="Ora", color="% Pnom"),
    )
    fig.update_layout(height=420, margin=dict(t=10, b=20))
    return fig


def lf_cycles_per_month(hourly: pd.DataFrame) -> go.Figure:
    """Giorni di load-following per mese + cicli medi per giorno di LF."""
    daily = _lf.daily_load_following(hourly)
    if daily.empty:
        return go.Figure()
    daily["month"] = pd.to_datetime(daily["date"]).dt.to_period("M").dt.to_timestamp()
    g = daily.groupby("month").agg(
        lf_days=("is_lf_day", "sum"),
        cycles=("n_cycles", lambda x: x[daily.loc[x.index, "is_lf_day"]].mean()),
    ).reset_index()
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=g["month"], y=g["lf_days"], name="Giorni di LF",
                         marker_color=COLORS["planned"]), secondary_y=False)
    fig.add_trace(go.Scatter(x=g["month"], y=g["cycles"], name="Cicli/giorno LF",
                             line=dict(color=COLORS["ramp_down"], width=2)),
                  secondary_y=True)
    fig.update_yaxes(title_text="Giorni di LF nel mese", secondary_y=False)
    fig.update_yaxes(title_text="Cicli medi/giorno", secondary_y=True, range=[0, 3])
    fig.update_layout(height=320, margin=dict(t=10, b=30),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig


def lf_ramp_rate_hist(hourly: pd.DataFrame) -> go.Figure:
    """Distribuzione delle velocità di rampa degli eventi online, con la linea
    del limite di letteratura (~20% Pnom/h, Argonne/MIT)."""
    ev = _lf.ramp_events(hourly)
    if ev.empty:
        return go.Figure()
    ev = ev[ev["online"]]
    rates = ev["rate_pct_h"].abs()
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=rates, nbinsx=50, marker_color=COLORS["production"],
                               name="Eventi online"))
    fig.add_vline(x=_lf.LIT_REFERENCE["max_ramp_pct_h"],
                  line=dict(color="#DC2626", width=2, dash="dash"),
                  annotation_text="~20%/h (letteratura)", annotation_position="top")
    fig.update_layout(xaxis_title="Velocità di rampa (% Pnom/h)",
                      yaxis_title="N. eventi", height=300, margin=dict(t=10, b=30),
                      showlegend=False)
    return fig


def fleet_reactors_modulating(hourly_by_reactor: dict, reactors: list[str],
                              date_from, date_to, freq: str = "D") -> go.Figure | None:
    """Quanti reattori sono in load-following simultaneamente, nel tempo."""
    frames = []
    for r in reactors:
        if r not in hourly_by_reactor:
            continue
        h = hourly_by_reactor[r]
        h = h.loc[(h.index >= pd.Timestamp(date_from)) &
                  (h.index <= pd.Timestamp(date_to) + pd.Timedelta(days=1))]
        if h.empty:
            continue
        st = _lf.classify_states(h)
        frames.append((st == "load_follow").astype(int).rename(r))
    if not frames:
        return None
    mat = pd.concat(frames, axis=1).fillna(0)
    modulating = mat.sum(axis=1).resample(freq).mean()

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=modulating.index, y=modulating.values,
                             name="Reattori in load-following",
                             fill="tozeroy", line=dict(color=COLORS["planned"], width=1.5),
                             fillcolor="rgba(245,158,11,0.2)"))
    fig.add_hline(y=len(frames), line=dict(color="#94A3B8", width=1, dash="dash"),
                  annotation_text=f"selezionati: {len(frames)}", annotation_position="top left")
    fig.update_layout(yaxis_title="N. reattori modulanti",
                      height=340, margin=dict(t=10, b=30),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
    return fig
