"""Constants for the holdings / net worth module.

The holdings source of truth is the "Money" Google Sheet, which has one
"Holdings YYYY" tab per year laid out as:

    Row 1: free-text note
    Row 2: Account | Account Type | Sub-Type | Jan YYYY | | Feb YYYY | | ...
    Row 3:         |              |          | Beginning Balance | Ending Balance | ...
    Row 4+: one row per account, until the first blank row
    Then:   "Totals" block (ignored - we recompute totals)

"Account Type" is only filled on the first row of each group, so blank
values inherit the type from the row above.
"""

# Environment variable holding the "Money" spreadsheet key
HOLDINGS_SPREADSHEET_KEY_ENV = "HOLDINGS_SPREADSHEET_KEY"

# Tab naming
HOLDINGS_WORKSHEET_PREFIX = "Holdings "
WORKSHEET_NET_WORTH = "Net Worth"

# Layout of a Holdings YYYY tab (0-based indexes into the values grid)
HEADER_ROW_INDEX = 1  # "Account | Account Type | Sub-Type | Jan YYYY ..."
FIRST_ACCOUNT_ROW_INDEX = 3
COL_ACCOUNT = 0
COL_ACCOUNT_TYPE = 1
COL_SUB_TYPE = 2
FIRST_MONTH_COL = 3  # Jan beginning balance; Jan ending balance is +1
COLS_PER_MONTH = 2
MONTHS_PER_YEAR = 12

# Marker for where the account rows stop and the totals block begins
TOTALS_MARKER = "totals"

# Account type groups (as written in the sheet's "Account Type" column)
TYPE_INVESTMENT = "Investment"
TYPE_SAVINGS = "Savings"
TYPE_RETIREMENT = "Retirement"
TYPE_HSA = "Health Savings"
TYPE_UNKNOWN = "Other"

# Which groups count as "liquid" (reachable without penalty).
# Matches the sheet's own "Grand Total" row (Investment + Savings).
LIQUID_TYPES = (TYPE_INVESTMENT, TYPE_SAVINGS)
ALL_TYPES = (TYPE_INVESTMENT, TYPE_SAVINGS, TYPE_RETIREMENT, TYPE_HSA, TYPE_UNKNOWN)

# Source tag written into the holdings table
SOURCE_MONEY_SHEET = "money_sheet"

# Month format used across the DB and summary sheet
YEAR_MONTH_FORMAT = "%Y-%m"

# How many trailing months of spending to average for the runway metric
RUNWAY_SPEND_WINDOW_MONTHS = 3

# Net Worth summary column names
class NetWorthColumns:
    """Column names for the Net Worth summary tab."""

    MONTH = "Month"
    INVESTMENT = "Investment"
    SAVINGS = "Savings"
    RETIREMENT = "Retirement"
    HSA = "HSA"
    OTHER = "Other"
    LIQUID = "Liquid (Inv + Savings)"
    NET_WORTH = "Net Worth"
    MOM_CHANGE = "MoM Change"
    MOM_CHANGE_PCT = "MoM Change %"
    MY_SPENDING = "My Spending"
    AVG_SPEND = "Avg Spend (3 mo)"
    RUNWAY_MONTHS = "Savings Runway (months)"

    CURRENCY = (
        INVESTMENT,
        SAVINGS,
        RETIREMENT,
        HSA,
        OTHER,
        LIQUID,
        NET_WORTH,
        MOM_CHANGE,
        MY_SPENDING,
        AVG_SPEND,
    )

    TYPE_TO_COLUMN = {
        TYPE_INVESTMENT: INVESTMENT,
        TYPE_SAVINGS: SAVINGS,
        TYPE_RETIREMENT: RETIREMENT,
        TYPE_HSA: HSA,
        TYPE_UNKNOWN: OTHER,
    }
