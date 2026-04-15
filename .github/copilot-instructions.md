📘 Project Summary — Splitwise + CSV Budget & Expense Tracker
🎯 Goal of the Project

Build a Python-based workflow that:

Processes CSV credit-card/bank statements (no PDF parsing).

Identifies which expenses belong in Splitwise, and automatically adds them to Splitwise using its API.

Pulls all Splitwise expenses (yours + shared) into a structured dataframe.

Uses this data to track budget vs. actuals for the year.

Writes summary data into a Google Sheet you already use for tracking investments & finances.

Avoids complexity early — no Plaid integration for now.

Should run locally on a Chromebook using Pycharm or a Jupyter environment.

🧩 Key Components
1. CSV Statement Processing

You will download monthly statements as .csv from your unlinked credit card.

Script requirements:

Parse CSV rows.

Normalize fields (date, amount, category, merchant).

Detect which transactions need to be added to Splitwise.

Avoid duplicates—track previously inserted items.

2. Splitwise API Integration

Using the Splitwise v3 OAuth API.

You will manually generate an API key via:

https://secure.splitwise.com/apps

Create a Personal Access Token (consumer key + secret).

Script can:

Add expenses.

Fetch all Splitwise activities.

Normalize them into a pandas DataFrame for downstream use.

3. Budget vs Actual Tracking

You maintain yearly budget buckets (e.g., Food, Gas, Insurance).

Your script should:

Load a YAML/JSON budget file (e.g., budget_2025.json).

Load Splitwise expenses + your CSV bank expenses.

Categorize transactions.

Summarize monthly and yearly totals.

Output a consolidated dataframe.

4. Google Sheets Sync

Using gspread or Google Sheets API v4.

Write:

Monthly spending totals

Category breakdown

Cumulative budget vs actual charts

Sheet will update from local script execution.

5. Project Structure

Current structure (updated Jan 13, 2026 - Phase 5 Complete):

SplitwiseImporter/
├── src/
│   ├── database/               # Local SQLite database layer (Phase 1)
│   │   ├── __init__.py
│   │   ├── schema.py           # Table definitions
│   │   ├── models.py           # Transaction & ImportLog dataclasses
│   │   ├── db_manager.py       # DatabaseManager with CRUD operations
│   │   └── migrate_refund_columns.py # Schema migration for refund tracking
│   ├── db_sync/                # Unified sync utilities (Phase 1 & 2)
│   │   ├── __init__.py
│   │   └── sync_from_splitwise.py # Sync DB with Splitwise (insert/update/delete)
│   ├── import_statement/       # CSV statement parsing and import pipeline
│   │   ├── pipeline.py         # Main ETL orchestrator (Phase 2: Splitwise → DB)
│   │   ├── parse_statement.py  # CSV parsing with refund detection
│   │   ├── categorization.py   # Transaction categorization
│   │   └── process_refunds.py  # Automatic refund/credit expense creation
│   ├── export/
│   │   ├── splitwise_export.py # Unified export (Splitwise API or database)
│   │   ├── monthly_export_pipeline.py # Automated monthly workflow (import→sync→export)
│   │   └── generate_summaries.py # Budget analysis and spending pattern summaries
│   ├── update/
│   │   ├── update_self_expenses.py # Fix self-expense splits
│   │   └── bulk_update_categories.py # Bulk category updates
│   ├── merchant_review/        # Interactive merchant review workflow
│   │   ├── review_merchants.py
│   │   └── apply_review_feedback.py
│   ├── common/                 # Shared utilities
│   │   ├── splitwise_client.py # Splitwise API wrapper
│   │   ├── sheets_sync.py      # Google Sheets integration
│   │   ├── transaction_filters.py # Transaction filtering utilities (refactored)
│   │   ├── env.py              # Environment variable loading (@cache singleton)
│   │   └── utils.py            # Date utilities, logging, common helpers
│   └── constants/              # Configuration constants
│       ├── config.py           # Project paths and configuration
│       ├── export_columns.py   # Google Sheets column definitions
│       ├── gsheets.py          # Worksheet names and sheet constants
│       ├── logging_config.py   # Logging configuration
│       └── splitwise.py        # Splitwise API constants (split types, categories, etc.)
├── config/
│   ├── .env                    # API keys & default settings
│   ├── merchant_category_lookup.json  # 219+ merchant mappings
│   ├── amex_category_mapping.json
│   └── gsheets_authentication.json
├── data/
│   ├── bank_statements/         # Bank statement CSV files - create subdirectories as needed:
│   │   ├── american express/   # American Express credit card statements
│   │   └── bank of america/    # Bank of America credit card/checking statements
│   ├── processed/              # Processed outputs
│   └── transactions.db         # SQLite database (4,889 transactions)
└── docs/
    ├── database_sync_guide.md  # Complete database & sync guide (Phase 1 & 2)
    └── ...

