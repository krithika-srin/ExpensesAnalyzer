# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Branch context

The active branch (`setup-project-krithika`) is a deliberate slim-down of `main`. Large swaths of `main` — the SQLite `database/` layer, `db_sync/`, `merchant_review/`, `update/`, `import_statement/pipeline.py`, `import_statement/categorization.py`, `process_refunds.py`, `export/monthly_export_pipeline.py`, `export/generate_summaries.py`, the entire `docs/` and `tests/` trees, and all multi-bank (Amex/BoFA) support — have been removed. `git status` lists them as deleted. **Do not re-import or reference those modules**; the working tree is the source of truth. [`.github/copilot-instructions.md`](.github/copilot-instructions.md) describes the old, richer architecture and is **out of date** for this branch.

## Common commands

```bash
# One-time setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Every shell session — required for `src.*` imports to resolve
source .venv/bin/activate
export PYTHONPATH=$PWD

# Run the main (and currently only) workflow
python scripts/process_2025_expenses.py                # current year
python scripts/process_2025_expenses.py --year 2026    # override year
```

No test suite, lint config, or build step exists on this branch — all of `tests/` was removed. The coding-style guide ([.github/coding_style.md](.github/coding_style.md)) recommends `pylint --disable=all --enable=unused-import,unused-variable src/` for dead-code detection, but pylint is not in `requirements.txt`.

## Architecture: Sheet-First workflow

The Google Sheet is the **source of truth**. There is no local database. The entire pipeline is one interactive script ([scripts/process_2025_expenses.py](scripts/process_2025_expenses.py)) coordinating three layers that together require reading multiple files to understand:

**1. Two-tab sheet model (per year).** Every year has two tabs in the spreadsheet identified by `SPREADSHEET_KEY`:
- `Expenses {YEAR}` — canonical ledger. Only approved rows live here. Columns are defined by [`ExportColumns`](src/constants/export_columns.py) (Date, Amount, Category, Subcategory, Description, Details, Split Type, Participant Names, My Paid, My Owed, My Net, Splitwise ID, Transaction Fingerprint).
- `Statement Imports {YEAR}` — review staging. The script **deletes and recreates** this tab every run (see [process_2025_expenses.py:182-187](scripts/process_2025_expenses.py#L182-L187)) to avoid stale data validation/formatting leaking between sessions. Users edit `status` and category in-sheet, then the script reads it back and appends approved rows to `Expenses {YEAR}`.

The Splitwise sync at Step 1 is optional and only used to seed/refresh `Expenses {YEAR}` from the Splitwise API before deduplication runs.

**2. Multi-layer deduplication ([src/common/deduplication_engine.py](src/common/deduplication_engine.py)).** Pre-computes fingerprints from `Expenses {YEAR}` on construction, then `find_match()` runs two layers:
- Layer 1: exact SHA-256 fingerprint match on `(date | amount.2f | description)` — see [`generate_fingerprint`](src/common/utils.py#L480) in `utils.py`.
- Layer 2: fuzzy match — same absolute amount (`np.isclose`), date within ±3 days, and substring match on cleaned descriptions.

Two non-obvious invariants:
- **Fingerprints always use `abs(amount)`** so Chase debits (sign-flipped in Step 4) and Splitwise expenses (already positive) collide correctly.
- Existing sheet amounts may be currency-formatted strings (`"$12.50"`); the engine strips `$` and `,` before numeric comparison.

**3. Chase CSV sign convention.** In Chase's CSV, sales are negative and refunds are positive. The script **negates `raw_amount`** ([process_2025_expenses.py:94-95](scripts/process_2025_expenses.py#L94)) so expenses become positive in the sheet (matching Splitwise convention). After negation: `amount < 0` means refund → status `REFUND`; payments/AT&T bill payments are forced to `SKIP` via [`is_payment_transaction`](src/common/transaction_filters.py) and the inline `att* bill payment` check.

Valid `status` values written to the review tab (also used as the dropdown validation list): `ADD`, `REFUND`, `FUZZY_MATCH`, `MATCH_FOUND`, `SKIP`. On readback, only rows with status `ADD` or `REFUND` are appended to the canonical ledger.

## Category inference chain

[`infer_category`](src/common/utils.py#L659) tries sources in this order and returns the first hit:
1. `merchant_category_lookup.json` keyed by lowercased cleaned merchant name (highest confidence).
2. Amex category from the CSV mapped via `amex_category_mapping.json` — **note this config file was deleted on this branch** but the code path remains; the loader returns `{}` and the step is effectively a no-op.
3. Regex patterns from `config/config.yaml` under `category_inference.patterns` — **also deleted on this branch**; falls through to default.
4. Default `Uncategorized` / `General` (category_id=2, subcategory_id=18).

In practice, only the merchant lookup is active. To improve auto-categorization, edit [`config/merchant_category_lookup.json`](config/merchant_category_lookup.json) — entries follow the `{normalized_name: {canonical_name, category, subcategory, confidence}}` shape.

Splitwise category IDs are resolved separately by [`_resolve_category_ids`](src/common/utils.py#L565) against [`config/splitwise_category_ids.json`](config/splitwise_category_ids.json), which holds both a full-path mapping (`"Transportation > Parking"` → IDs) and a name-only `category_lookup` used when the path is ambiguous.

## Environment and configuration

- `.env` lives at [config/.env](config/.env) (gitignored). Loaded exactly once by [`load_project_env`](src/common/env.py) via `@functools.cache`. **Never use the `global` keyword** — the codebase standardizes on `@cache` for singletons (see [coding_style.md Rule 5a](.github/coding_style.md)).
- Required env vars: `SPREADSHEET_KEY`, `SPLITWISE_CONSUMER_KEY`, `SPLITWISE_CONSUMER_SECRET`, `SPLITWISE_API_KEY`, `SPLITWISE_SELF_ID`, `SPLITWISE_PARTNER_ID`, plus `START_DATE` / `END_DATE` / `EXPENSES_WORKSHEET_NAME` (annual rotation).
- Google service-account JSON at [config/gsheets_authentication.json](config/gsheets_authentication.json) (gitignored). The spreadsheet must be shared with the service-account email.
- VS Code's [.vscode/launch.json](.vscode/launch.json) injects `config/.env` via `envFile` — do **not** pass `${env:VAR}` in `args`, those are substituted before `.env` loads.

## Project conventions ([.github/coding_style.md](.github/coding_style.md))

- Imports grouped (stdlib / third-party / local), each group alphabetized, blank line between.
- No emojis in log messages or terminal output.
- **No broad `except:` or `except ImportError`** — let unexpected errors and missing-dependency errors propagate. Catch specific exceptions (`ValueError`, `OSError`, …) only with a real recovery path.
- Pull repeated literals (worksheet names, SQL fragments, status strings) into module-level constants — see [src/constants/](src/constants/).
- Use the project `LOG` (`logging.getLogger("cc_splitwise")`, exposed from `src.common.utils`); use `LOG.exception` inside `except` blocks.
