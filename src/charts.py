"""
charts.py — Figure Plotly per l'app.
La vista oraria produzione↔availability è il grafico centrale.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

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

    # Nominale
    if show_nominal and "nominal_MW" in hourly:
        nominal = float(hourly["nominal_MW"].iloc[0])
        fig.add_hline(
            y=nominal, line=dict(color=COLORS["nominal"], width=1, dash="dash"),
            annotation_text=f"Nominale {nominal:.0f} MW",
            annotation_position="top left",
        )

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