**Removed Files (Phase 2 cleanup):**
- review.sh (merchant review complete with 216+ merchants)
- data/splitwise_cache.json (replaced with database duplicate detection)
- src/constants/config.py:CACHE_PATH (no longer needed)

🤖 AI Workflow
You are using:

Windsurf (Codeium) with free SWE-1 model.

Also optionally Claude Haiku 4.5 or GPT-4.1 as your free assistant depending on the editor.

Goal is to feed Copilot/Windsurf the context so it can help you write the code.

This summary provides everything Copilot needs.

📝 Current Status (What Has Been Completed)

✅ **Phase 1: Local Database as Source of Truth (Complete - Jan 2026)**
- SQLite database (`data/transactions.db`) - Canonical source for all transactions
- Database schema with comprehensive transaction model (deduplication, source tracking, sync status)
- DatabaseManager API for CRUD operations
- Direct Splitwise API migration tool (4,889 transactions imported: 2013-2026)
- Google Sheets positioned as "view cache" not primary ledger
- Import audit trail with import_log table

✅ **Phase 2: Splitwise-First Import Pipeline (Complete - Jan 12, 2026)**
- Import pipeline saves to database after successful Splitwise API creation
- Splitwise is source of truth - database reflects Splitwise state
- Sync script (`src/db_sync/sync_from_splitwise.py`) to pull updates/deletes from Splitwise
- DatabaseManager extended with sync methods (update_transaction_from_splitwise, mark_deleted_by_splitwise_id)
- Manual Splitwise edits (splits, deletes, categories) can be synced back to database
- Workflow: CSV → Splitwise → Database → [manual edits in Splitwise] → Sync back to DB
- JSON cache removed - pure database-driven duplicate detection by cc_reference_id
- Category inference runs for all transactions (including duplicates) for proper sheet reporting
- Fixed duplicate detection to only check cc_reference_id (allows legitimate duplicate transactions)

✅ **Core Infrastructure**
- Set up development environment on Chromebook using Linux/PyCharm
- Created modular project structure with `src/` subdirectories
- Implemented SplitwiseClient wrapper with API integration, caching, and deleted expense filtering
- Built Google Sheets sync functionality with gspread
- CSV parsing and normalization for credit card statements

✅ **Import Pipeline**
- Full ETL pipeline for importing credit card statements to Splitwise
- Batch processing support (`--limit`, `--offset`, `--append`)
- Merchant filtering for selective reprocessing (`--merchant-filter`)
- Duplicate detection using local cache and remote API checks
- Auto-categorization using merchant lookup with 216+ merchants configured
- Interactive merchant review workflow for improving extraction accuracy
- **Automatic refund/credit processing** - Detects credits in statements and creates Splitwise expenses
- **Refund tracking** - 8 database columns for reconciliation (cc_reference_id, refund_for_txn_id, etc.)
- **Simplified refund creation** - Creates refunds with original statement description, no transaction matching

✅ **Export & Sync**
- Export Splitwise expenses to Google Sheets with filtering
- Deleted transaction filtering (DELETED_AT_FIELD constant)
- Payment and settlement filtering (excludes "Settle all balances", "Payment")
- Zero-participation filtering (excludes expenses where user not involved)
- Date formatting fixed (removed UTC timezone conversion to prevent date shifts)
- Support for both append and overwrite modes

