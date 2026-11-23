import marimo

__generated_with = "0.25.2"
app = marimo.App(width="full", app_title="Spending")


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
    mo.Html(ui.nav("spending"))
    return


@app.cell
def _(d, mo, ui):
    _years = d.expense_years(ui.EXPENSES_KEY)
    year = mo.ui.dropdown([str(y) for y in _years], value=str(_years[-1]), label="Year")
    threshold = mo.ui.number(start=0, stop=1_000_000, step=500, value=5000,
                             label="List one-offs of at least ($) separately")
    refresh = mo.ui.button(label="Refresh from sheet", value=0, on_click=lambda v: v + 1)
    mo.hstack([year, threshold, refresh], justify="start", gap=2)
    return refresh, threshold, year


@app.cell
def _(d, refresh, threshold, ui, year):
    expenses = d.load_expenses(ui.EXPENSES_KEY, int(year.value), version=refresh.value)
    one_offs = expenses[expenses[d.AMOUNT] >= threshold.value] if threshold.value else expenses.iloc[0:0]
    everyday = expenses.drop(one_offs.index)
    return everyday, expenses, one_offs


@app.cell
def _(d, everyday, expenses, mo, one_offs, pd, ui):
    _monthly = everyday.groupby(d.MONTH)[d.AMOUNT].sum().sort_index()
    _total = expenses[d.AMOUNT].sum()
    _this = _monthly.iloc[-1] if len(_monthly) else 0.0
    _prev = _monthly.iloc[-2] if len(_monthly) > 1 else 0.0
    _last = _monthly.index[-1] if len(_monthly) else pd.Timestamp.today()
    mo.Html(ui.kpi_row(
        ui.kpi("Spent this year", ui.money(_total), f"{len(expenses)} expenses incl. one-offs"),
        ui.kpi(f"Spent in {_last:%b}", ui.money(_this), f"{ui.money(_this - _prev, True)} vs {(_last - pd.DateOffset(months=1)):%b}",
               ui.tone(_this - _prev, good_when_positive=False)),
        ui.kpi("Average month", ui.money(_monthly.mean() if len(_monthly) else 0), "excluding one-offs"),
        ui.kpi("One-offs", ui.money(one_offs[d.AMOUNT].sum()), f"{len(one_offs)} expense(s)"),
    ))
    return


@app.cell
def _(d, everyday, mo):
    _cats = sorted(everyday[d.CATEGORY].unique())
    category = mo.ui.dropdown(["All categories"] + _cats, value="All categories", label="Drill into")
    category
    return (category,)


@app.cell
def _(alt, category, d, everyday, mo):
    _all = category.value == "All categories"
    _df = everyday if _all else everyday[everyday[d.CATEGORY] == category.value]
    _by = d.CATEGORY if _all else d.SUBCATEGORY
    _agg = _df.groupby([d.MONTH, _by], as_index=False)[d.AMOUNT].sum()
    _chart = (
        alt.Chart(_agg)
        .mark_bar()
        .encode(
            x=alt.X(f"yearmonth({d.MONTH}):O", title=None, axis=alt.Axis(format="%b")),
            y=alt.Y(f"sum({d.AMOUNT}):Q", title="Your share ($)", axis=alt.Axis(format="$,.0f")),
            color=alt.Color(f"{_by}:N", title=_by.title()),
            tooltip=[alt.Tooltip(f"yearmonth({d.MONTH}):O", title="Month", format="%b %Y"),
                     alt.Tooltip(f"{_by}:N", title=_by.title()),
                     alt.Tooltip(f"sum({d.AMOUNT}):Q", title="Amount", format="$,.2f")],
        )
        .properties(height=340, title=f"Spending by month: {category.value}")
    )
    mo.ui.altair_chart(_chart)
    return


@app.cell
def _(category, d, everyday, mo):
    _all = category.value == "All categories"
    _df = everyday if _all else everyday[everyday[d.CATEGORY] == category.value]
    _by = d.CATEGORY if _all else d.SUBCATEGORY
    _pivot = _df.pivot_table(index=_by, columns=d.MONTH, values=d.AMOUNT, aggfunc="sum", fill_value=0.0)
    _pivot.columns = [c.strftime("%b") for c in _pivot.columns]
    _pivot["Total"] = _pivot.sum(axis=1)
    _pivot = _pivot.sort_values("Total", ascending=False)
    _pivot.loc["Total"] = _pivot.sum()
    _fmt = {c: "${:,.0f}" for c in _pivot.columns}
    mo.vstack([mo.md(f"### By {_by} and month"), mo.ui.table(_pivot.round(2).reset_index(), selection=None, format_mapping=_fmt, page_size=40)])
    return


@app.cell
def _(d, everyday, mo):
    _top = (everyday.groupby(d.DESCRIPTION)[d.AMOUNT].agg(["sum", "count"])
            .sort_values("sum", ascending=False).head(15).reset_index())
    _top.columns = ["Merchant", "Total", "Count"]
    mo.vstack([mo.md("### Top merchants"),
               mo.ui.table(_top.round(2), selection=None, format_mapping={"Total": "${:,.2f}"}, page_size=15)])
    return


@app.cell
def _(d, mo, one_offs):
    _t = one_offs[[d.DATE, d.CATEGORY, d.SUBCATEGORY, d.DESCRIPTION, d.AMOUNT]].sort_values(d.DATE).copy()
    _t[d.DATE] = _t[d.DATE].dt.strftime("%Y-%m-%d")
    mo.vstack([mo.md("### One-off expenses (kept out of the charts above)"),
               mo.ui.table(_t.round(2), selection=None, format_mapping={d.AMOUNT: "${:,.2f}"})
               if len(_t) else mo.md("_None at this threshold._")])
    return


if __name__ == "__main__":
    app.run()
