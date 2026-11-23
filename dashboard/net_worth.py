import marimo

__generated_with = "0.25.2"
app = marimo.App(width="full", app_title="Net Worth")


@app.cell
def _():
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    import altair as alt
    import marimo as mo
    import pandas as pd

    from dashboard import data as d
    from dashboard import ui
    return alt, d, mo, pd, ui


@app.cell
def _(mo, ui):
    mo.Html(ui.nav("net_worth"))
    return


@app.cell
def _(mo):
    refresh = mo.ui.button(label="Refresh from sheet", value=0, on_click=lambda v: v + 1)
    split = mo.ui.switch(label="Split by group", value=True)
    mo.hstack([refresh, split], justify="start", gap=2)
    return refresh, split


@app.cell
def _(d, refresh, ui):
    nw = d.load_net_worth(ui.NET_WORTH_KEY, version=refresh.value)
    totals = nw.groupby(d.MONTH)[[d.BEGIN, d.END]].sum().sort_index()
    latest = totals.index.max()
    return latest, nw, totals


@app.cell
def _(d, latest, mo, pd, totals, ui):
    _now = totals.loc[latest, d.END]
    _month = _now - totals.loc[latest, d.BEGIN]
    _jan = pd.Timestamp(year=latest.year, month=1, day=1)
    _ytd_start = totals.loc[_jan, d.BEGIN] if _jan in totals.index else totals[d.BEGIN].iloc[0]
    _first = totals[d.BEGIN].iloc[0]
    mo.Html(ui.kpi_row(
        ui.kpi("Net worth", ui.money(_now), f"as of end of {latest:%b %Y}"),
        ui.kpi(f"Change in {latest:%b}", ui.money(_month, True), "ending minus beginning", ui.tone(_month)),
        ui.kpi(f"Change in {latest:%Y}", ui.money(_now - _ytd_start, True), f"since Jan 1 ({ui.money(_ytd_start)})", ui.tone(_now - _ytd_start)),
        ui.kpi("Since tracking began", ui.money(_now - _first, True), f"from {totals.index[0]:%b %Y}", ui.tone(_now - _first)),
    ))
    return


@app.cell
def _(alt, d, mo, nw, split, totals, ui):
    if split.value:
        _df = nw.groupby([d.MONTH, d.GROUP], as_index=False)[d.END].sum()
        _chart = alt.Chart(_df).mark_area(opacity=0.85).encode(
            x=alt.X(f"{d.MONTH}:T", title=None),
            y=alt.Y(f"{d.END}:Q", stack="zero", title="Ending balance ($)", axis=alt.Axis(format="$,.0f")),
            color=alt.Color(f"{d.GROUP}:N", title="Group",
                            scale=alt.Scale(domain=list(ui.GROUP_COLORS), range=list(ui.GROUP_COLORS.values()))),
            tooltip=[alt.Tooltip(f"{d.MONTH}:T", format="%b %Y", title="Month"), alt.Tooltip(f"{d.GROUP}:N", title="Group"),
                     alt.Tooltip(f"{d.END}:Q", format="$,.0f", title="Ending")],
        )
    else:
        _df = totals.reset_index()
        _chart = alt.Chart(_df).mark_line(point=True).encode(
            x=alt.X(f"{d.MONTH}:T", title=None),
            y=alt.Y(f"{d.END}:Q", title="Net worth ($)", axis=alt.Axis(format="$,.0f")),
            tooltip=[alt.Tooltip(f"{d.MONTH}:T", format="%b %Y", title="Month"), alt.Tooltip(f"{d.END}:Q", format="$,.0f", title="Net worth")],
        )
    mo.ui.altair_chart(_chart.properties(height=340, title="Net worth over time"))
    return


@app.cell
def _(alt, d, latest, mo, nw, ui):
    _cur = nw[nw[d.MONTH] == latest].groupby(d.GROUP, as_index=False)[d.END].sum()
    _cur = _cur[_cur[d.END] != 0]
    _cur["share"] = _cur[d.END] / _cur[d.END].sum()
    _bar = alt.Chart(_cur).mark_bar().encode(
        x=alt.X(f"sum({d.END}):Q", stack="normalize", title=None, axis=alt.Axis(format="%")),
        color=alt.Color(f"{d.GROUP}:N", title="Group",
                        scale=alt.Scale(domain=list(ui.GROUP_COLORS), range=list(ui.GROUP_COLORS.values()))),
        tooltip=[alt.Tooltip(f"{d.GROUP}:N"), alt.Tooltip(f"{d.END}:Q", format="$,.0f", title="Balance"),
                 alt.Tooltip("share:Q", format=".1%", title="Share")],
    ).properties(height=60, title=f"Allocation at end of {latest:%b %Y}")
    mo.ui.altair_chart(_bar)
    return


@app.cell
def _(d, latest, mo, nw, pd):
    _jan = pd.Timestamp(year=latest.year, month=1, day=1)
    _cur = nw[nw[d.MONTH] == latest].set_index(d.ACCOUNT)
    _ytd = nw[nw[d.MONTH] == _jan].set_index(d.ACCOUNT)[d.BEGIN] if (nw[d.MONTH] == _jan).any() else None
    _t = pd.DataFrame({
        "Group": _cur[d.GROUP],
        "Balance": _cur[d.END],
        "This month": _cur[d.END] - _cur[d.BEGIN],
        "This year": (_cur[d.END] - _ytd.reindex(_cur.index).fillna(0.0)) if _ytd is not None else float("nan"),
    })
    _t["Share"] = _t["Balance"] / _t["Balance"].sum()
    _t = _t.sort_values(["Group", "Balance"], ascending=[True, False]).reset_index().rename(columns={d.ACCOUNT: "Account"})
    _fmt = {c: "${:,.0f}" for c in ["Balance", "This month", "This year"]} | {"Share": "{:.1%}"}
    mo.vstack([mo.md(f"### Accounts at end of {latest:%b %Y}"),
               mo.ui.table(_t.round(4), selection=None, format_mapping=_fmt, page_size=30)])
    return


@app.cell
def _(d, latest, mo, nw):
    _yr = nw[nw[d.MONTH].dt.year == latest.year].copy()
    _yr["change"] = _yr[d.END] - _yr[d.BEGIN]
    _p = _yr.pivot_table(index=d.ACCOUNT, columns=d.MONTH, values="change", aggfunc="sum", fill_value=0.0)
    _p.columns = [c.strftime("%b") for c in _p.columns]
    _p = _p[(_p != 0).any(axis=1)]
    _p.loc["Total"] = _p.sum()
    mo.vstack([mo.md(f"### Monthly change by account ({latest:%Y}, ending minus beginning)"),
               mo.ui.table(_p.round(2).reset_index().rename(columns={d.ACCOUNT: "Account"}), selection=None,
                           format_mapping={c: "${:,.0f}" for c in _p.columns}, page_size=30)])
    return


if __name__ == "__main__":
    app.run()