✅ **Bulk Updates**
- Bulk category updates script (src/update/bulk_update_categories.py) for updating expenses by merchant/category
- Self-expense split fixing (50/50 → 100% owed) via update_self_expenses.py
- Category reassignment workflows (SpotHero → Parking, Amazon → Household supplies, Costco → Household supplies)
- Support for predefined subcategory names (parking, household_supplies, medical, etc.)

✅ **Configuration & Data**
- Merchant category lookup with 216+ merchants
- Category mappings: Transportation/Parking, Home/Household supplies, etc.
- 2025 data fully imported (4,872 Splitwise expenses in database)
- 2026 data imported (45 Splitwise expenses in database)
- Now tracking 2026 expenses in new "Expenses 2026" sheet tab

**Recent Session Changes (Jan 13, 2026 - Phase 6 Complete)**
- ✅ Created `generate_summaries.py` with 5 analysis types (Monthly Summary, Category Breakdown, Budget vs Actual, Monthly Trends, Category x Month)
- ✅ Created `budget_2026.json` with $113,517 annual budget across 32 Splitwise categories
- ✅ Implemented smart category mapping (20+ mappings from transaction categories to Splitwise budget format)
- ✅ Fixed Google Sheets API error by adding `skip_formatting` parameter to `write_to_sheets()`
- ✅ Integrated summary generation as Step 4 in monthly export pipeline
- ✅ Pipeline now runs: Import → Sync → Export → Generate Summaries (4 steps)
- ✅ Budget vs Actual analysis shows variance % and over/under budget status
- ✅ January 2026 analysis: 42 transactions, $4,273 spent, 96% under budget
- ✅ Only writes Monthly Summary sheet (other sheets available but not enabled)
- ✅ **Database-backed summaries** - Monthly summaries cached in `monthly_summaries` table for fast comparison
- ✅ **Idempotent updates** - Only updates sheets when data actually changes (0.01 tolerance)
- ✅ **Constants organization** - Moved worksheet constants to `src/constants/gsheets.py`
- ✅ **Exception handling** - Removed try-catch blocks to fail fast (follows coding_style.md)
- ✅ **Append-only mode** - Transactions and summaries only write new/changed data
- ✅ **Historical backfill** - Synced 2,377 transactions from 2013-2024 Splitwise data
- ✅ **Year-based tabs** - Exported 14 separate "Expenses YYYY" sheets (2013-2026, 4,889 total transactions)
- ✅ **Code cleanup** - Moved REFUND_KEYWORDS to constants, fixed import organization per coding_style.md
- ✅ **Split type constants** - Added SPLIT_TYPE_SELF, SPLIT_TYPE_SPLIT, SPLIT_TYPE_SHARED, SPLIT_TYPE_PARTNER to constants/splitwise.py

✅ **Phase 6: Code Refactoring & Quality Improvements (Complete - Jan 13, 2026)**
- **Eliminated 50+ code duplications** across 9 categories:
  - Date parsing/formatting (12+ duplicates → 2 utility functions)
  - SQL deletion filters (18 duplicates → 1 helper method)
  - Environment loading (8 duplicates → 1 cached function)
  - Transaction filtering (15+ duplicates → 5 filter functions)
  - Factory methods for DB and Splitwise client (10+ duplicates → 2 factory functions)
- **New utility modules created**:
  - `src/common/env.py` - Centralized environment loading with @cache singleton
  - `src/common/transaction_filters.py` - Transaction filtering utilities (renamed from filters.py)
  - Date utilities in `src/common/utils.py` - parse_date_string(), format_date()
