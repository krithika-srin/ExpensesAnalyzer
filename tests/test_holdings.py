"""Tests for the holdings parser and net worth table (synthetic data only)."""

# Standard library
import os
import tempfile

# Third-party
import pandas as pd
import pytest

# Local application
from src.constants.holdings import NetWorthColumns as C
from src.database.db_manager import DatabaseManager
from src.holdings.holdings_parser import parse_amount, parse_holdings_grid
from src.holdings.net_worth import build_net_worth_table

YEAR = 2030


def _header(year=YEAR):
    months = []
    for m in ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]:
        months += [f"{m} {year}", ""]
    return ["Account", "Account Type ", "Sub-Type"] + months[:-1]


def _sub_header():
    return ["", "", ""] + ["Beginning Balance", "Ending Balance "] * 12


def _row(account, acct_type, sub_type, pairs):
    """pairs: list of (begin, end) per month; remaining months pre-filled with 0.00."""
    cells = []
    for begin, end in pairs:
        cells += [begin, end]
    cells += ["0.00", "0.00"] * (12 - len(pairs))
    return [account, acct_type, sub_type] + cells


@pytest.fixture
def grid():
    return [
        ["**This view is a representation of current holdings"],
        _header(),
        _sub_header(),
        _row("Brokerage", "Investment", "Stocks/ETFs", [("1,000.00", "1,100.00"), ("1,100.00", "1,200.00")]),
        _row("Bank ", "", "Bonds", [("500.00", "500.00"), ("500.00", "500.00")]),
        _row("Bank", "Savings", "Savings", [("2,000.00", "2,250.50"), ("2,250.50", "2,400.00")]),
        _row("Robo", "Retirement", "IRA ", [("3,000.00", "3,050.00"), ("3,050.00", "2,950.00")]),
        _row("Robo", "Health Savings", "", [("400.00", "410.00"), ("410.00", "420.00")]),
        [],
        ["Totals"],
        [],
        ["Investment Total", "", "", "$1,500.00", "$1,600.00"],
    ]


def test_parse_amount_variants():
    assert parse_amount("$1,234.56") == 1234.56
    assert parse_amount("-$7,790.45") == -7790.45
    assert parse_amount("(12.00)") == -12.0
    assert parse_amount("") is None
    assert parse_amount(None) is None
    assert parse_amount(5) == 5.0


def test_parse_grid_inherits_types_and_stops_at_totals(grid):
    snaps = parse_holdings_grid(grid, YEAR)
    # 5 accounts x 2 filled months; Mar-Dec are all zero so dropped
    assert len(snaps) == 10
    assert {s.year_month for s in snaps} == {"2030-01", "2030-02"}

    by_key = {(s.account_key, s.year_month): s for s in snaps}
    bonds = by_key[("Bank | Bonds", "2030-01")]
    assert bonds.account_type == "Investment"  # inherited from the row above
    assert by_key[("Robo | IRA", "2030-02")].ending_balance == 2950.0  # sub-type trimmed
    assert by_key[("Robo", "2030-01")].account_type == "Health Savings"  # blank sub-type
    assert not any(s.account.lower().endswith("total") for s in snaps)


def test_header_mismatch_raises(grid):
    grid[1] = _header(YEAR + 1)
    with pytest.raises(ValueError, match="layout changed"):
        parse_holdings_grid(grid, YEAR)


def test_net_worth_table(grid):
    snaps = [s.to_dict() for s in parse_holdings_grid(grid, YEAR)]
    spending = pd.Series({"2030-01": 1000.0, "2030-02": 3000.0})
    table = build_net_worth_table(snaps, spending).set_index(C.MONTH)

    jan, feb = table.loc["2030-01"], table.loc["2030-02"]
    assert jan[C.INVESTMENT] == 1600.0
    assert jan[C.SAVINGS] == 2250.5
    assert jan[C.LIQUID] == 3850.5
    assert jan[C.NET_WORTH] == 1600 + 2250.5 + 3050 + 410
    assert feb[C.MOM_CHANGE] == pytest.approx(feb[C.NET_WORTH] - jan[C.NET_WORTH])
    assert feb[C.AVG_SPEND] == 2000.0  # rolling mean of available months
    assert feb[C.RUNWAY_MONTHS] == pytest.approx(2400 / 2000, abs=0.01)
    assert C.OTHER not in table.columns


def test_db_round_trip_and_resync(grid):
    with tempfile.TemporaryDirectory() as tmp:
        db = DatabaseManager(os.path.join(tmp, "test.db"))
        rows = [s.to_dict() for s in parse_holdings_grid(grid, YEAR)]
        assert db.upsert_holdings(rows) == 10
        assert db.upsert_holdings(rows) == 10  # idempotent upsert
        assert len(db.get_holdings()) == 10
        assert len(db.get_holdings(start_month="2030-02")) == 5

        db.delete_holdings_for_months(["2030-01"])
        assert {r["year_month"] for r in db.get_holdings()} == {"2030-02"}
