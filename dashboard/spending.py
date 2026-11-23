import marimo

__generated_with = "0.25.2"
app = marimo.App(width="full", app_title="Spending")


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
    mo.Html(ui.nav("spending"))
    return


@app.cell
def _(d, mo, ui):
    _years = d.expense_years(ui.EXPENSES_KEY)
    year = mo.ui.dropdown([str(y) for y in _years], value=str(_years[-1]), label="Year")
    threshold = mo.ui.number(start=0, stop=1_000_000, step=500, value=5000,
                             label="List one-offs of at least ($) separately")
    refresh = mo.ui.button(label="Refresh from sheet", kind="neutral", value=0, on_click=lambda v: v + 1)
    mo.Html(ui.block(
        ui.header("Spending", "Expenses sheet · Your share (My Owed)"),
        f'<div class="t-filter-row">{mo.as_html(year)}{mo.as_html(threshold)}{mo.as_html(refresh)}</div>',
    ))
    return refresh, threshold, year


@app.cell
def _(d, refresh, threshold, ui, year):
    _all = d.load_expenses(ui.EXPENSES_KEY, int(year.value), version=refresh.value)
    _purchase = d.is_house_purchase(_all)
    house = _all[_purchase]
    expenses = _all[~_purchase]
    one_offs = expenses[expenses[d.AMOUNT] >= threshold.value] if threshold.value else expenses.iloc[0:0]
    everyday = expenses.drop(one_offs.index)
    return everyday, expenses, house, one_offs


@app.cell
def _(d, everyday, expenses, mo, one_offs, pd, ui):
    _monthly = everyday.groupby(d.MONTH)[d.AMOUNT].sum().sort_index()
    _total = expenses[d.AMOUNT].sum()
    _this = _monthly.iloc[-1] if len(_monthly) else 0.0
    _prev = _monthly.iloc[-2] if len(_monthly) > 1 else 0.0
    _last = _monthly.index[-1] if len(_monthly) else pd.Timestamp.today()
    _change_cls = ui.tone(_this - _prev, good_when_positive=False)
    mo.Html(ui.block(ui.kpi_row(
        ui.kpi("Spent this year", ui.money(_total), f"{len(expenses)} expenses incl. one-offs"),
        ui.kpi(f"Spent in {_last:%b}", ui.money(_this),
               f"{ui.money(_this - _prev, True)} vs {(_last - pd.DateOffset(months=1)):%b}", _change_cls or "amb"),
        ui.kpi("Average month", ui.money(_monthly.mean() if len(_monthly) else 0), "excluding one-offs"),
        ui.kpi("One-offs", ui.money(one_offs[d.AMOUNT].sum()), f"{len(one_offs)} expense(s)", "amb"),
    )))
    return


@app.cell
def _(d, everyday, mo, ui):
    _cats = sorted(everyday[d.CATEGORY].unique())
    category = mo.ui.dropdown(["All categories"] + _cats, value="All categories", label="Drill into")
    mo.Html(ui.block(f'<div class="t-filter-row">{mo.as_html(category)}</div>'))
    return (category,)


@app.cell
def _(category, d, everyday):
    show_all = category.value == "All categories"
    selected = everyday if show_all else everyday[everyday[d.CATEGORY] == category.value]
    group_by = d.CATEGORY if show_all else d.SUBCATEGORY
    return group_by, selected


@app.cell
def _(category, group_by, mo, selected, d, ui):
    # Top 7 groups get their own color; the rest are lumped into "Other"
    _totals = selected.groupby(group_by)[d.AMOUNT].sum().sort_values(ascending=False)
    _top = list(_totals.index[:7])
    _named = selected[group_by].where(selected[group_by].isin(_top), "Other")
    _p = selected.assign(_g=_named).pivot_table(index=d.MONTH, columns="_g", values=d.AMOUNT,
                                                aggfunc="sum", fill_value=0.0).sort_index()
    _names = [g for g in _top + ["Other"] if g in _p.columns]
    _colors = ui.PALETTE[:len(_top)] + ([ui.OTHER_COLOR] if "Other" in _names else [])
    _labels = [m.strftime("%b") for m in _p.index]
    _series = {g: _p[g].tolist() for g in _names}
    mo.Html(ui.block(
        ui.section(f"Spending by month: {category.value}"),
        ui.legend(_names, _colors),
        f'<div class="t-chart">{ui.stacked_bars_svg(_labels, _series, _colors)}</div>',
    ))
    return