- **Eliminated all `global` keywords** - Unified to @functools.cache pattern for singletons
- **Consistent singleton pattern** - Both DatabaseManager and environment loading use @cache decorator
- **SQL query refactoring** - Added DELETED_FILTER_CLAUSE constant and _append_deleted_filter() helper
- **Updated coding standards** - Enhanced Rule 5a (no global), Rule 5 (SQL fragments as constants), Rule 8 (descriptive naming)
- **Code duplication reduction**: 83-94% reduction across different categories
- **Improved maintainability** - Single source of truth for repeated logic, easier testing, clearer code structure
- **Dead code elimination**: Removed 21 unused imports, 6 unused variables, 4 lines commented code
- **Perfect pylint score**: Achieved 10.00/10 rating with zero warnings
- **Automated quality checks**: Use `pylint --disable=all --enable=unused-import,unused-variable src/` to detect unused code

✅ **Phase 3: Google Sheets Export & Monthly Pipeline (Complete - Jan 12, 2026)**
- Unified export script supports both Splitwise API and database sources
- Database export with full 12-column format matching Splitwise API
- Payment transaction filtering (excluded from sheets but kept in DB)
- Simplified details column (only cc_reference_id or blank)
- Sync script updates payment information from Splitwise API
- **Automated monthly pipeline** - Single command runs import → sync → export
- **Append-only mode** - Tracks written_to_sheet flag, only exports new transactions
- Column order: Date, Amount, Category, Description, Details, Split Type, Participant Names, My Paid, My Owed, My Net, Splitwise ID, Transaction Fingerprint

✅ **Phase 4: Budget Tracking & Analysis (Complete - Jan 13, 2026)**
- Budget summary generation integrated into monthly pipeline as Step 4
- 5 analysis types: Monthly Summary, Category Breakdown, Budget vs Actual, Monthly Trends, Category x Month
- Smart category mapping (20+ transaction categories → Splitwise budget format)
- Budget configuration in `config/budget_2026.json` ($113,517 annual budget across 32 categories)
- Monthly Summary sheet: Month, Total Spent, Avg Transaction, Transaction Count, Total Paid, Total Owed, Cumulative Spending, MoM Change
- Enhanced `write_to_sheets()` with `skip_formatting` parameter to prevent API errors on non-transaction sheets
- **4-step automated pipeline** - Import → Sync → Export → Generate Summaries
- Budget vs Actual analysis with variance % and over/under budget status
- Spending pattern insights with 3-month rolling averages and YTD trends
- **Database-backed summaries** - `monthly_summaries` table caches computed values for fast comparison
- **Idempotent updates** - Compares database values, only updates sheets when data changes (0.01 tolerance)
- **Fail-fast error handling** - Removed try-catch blocks, exceptions bubble up immediately
- **Append-only sheets** - Both transactions and summaries only write new/changed rows

✅ **Phase 5: Refund/Credit Processing (Complete - Jan 13, 2026)**
- **Automatic refund detection** - Parser identifies credits via keywords (refund, credit, return) excluding payments
- **Database schema** - 8 refund tracking columns (cc_reference_id, refund_for_txn_id, refund_for_splitwise_id, etc.)
- **Schema migration** - Idempotent migration script in `src/database/migrate_refund_columns.py`
- **RefundProcessor** - Simplified processor creates Splitwise expenses with original statement description
- **No matching logic** - User can manually categorize/link refunds in Splitwise UI
- **UUID generation** - Creates unique cc_reference_id for refunds without statement reference
- **Split logic** - SELF paid 100%, SELF_EXPENSE owes 100% (tracks credits back to self)
- **Batch processing** - Only processes refunds from current import batch to prevent duplicates
- **Database reconciliation** - Notes field stores cc_reference_id for sheet export

🚀 Next Steps - Future Phases

**Alerting & Notifications:**
- Alert thresholds for over-budget categories
- Email/Slack notifications for budget warnings
- Monthly spending summary reports

**Automation:**
- GitHub Actions or cron-based scheduled runs
- Automatic statement download integration
- End-to-end monthly workflow automation

See `docs/database_sync_guide.md` for Phase 1 & 2 architecture details.

**Workflow - Automated Monthly Pipeline (Recommended)**

