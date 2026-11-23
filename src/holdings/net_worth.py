"""Combine holdings snapshots and spending into a monthly net worth table."""

# Standard library
from typing import Dict, List, Optional

# Third-party
import pandas as pd

# Local application
from src.constants.holdings import (
    ALL_TYPES,
    LIQUID_TYPES,
    RUNWAY_SPEND_WINDOW_MONTHS,
    TYPE_SAVINGS,
    TYPE_UNKNOWN,
    NetWorthColumns as C,
)


def _month_balance(row: pd.Series) -> float:
    """Ending balance is the month's snapshot; fall back to beginning if ending is blank."""
    if pd.notna(row["ending_balance"]):
        return float(row["ending_balance"])
    if pd.notna(row["beginning_balance"]):
        return float(row["beginning_balance"])
    return 0.0


def build_net_worth_table(
    holdings: List[Dict],
    monthly_spending: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """Build one row per month with balances by account type and net worth.

    Args:
        holdings: Rows from DatabaseManager.get_holdings() (or HoldingSnapshot.to_dict())
        monthly_spending: Optional Series indexed by YYYY-MM with my spending that month

    Returns:
        DataFrame sorted by month (oldest first) with NetWorthColumns columns
    """
    if not holdings:
        return pd.DataFrame()

    df = pd.DataFrame(holdings)
    df["balance"] = df.apply(_month_balance, axis=1)
    df["group"] = df["account_type"].where(df["account_type"].isin(ALL_TYPES), TYPE_UNKNOWN)

    pivot = (
        df.pivot_table(index="year_month", columns="group", values="balance", aggfunc="sum")
        .reindex(columns=list(ALL_TYPES), fill_value=0.0)
        .fillna(0.0)
        .sort_index()
    )

    out = pd.DataFrame(index=pivot.index)
    for account_type, column in C.TYPE_TO_COLUMN.items():
        out[column] = pivot[account_type]
    if (out[C.OTHER] == 0).all():
        out = out.drop(columns=[C.OTHER])

    out[C.LIQUID] = pivot[list(LIQUID_TYPES)].sum(axis=1)
    out[C.NET_WORTH] = pivot.sum(axis=1)
    out[C.MOM_CHANGE] = out[C.NET_WORTH].diff().fillna(0.0)
    out[C.MOM_CHANGE_PCT] = out[C.NET_WORTH].pct_change().fillna(0.0)

    if monthly_spending is not None and not monthly_spending.empty:
        spend = monthly_spending.reindex(out.index)
        out[C.MY_SPENDING] = spend
        avg = spend.rolling(RUNWAY_SPEND_WINDOW_MONTHS, min_periods=1).mean()
        out[C.AVG_SPEND] = avg
        # Months of spending the Savings group could cover (emergency-fund runway)
        out[C.RUNWAY_MONTHS] = (pivot[TYPE_SAVINGS] / avg).where(avg > 0)

    out = out.round(2)
    out.index.name = C.MONTH
    return out.reset_index()


def monthly_spending_from_transactions(df: pd.DataFrame) -> pd.Series:
    """Sum my share of spending per month from generate_summaries' transaction frame.

    Uses the same definition as the Monthly Summary tab ("Total Spent (Net)" = sum of my_owed).
    """
    if df.empty:
        return pd.Series(dtype=float)
    spend = df.groupby(df["date"].dt.strftime("%Y-%m"))["my_owed"].sum()
    spend.index.name = C.MONTH
    return spend