@app.cell
def _(d, group_by, mo, selected, ui):
    _totals = selected.groupby(group_by)[d.AMOUNT].sum().sort_values(ascending=False)
    _sum = _totals.sum() or 1
    _items = [(name, v, f"{ui.money(v)} ({v / _sum:.0%})",
               ui.PALETTE[i] if i < 7 else ui.OTHER_COLOR) for i, (name, v) in enumerate(_totals.items())]
    mo.Html(ui.block(ui.section(f"Spend by {group_by}"), ui.bar_rows(_items)))
    return


@app.cell
def _(d, group_by, mo, selected, ui):
    _p = selected.pivot_table(index=group_by, columns=d.MONTH, values=d.AMOUNT, aggfunc="sum", fill_value=0.0)
    _months = [c.strftime("%b") for c in _p.columns]
    _p["Total"] = _p.sum(axis=1)
    _p = _p.sort_values("Total", ascending=False)
    _p.loc["Total"] = _p.sum()
    _rows = [[(ui.esc(name), "tk")] + [(ui.money(v) if v else "-", "" if v else "dim") for v in row]
             for name, row in zip(_p.index, _p.to_numpy())]
    _body = ui.table([group_by.title(), *_months, "Total"], _rows, total_last=True)
    mo.Html(ui.block(
        ui.section(f"By {group_by} and month"),
        ui.fold(f"{len(_p) - 1} {group_by} rows", f"{ui.money(_p.loc['Total', 'Total'])} total", _body),
    ))
    return


@app.cell
def _(d, everyday, mo, ui):
    _top = (everyday.groupby(d.DESCRIPTION)[d.AMOUNT].agg(["sum", "count"])
            .sort_values("sum", ascending=False).head(15))
    _rows = [[(ui.esc(name), "tk"), (f"${total:,.2f}", ""), (str(int(count)), "dim"),
              (f"${total / count:,.2f}", "dim")]
             for name, (total, count) in zip(_top.index, _top.to_numpy())]
    mo.Html(ui.block(
        ui.section("Top merchants"),
        ui.fold(f"{len(_top)} merchants", f"{ui.money(_top['sum'].sum())} total",
                ui.table(["Merchant", "Total", "Count", "Avg"], _rows)),
    ))
    return


@app.cell
def _(d, mo, one_offs, ui):
    _t = one_offs.sort_values(d.DATE)
    if len(_t):
        _rows = [[(f"{r[d.DATE]:%Y-%m-%d}", "dim"), (ui.esc(r[d.CATEGORY]), ""), (ui.esc(r[d.SUBCATEGORY]), "dim"),
                  (ui.esc(r[d.DESCRIPTION]), "tk"), (f"${r[d.AMOUNT]:,.2f}", "")] for _, r in _t.iterrows()]
        _body = ui.fold(f"{len(_t)} expense(s)", f"{ui.money(_t[d.AMOUNT].sum())} total",
                        ui.table(["Date", "Category", "Subcategory", "Description", "Amount"], _rows, num_from=4),
                        open_=True)
    else:
        _body = ui.note("None at this threshold.")
    mo.Html(ui.block(ui.section("One-off expenses (kept out of the charts above)"), _body))
    return


@app.cell
def _(d, house, mo, ui):
    # Only shown in a year with house-purchase rows
    if len(house):
        _rows = [[(f"{r[d.DATE]:%Y-%m-%d}", "dim"), (ui.esc(r[d.DESCRIPTION]), "tk"), (f"${r[d.AMOUNT]:,.2f}", "")]
                 for _, r in house.sort_values(d.DATE).iterrows()]
        _out = ui.block(
            ui.section("House purchase (not counted as spending)"),
            ui.note("Already in net worth as home equity, so left out of every total above."),
            ui.fold(f"{len(house)} payment(s)", f"{ui.money(house[d.AMOUNT].sum())} your share",
                    ui.table(["Date", "Description", "Amount"], _rows, num_from=2), open_=True),
        )
    else:
        _out = ""
    mo.Html(_out)
    return


if __name__ == "__main__":
    app.run()
