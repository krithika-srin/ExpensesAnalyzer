import marimo

__generated_with = "0.25.2"
app = marimo.App(width="full", app_title="Net Worth")


@app.cell
def _():
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    import marimo as mo
    import pandas as pd

    from dashboard import data as d
    from dashboard import ui
    return d, mo, pd, ui


@app.cell
def _(mo, ui):
    mo.Html(ui.nav("net_worth"))
    return


@app.cell
def _(mo):
    refresh = mo.ui.button(label="Refresh from sheet", kind="neutral", value=0, on_click=lambda v: v + 1)
    split = mo.ui.switch(label="Split by group", value=True)
    return refresh, split


@app.cell
def _(d, refresh, ui):
    nw = d.load_net_worth(ui.NET_WORTH_KEY, version=refresh.value)
    owed = d.owed_on_splitwise(version=refresh.value)  # what you owe your partner today; None if unavailable
    totals = nw.groupby(d.MONTH)[[d.BEGIN, d.END]].sum().sort_index()
    latest = totals.index.max()
    # Known groups first, in their usual order, then any others (e.g. "Real Estate") alphabetically
    _present = set(nw[d.GROUP])
    groups = [g for g in ui.GROUP_COLORS if g in _present] + sorted(_present - set(ui.GROUP_COLORS))
    _extra = iter(c for c in ui.PALETTE if c not in ui.GROUP_COLORS.values())
    group_colors = [ui.GROUP_COLORS.get(g) or next(_extra, ui.OTHER_COLOR) for g in groups]
    return group_colors, groups, latest, nw, owed, totals


@app.cell
def _(d, latest, mo, nw, owed, pd, refresh, totals, ui):
    _now = totals.loc[latest, d.END]
    _cur = nw[nw[d.MONTH] == latest]
    _debt = owed or 0.0
    _net = _now - _debt
    _non_ret = _cur.loc[~_cur[d.GROUP].isin(d.RETIREMENT_GROUPS), d.END].sum() - _debt
    if owed is None:
        _owed_note = "Holdings only (Splitwise not connected)"
    elif owed > 0:
        _owed_note = f"after {ui.money(owed)} you owe on Splitwise"
    elif owed < 0:
        _owed_note = f"incl. {ui.money(-owed)} owed to you on Splitwise"
    else:
        _owed_note = "Splitwise is settled up"
    _month = _now - totals.loc[latest, d.BEGIN]
    _jan = pd.Timestamp(year=latest.year, month=1, day=1)
    _ytd_start = totals.loc[_jan, d.BEGIN] if _jan in totals.index else totals[d.BEGIN].iloc[0]
    _ytd = _now - _ytd_start
    _all = _now - totals[d.BEGIN].iloc[0]
    mo.Html(ui.block(
        ui.header("Net Worth", f"Holdings · As of end of {latest:%b %Y}"),
        f'<div class="t-filter-row">{mo.as_html(refresh)}</div>',
        ui.kpi_row(
            ui.kpi("Net worth", ui.money(_net), _owed_note),
            ui.kpi("Non-retirement net worth", ui.money(_non_ret), "excludes retirement &amp; HSA", "amb"),
            ui.kpi(f"Change in {latest:%b}", ui.money(_month, True), "ending minus beginning",
                   ui.tone(_month) or "amb", ui.tone(_month)),
            ui.kpi(f"Change in {latest:%Y}", ui.money(_ytd, True), f"since Jan 1 ({ui.money(_ytd_start)})",
                   ui.tone(_ytd) or "amb", ui.tone(_ytd)),
            ui.kpi("Since tracking began", ui.money(_all, True), f"from {totals.index[0]:%b %Y}",
                   ui.tone(_all) or "amb", ui.tone(_all)),
        ),
    ))
    return


@app.cell
def _(mo, totals):
    _years = sorted({str(m.year) for m in totals.index}, reverse=True)
    chart_year = mo.ui.dropdown(["All years"] + _years, value="All years", label="Year")
    return (chart_year,)