The automated pipeline runs all four steps in sequence:

```bash
# Full pipeline: Import new statement → Sync DB → Export to sheets → Generate summaries
export PYTHONPATH=/home/balaji94/PycharmProjects/SplitwiseImporter
python src/export/monthly_export_pipeline.py \
  --statement data/bank_statements/american\ express/jan2026.csv \
  --year 2026 \
  --start-date 2026-01-01 \
  --end-date 2026-01-31

# Sync and export only (no new statement)
python src/export/monthly_export_pipeline.py --year 2026 --sync-only

# Append-only mode (only export unwritten transactions)
python src/export/monthly_export_pipeline.py --year 2026 --sync-only --append-only

# Dry run to preview all changes
python src/export/monthly_export_pipeline.py \
  --statement data/bank_statements/bank\ of\ america/jan2026.csv \
  --year 2026 \
  --dry-run
```

**Pipeline Steps:**
1. **Import** - Parse CSV and add transactions to Splitwise (optional, skipped with --sync-only)
2. **Sync** - Pull updates/deletes from Splitwise to database, populate payment info
3. **Export** - Write transactions to Google Sheets (overwrite or append mode)
4. **Summaries** - Generate Monthly Summary with budget analysis (now runs with `--all-time` full rewrite instead of merging)

**Key Features & Recent Fixes (Phase 7 - March 2026):**
- **Bank-Specific Credit Detection:** Amex defines credits as `<0`, but BoFA defines credits (payments/refunds) as `>0`. Both are parsed natively and handled accurately.
- **Strict Non-Refund Dropping:** We universally filter out non-refund statement credits (like payments to the bank) explicitly via `is_credit & ~is_refund` logic rather than relying on brittle description regex.
- **Reference ID Regex Extraction:** `cc_reference_id` parsing strictly handles 6-25 digit boundaries rather than incorrectly grabbing multiline fallback text strings.
- **Keyword Boundary Handling:** Refined the logic that matches the word "refund" inside Splitwise descriptions so that companies with "refund" arbitrarily in their name (e.g. `Richyrefund`) aren't falsely flagged as literal refunds and flipped to negative. 
- **Google Sheets Format Persistence:** Implemented custom format applications (`$`, `%`) inside `write_to_sheets` during summary generation to prevent the Google Sheets API from stripping formats when cells are refreshed via data overwrites.
- **Full History Summations:** Upgraded `monthly_export_pipeline.py` to always run the Monthly Summary with the `--all-time` flag, completely overwriting the historical Google Sheet rather than awkwardly merging history rows.

Environment / Running Locally
--------------------------------
- **CRITICAL: Always activate virtualenv first:** AI agents MUST activate the project's Python virtual environment BEFORE running any Python commands, installing packages, or executing scripts. This prevents installing packages in the wrong environment and ensures all dependencies are available. Example: `source .venv/bin/activate`
- **CRITICAL: Set PYTHONPATH:** When running Python scripts from the terminal, ALWAYS set `PYTHONPATH` to the project root to ensure `src` module imports work correctly. Example: `PYTHONPATH=/home/balaji94/PycharmProjects/SplitwiseImporter python src/import_statement/pipeline.py`
- **Package Installation:** AI agents should NEVER run `pip install` commands without first activating the virtual environment. Always use the pattern: `source .venv/bin/activate && pip install <package>`
- **VS Code Environment Variables:** The `.vscode/launch.json` is set to pass `"envFile": "${workspaceFolder}/config/.env"`, which injects variables (e.g. `DRY_RUN_WORKSHEET_NAME`) at runtime inside the script. AVOID passing `${env:VAR_NAME}` explicitly inside `"args"` in `launch.json`, as VS Code will substitute them with an empty string before parsing if the host VS Code window hasn't loaded the `.env` file first.
- **VS Code Settings:** Ensure `"python.terminal.useEnvFile": true` and `"python.envFile": "${workspaceFolder}/config/.env"` are in your `.vscode/settings.json` so the integrated terminal auto-sources secrets.
