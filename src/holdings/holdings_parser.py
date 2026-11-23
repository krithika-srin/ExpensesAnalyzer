"""Parse a "Holdings YYYY" tab from the Money sheet into balance snapshots.

This module is pure (no network, no DB) so it can be unit tested with a
plain list-of-lists grid, exactly as the Sheets API returns it.
"""

# Standard library
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional

# Local application
from src.constants.holdings import (
    COL_ACCOUNT,
    COL_ACCOUNT_TYPE,
    COL_SUB_TYPE,
    COLS_PER_MONTH,
    FIRST_ACCOUNT_ROW_INDEX,
    FIRST_MONTH_COL,
    HEADER_ROW_INDEX,
    MONTHS_PER_YEAR,
    SOURCE_MONEY_SHEET,
    TOTALS_MARKER,
    TYPE_UNKNOWN,
    YEAR_MONTH_FORMAT,
)

# "$1,234.56", "-$1,234.56", "(1,234.56)", "1234" -> float
_CURRENCY_STRIP_PATTERN = re.compile(r"[$,\s]")
_HEADER_MONTH_FORMAT = "%b %Y"


@dataclass
class HoldingSnapshot:
    """One account's balances for one month."""

    year_month: str  # YYYY-MM
    account: str
    account_type: str
    sub_type: str
    beginning_balance: Optional[float]
    ending_balance: Optional[float]
    source: str = SOURCE_MONEY_SHEET

    @property
    def account_key(self) -> str:
        """Stable identifier: account name + sub-type (e.g. 'Wealthfront | IRA')."""
        if self.sub_type:
            return f"{self.account} | {self.sub_type}"
        return self.account

    def to_dict(self) -> dict:
        data = asdict(self)
        data["account_key"] = self.account_key
        return data


def parse_amount(raw) -> Optional[float]:
    """Convert a formatted sheet cell to a float. Blank cells return None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = _CURRENCY_STRIP_PATTERN.sub("", text.strip("()"))
    if not text or text == "-":
        return None
    value = float(text)
    return -value if negative else value


def _cell(row: List, index: int) -> str:
    return str(row[index]).strip() if index < len(row) and row[index] is not None else ""


def _parse_header_months(header_row: List, year: int) -> List[str]:
    """Return YYYY-MM for each month column, validated against the header labels."""
    months = []
    for month_index in range(MONTHS_PER_YEAR):
        col = FIRST_MONTH_COL + month_index * COLS_PER_MONTH
        label = _cell(header_row, col)
        expected = datetime(year, month_index + 1, 1)
        if label:
            parsed = datetime.strptime(label, _HEADER_MONTH_FORMAT)
            if (parsed.year, parsed.month) != (expected.year, expected.month):
                raise ValueError(
                    f"Header column {col} says '{label}', expected "
                    f"'{expected.strftime(_HEADER_MONTH_FORMAT)}' - has the layout changed?"
                )
        months.append(expected.strftime(YEAR_MONTH_FORMAT))
    return months


def _is_end_of_accounts(row: List) -> bool:
    account = _cell(row, COL_ACCOUNT)
    return not account or account.lower() == TOTALS_MARKER


def parse_holdings_grid(values: List[List], year: int) -> List[HoldingSnapshot]:
    """Parse the raw values of a Holdings YYYY tab.

    Args:
        values: Grid of cell values (formatted strings), row-major
        year: The tab's year

    Returns:
        Snapshots for every account x month that has at least one balance filled in.
    """
    if len(values) <= HEADER_ROW_INDEX:
        raise ValueError(f"Holdings {year} tab is empty or missing its header row")

    months = _parse_header_months(values[HEADER_ROW_INDEX], year)
    snapshots: List[HoldingSnapshot] = []
    current_type = TYPE_UNKNOWN

    for row in values[FIRST_ACCOUNT_ROW_INDEX:]:
        if _is_end_of_accounts(row):
            break

        # Account Type is only written on the first row of each group
        row_type = _cell(row, COL_ACCOUNT_TYPE)
        if row_type:
            current_type = row_type

        for month_index, year_month in enumerate(months):
            begin_col = FIRST_MONTH_COL + month_index * COLS_PER_MONTH
            beginning = parse_amount(row[begin_col] if begin_col < len(row) else None)
            ending = parse_amount(row[begin_col + 1] if begin_col + 1 < len(row) else None)
            if beginning is None and ending is None:
                continue
            snapshots.append(
                HoldingSnapshot(
                    year_month=year_month,
                    account=_cell(row, COL_ACCOUNT),
                    account_type=current_type,
                    sub_type=_cell(row, COL_SUB_TYPE),
                    beginning_balance=beginning,
                    ending_balance=ending,
                )
            )

    return drop_unfilled_months(snapshots)


def drop_unfilled_months(snapshots: List[HoldingSnapshot]) -> List[HoldingSnapshot]:
    """Drop months where every account is zero/blank.

    The sheet pre-fills future months with 0.00, which would otherwise look
    like a net worth crash. A month counts as filled if any account has a
    non-zero ending (or beginning) balance.
    """
    filled = {
        s.year_month
        for s in snapshots
        if (s.ending_balance or 0) != 0 or (s.beginning_balance or 0) != 0
    }
    return [s for s in snapshots if s.year_month in filled]