@app.cell
def _(chart_year, d, group_colors, groups, mo, nw, owed, split, totals, ui):
    _shown = totals if chart_year.value == "All years" else totals[totals.index.year == int(chart_year.value)]
    _labels = [m.strftime("%b %y") for m in _shown.index]
    if split.value:
        _p = nw.pivot_table(index=d.MONTH, columns=d.GROUP, values=d.END, aggfunc="sum", fill_value=0.0)
        _p = _p.reindex(index=_shown.index, columns=groups, fill_value=0.0)
        _series = {g: _p[g].tolist() for g in groups}
        _svg = ui.stacked_bars_svg(_labels, _series, group_colors, line=_shown[d.END].tolist())
        _legend = ui.legend(groups + ["Net worth"], group_colors + ["#e8edf5"])
    else:
        _svg = ui.stacked_bars_svg(_labels, {"Net worth": _shown[d.END].tolist()}, [ui.PALETTE[0]])
        _legend = ui.legend(["Net worth"], [ui.PALETTE[0]])
    mo.Html(ui.block(
        ui.section("Net worth over time (end of month)"),
        f'<div class="t-filter-row">{mo.as_html(chart_year)}{mo.as_html(split)}</div>',
        _legend,
        f'<div class="t-chart">{_svg}</div>',
        ui.note(f"Bars show the Holdings tabs only. The headline net worth also subtracts the {ui.money(owed)} "
                "you currently owe on Splitwise.") if owed else "",
    ))
    return


@app.cell
def _(d, group_colors, groups, latest, mo, nw, ui):
    _cur = nw[nw[d.MONTH] == latest].groupby(d.GROUP)[d.END].sum()
    _sum = _cur.sum() or 1
    _items = [(g, _cur[g], f"{ui.money(_cur[g])} ({_cur[g] / _sum:.0%})", c)
              for g, c in zip(groups, group_colors) if _cur.get(g, 0) != 0]
    mo.Html(ui.block(ui.section(f"Allocation at end of {latest:%b %Y}"), ui.bar_rows(_items)))
    return


@app.cell
def _(d, latest, mo, nw, owed, pd, ui):
    _jan = pd.Timestamp(year=latest.year, month=1, day=1)
    _cur = nw[nw[d.MONTH] == latest].set_index(d.ACCOUNT)
    _has_jan = (nw[d.MONTH] == _jan).any()
    _ytd_start = nw[nw[d.MONTH] == _jan].set_index(d.ACCOUNT)[d.BEGIN].reindex(_cur.index).fillna(0.0) if _has_jan else None
    _t = _cur.assign(month_chg=_cur[d.END] - _cur[d.BEGIN],
                     year_chg=(_cur[d.END] - _ytd_start) if _ytd_start is not None else float("nan"))
    _t = _t.sort_values([d.GROUP, d.END], ascending=[True, False])
    _sum = _t[d.END].sum() or 1

    def _chg(v):
        return ("-", "dim") if pd.isna(v) else (ui.money(v, True), ui.tone(v))

    _rows = [[(ui.esc(acct), "tk"), (ui.esc(r[d.GROUP]), "dim"), (ui.money(r[d.END]), ""),
              _chg(r["month_chg"]), _chg(r["year_chg"]), (f"{r[d.END] / _sum:.1%}", "dim")]
             for acct, r in _t.iterrows()]
    _total = _t[d.END].sum()
    if owed:
        _rows.append([("Splitwise balance (today)", "tk"), ("Debt" if owed > 0 else "Owed to you", "dim"),
                      (ui.money(-owed), "neg" if owed > 0 else "pos"), ("-", "dim"), ("-", "dim"), ("-", "dim")])
        _total -= owed
    _rows.append([("Total", "tk"), ("", ""), (ui.money(_total), ""), _chg(_t["month_chg"].sum()),
                  _chg(_t["year_chg"].sum(min_count=1)), ("", "")])
    mo.Html(ui.block(
        ui.section(f"Accounts at end of {latest:%b %Y}"),
        ui.fold(f"{len(_t)} accounts", f"{ui.money(_total)} total",
                ui.table(["Account", "Group", "Balance", "This month", "This year", "Share"], _rows,
                         num_from=2, total_last=True), open_=True),
    ))
    return


@app.cell
def _(d, latest, mo, nw, ui):
    _yr = nw[nw[d.MONTH].dt.year == latest.year].copy()
    _yr["change"] = _yr[d.END] - _yr[d.BEGIN]
    _p = _yr.pivot_table(index=d.ACCOUNT, columns=d.MONTH, values="change", aggfunc="sum", fill_value=0.0)
    _months = [c.strftime("%b") for c in _p.columns]
    _p = _p[(_p != 0).any(axis=1)]
    _p.loc["Total"] = _p.sum()
    _rows = [[(ui.esc(acct), "tk")] + [(ui.money(v, True), ui.tone(v)) if v else ("-", "dim") for v in row]
             for acct, row in zip(_p.index, _p.to_numpy())]
    mo.Html(ui.block(
        ui.section(f"Monthly change by account ({latest:%Y}, ending minus beginning)"),
        ui.fold(f"{len(_p) - 1} accounts", f"{ui.money(_p.loc['Total'].sum(), True)} this year",
                ui.table(["Account", *_months], _rows, total_last=True)),
    ))
    return


if __name__ == "__main__":
    app.run()
