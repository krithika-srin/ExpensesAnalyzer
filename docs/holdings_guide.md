# Holdings and Net Worth

Tracks account balances alongside expenses. The **Money** Google Sheet stays the
place you type balances each month; this module reads it, stores snapshots in the
same SQLite DB as transactions, and writes a **Net Worth** tab.

```
Money sheet "Holdings YYYY" tabs  ->  holdings table (data/transactions.db)
holdings + transactions tables    ->  "Net Worth" tab in the Money sheet
```

## Setup

1. Share the Money sheet with the same service account used for the expenses sheet
   (the `client_email` in `config/gsheets_authentication.json`), as Editor.
2. Add the sheet key to `config/.env`:

   ```
   HOLDINGS_SPREADSHEET_KEY=<key from the Money sheet URL>
   ```

## Monthly workflow

1. Fill in the month's Ending Balance for each account in `Holdings YYYY`
   (as you do today).
2. Run your usual expense pipeline so the transactions DB is current.
3. Run:

   ```bash
   export PYTHONPATH=$(pwd)
   python src/holdings/sync_holdings.py --years 2026 --write-summary
   ```

Other options:

```bash
python src/holdings/sync_holdings.py --dry-run                 # parse every Holdings tab, print, write nothing
python src/holdings/sync_holdings.py --write-summary           # re-sync all years
python src/holdings/sync_holdings.py --write-summary --no-spending
```

## Net Worth tab columns

| Column | Meaning |
|---|---|
| Investment / Savings / Retirement / HSA | Sum of Ending Balance by the sheet's Account Type |
| Liquid (Inv + Savings) | Same as the sheet's "Grand Total" row |
| Net Worth | All account types together |
| MoM Change, MoM Change % | Change in Net Worth vs the previous month |
| My Spending | Your share of spending that month (same as Monthly Summary "Total Spent (Net)") |
| Avg Spend (3 mo) | Rolling 3-month average of My Spending |
| Savings Runway (months) | Savings balance / Avg Spend - how many months the emergency funds cover |

## How the sheet is read

- Account rows start on row 4 and stop at the first blank row or "Totals"; the totals
  block is ignored and recomputed.
- A blank Account Type inherits the type from the row above (matching the sheet layout).
- Each account is keyed as `Account | Sub-Type` (e.g. `Wealthfront | Joint Savings`).
- Months where every account is 0 or blank are treated as not yet entered and skipped.
- The header row is checked (`Jan YYYY`, `Feb YYYY`, ...); if columns move, the sync fails
  rather than storing balances under the wrong month.
- A re-sync replaces that year's rows, so edits and deletions in the sheet carry over.

## Adding accounts

Add a row inside the account block of the Holdings tab. Any Account Type other than
Investment, Savings, Retirement or Health Savings (e.g. "Real Estate" for home value, or
a negative balance row for the mortgage) is counted in an **Other** column and in Net Worth.

## Tests

```bash
pip install -r requirements-dev.txt
PYTHONPATH=. pytest tests/test_holdings.py
```
