# SplitwiseImporter

A robust, automated Python pipeline for managing personal finances by importing credit card statements, categorizing expenses, and syncing them with Splitwise and Google Sheets for budget tracking.

## Project Overview

**Architecture:**
- **Splitwise** = Source of Truth (Manual edits & split management)
- **Local SQLite Database** = Synced Mirror (Fast queries & historical archiving)
- **Google Sheets** = Viewing Layer (Formatted exports & spending analysis)

## Core Features

- **Automated Pipeline**: Single-command ETL (Extract, Transform, Load) for monthly statements.
- **Smart Categorization**: 200+ merchant mappings with interactive review and auto-correction.
- **Refund Handling**: Automatic detection and matching of refunds/credits.
- **Budget Analysis**: Detailed monthly summaries, category breakdowns, and year-over-year trends in Google Sheets.
- **Historical Archiving**: Complete transaction history (2013-2026) stored locally in SQLite.
- **Year-Based Exporting**: Clean, structured spreadsheets with separate tabs for each year.
- **Idempotent Updates**: Smart syncing ensures no duplicate entries and minimal API/Sheet writes.

## Setup
1. Create a virtual environment: `python -m venv .venv`
2. Activate the environment: `source .venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Configure environment variables:
   - Copy the template: `cp config/.env.example config/.env`
   - Open `config/.env` and add your API keys and configuration (see Environment Variables section below). Note: Make sure your `SPLITWISE_PARTNER_ID` is defined here.
5. Set up Google Sheets access:
   - Place your service account JSON file at `config/gsheets_authentication.json`
   - Share your spreadsheet with the service account email address
6. Set PYTHONPATH: `export PYTHONPATH=$PWD`

## Quick Start

### Recommended: Monthly Export Pipeline

The **Monthly Export Pipeline** is the primary, automated tool for managing your expenses. It handles several steps at once: syncing with Splitwise, importing new statements, exporting to Google Sheets, and generating budget summaries.

#### Mode 1: Full Monthly Pipeline (with Statement Import)
Use this when you have a new credit card statement to process.

```bash
# 1. Activate venv and set PYTHONPATH
source .venv/bin/activate
export PYTHONPATH=$PWD

# 2. Run the full pipeline
# This syncs DB → Imports Statement → Syncs DB Again → Exports to Sheets → Generates Summaries
python src/export/monthly_export_pipeline.py \
  --statement data/bank_statements/jan2026.csv \
  --year 2026 \
  --start-date 2026-01-01 \
  --end-date 2026-01-31
```

**What it does:**
1. **Syncs database** with latest Splitwise data to ensure no duplicates.
2. **Imports CSV statement** to Splitwise and categorizes transactions.
3. **Syncs database again** to capture the newly imported expenses.
4. **Exports to Google Sheets** (default: `Expenses 2026` worksheet).
5. **Generates Budget Summaries** (e.g., `Monthly Summary`).

#### Mode 2: Sync Only Mode (No Statement)
Use this to refresh your Google Sheets and summaries from existing Splitwise data without importing a new statement.

```bash
# Sync and export only
python src/export/monthly_export_pipeline.py --year 2026 --sync-only
```

#### Mode 3: Append Only Mode
By default, the pipeline overwrites the worksheet for a full refresh. Use `--append-only` to only add transactions that haven't been written to the sheet yet.

```bash
# Append-only export
python src/export/monthly_export_pipeline.py --year 2026 --sync-only --append-only
```

#### Dry Run
Always run with `--dry-run` first to preview changes. For **Full Monthly Pipeline** (Mode 1), the dry run will also write the parsed transactions to a dedicated Google Sheet (default: `Statement Imports`) so you can manually verify categorizations and amounts before actually adding them to Splitwise.

```bash
# Preview changes for Mode 1 - writes to "Statement Imports" worksheet
python src/export/monthly_export_pipeline.py \
  --statement data/bank_statements/jan2026.csv \
  --year 2026 \
  --start-date 2026-01-01 \
  --end-date 2026-01-31 \
  --dry-run

# Preview changes for Mode 2
python src/export/monthly_export_pipeline.py --year 2026 --sync-only --dry-run
```


### Export Options

Export from Splitwise API or database to Google Sheets:

```bash
# Export from database (recommended - faster, filtered)
python src/export/splitwise_export.py \
  --source database \
  --year 2026 \
  --worksheet "Expenses 2026" \
  --overwrite

# Export from Splitwise API (live data)
python src/export/splitwise_export.py \
  --source splitwise \
  --start-date 2026-01-01 \
  --end-date 2026-12-31 \
  --worksheet "Expenses 2026" \
  --overwrite

# Dry run to preview
python src/export/splitwise_export.py \
  --source database \
  --year 2026 \
  --dry-run
```

**Export features:**
- 12 columns: Date, Amount, Category, Description, Details (cc_ref), Split Type, Participant Names, My Paid, My Owed, My Net, Splitwise ID, Fingerprint
- Filters Payment transactions (excluded from sheets but tracked in DB)
- Overwrite mode for full refresh or default append mode


### Bulk Category Updates

Update categories for existing Splitwise expenses in bulk by merchant name or current category:

```bash
# Update all SpotHero expenses to Transportation > Parking
python src/update/bulk_update_categories.py --merchant "SpotHero" --subcategory parking

# Update Amazon (excluding AWS) to Household supplies
python src/update/bulk_update_categories.py --merchant "Amazon" --exclude "AWS" --subcategory household_supplies

# Update Costco expenses currently in "Home - Other" to Household supplies
python src/update/bulk_update_categories.py --merchant "Costco" --current-category "Home - Other" --subcategory-id 14

# Dry run to preview changes
python src/update/bulk_update_categories.py --merchant "SpotHero" --subcategory parking --dry-run

# Skip confirmation prompt
python src/update/bulk_update_categories.py --merchant "Costco" --subcategory household_supplies --yes
```

**Common Subcategory Options:**
- `parking` (ID: 9) - Transportation > Parking
- `household_supplies` (ID: 14) - Home > Household supplies
- `home_other` (ID: 28) - Home > Other
- `medical` (ID: 38) - Life > Medical expenses
- `groceries` (ID: 1) - Food and drink > Groceries
- `dining_out` (ID: 2) - Food and drink > Dining out

See `src/constants/splitwise.py` (SUBCATEGORY_IDS) for the full list of available subcategories.

Or use `--subcategory-id` with any Splitwise subcategory ID.


## Project Structure

```
SplitwiseImporter/
├── src/
│   ├── database/               # Local SQLite database layer
│   │   ├── schema.py           # Table definitions (transactions, monthly_summaries, etc.)
│   │   ├── models.py           # Transaction & ImportLog dataclasses
│   │   └── db_manager.py       # DatabaseManager with CRUD + summary methods
│   ├── db_sync/                # Database sync utilities
│   │   └── sync_from_splitwise.py # Sync DB with Splitwise (insert/update/delete)
│   ├── import_statement/       # CSV statement parsing and import pipeline
│   │   ├── pipeline.py         # Main ETL pipeline orchestrator
│   │   ├── parse_statement.py  # CSV parsing and normalization
│   │   └── categorization.py   # Transaction categorization logic
│   ├── export/                 # Splitwise data export and summaries
│   │   ├── splitwise_export.py # Fetch and export Splitwise expenses
│   │   ├── monthly_export_pipeline.py # Automated 4-step pipeline
│   │   └── generate_summaries.py # Budget analysis and spending summaries
│   ├── update/                 # Bulk update utilities
│   │   ├── update_self_expenses.py # Fix self-expense splits
│   │   └── bulk_update_categories.py # Bulk category updates
│   ├── merchant_review/        # Interactive merchant review workflow
│   │   ├── run_review_workflow.py   # Unified workflow orchestrator (NEW)
│   │   ├── generate_review_file.py  # Generate review CSV from processed data
│   │   ├── review_merchants.py      # Interactive review tool
│   │   └── apply_review_feedback.py # Apply corrections to config
│   ├── common/                 # Shared utilities
│   │   ├── splitwise_client.py # Splitwise API wrapper
│   │   ├── sheets_sync.py      # Google Sheets integration
│   │   └── utils.py            # Common helper functions (simplified merchant extraction)
│   └── constants/              # Configuration constants
├── config/                     # Credentials and mappings
│   ├── .env                    # API keys (not in git)
│   ├── merchant_category_lookup.json  # 219+ merchant→category mappings
│   ├── amex_category_mapping.json     # Amex category mappings
│   └── gsheets_authentication.json    # Google Sheets credentials
├── data/
│   ├── bank_statements/        # Credit card statements
│   ├── processed/              # Processed outputs and review files
│   └── transactions.db         # SQLite database
├── docs/                       # Documentation
└── notebooks/                  # Jupyter analysis notebooks
```


## Common Workflows

### Monthly Expense Processing Pipeline

The **Monthly Export Pipeline** is the recommended way to process new statements as it ensures all steps (syncing, importing, and exporting) are performed in the correct order.

```bash
# Process a new statement from start to finish
python src/export/monthly_export_pipeline.py \
  --statement data/raw/amex_jan2026.csv \
  --year 2026 \
  --start-date 2026-01-01 \
  --end-date 2026-01-31
```

**Why the pipeline matters:**
- **Order of Operations**: It syncs Splitwise data *before* importing to prevent duplicates from overlapping statements.
- **Retroactive Transactions**: It syncs again *after* importing to capture Splitwise IDs for the new transactions.
- **Chronological Sorting**: It uses `--overwrite` by default for exports, which re-sorts all expenses chronologically in Google Sheets.
- **Automation**: It combines 5 manual steps into a single idempotent command.

### First-Time Statement Import
1. Place your CSV statement in `data/bank_statements/`
2. Run dry-run to preview: `python src/import_statement/pipeline.py --statement data/bank_statements/statement.csv --dry-run`
3. Review merchant extractions in `data/processed/merchant_names_for_review.csv`
4. Correct any issues: `python src/merchant_review/review_merchants.py`
5. Run actual import: `python src/import_statement/pipeline.py --statement data/bank_statements/statement.csv`

### Large Statement Processing (Batch Mode)
```bash
# Process in batches of 50 transactions
python src/import_statement/pipeline.py --statement data/bank_statements/big_statement.csv --limit 50 --offset 0
python src/import_statement/pipeline.py --statement data/bank_statements/big_statement.csv --limit 50 --offset 50 --append
python src/import_statement/pipeline.py --statement data/bank_statements/big_statement.csv --limit 50 --offset 100 --append
# ... continue until done
```

### Monthly Budget Sync
```bash
# Export current month's Splitwise expenses
python src/export/splitwise_export.py --start-date 2025-01-01 --end-date 2025-01-31 --sheet-name "Jan 2025"

# Full year export with categories
python src/export/splitwise_export.py --start-date 2025-01-01 --end-date 2025-12-31 --overwrite --export-categories
```

## Configuration Files

### merchant_category_lookup.json
Maps merchant names to Splitwise categories. Auto-updated through merchant review workflow.

```json
{
  "spothero": {
    "canonical_name": "SpotHero",
    "category": "Transportation",
    "subcategory": "Parking",
    "confidence": 0.95
  }
}
```

### Environment Variables (.env)
Required API credentials and default settings:

```env
# Splitwise API
SPLITWISE_CONSUMER_KEY=your_key_here
SPLITWISE_CONSUMER_SECRET=your_secret_here
SPLITWISE_API_KEY=your_api_key_here

# Splitwise User IDs (Get these from your Splitwise profile or API)
SPLITWISE_SELF_ID=your_self_user_id_here
SPLITWISE_PARTNER_ID=your_partner_user_id_here

# Google Sheets
SPREADSHEET_KEY=your_google_sheets_key

# Default date range and worksheet (change for new year)
START_DATE=2026-01-01
END_DATE=2026-12-31
EXPENSES_WORKSHEET_NAME=Expenses 2026
DRY_RUN_WORKSHEET_NAME=Statement Imports
```

**Note:** Update `START_DATE`, `END_DATE`, and `EXPENSES_WORKSHEET_NAME` at the start of each year to automatically target the new year's data.

## Tips & Best Practices

- **Always set PYTHONPATH** before running commands: `export PYTHONPATH=$PWD`
- **Use dry-run first** to preview changes before committing to Splitwise
- **Review merchants regularly** to improve auto-categorization accuracy
- **Process large statements in batches** to handle API rate limits gracefully
- **Use --overwrite for exports** to get a clean dataset with deleted transactions filtered out
- **Check logs** in terminal output for detailed processing information
- **Follow the processing pipeline order**: Import statements to Splitwise first, then export to sheets with `--overwrite`
- **Update config/.env dates** at the start of each year (START_DATE, END_DATE, EXPENSES_WORKSHEET_NAME)

## Automation Considerations

The expense processing workflow can be automated with these steps:

1. **Statement Download**: Automate CSV download from credit card provider (or manual upload to `data/bank_statements/`)
2. **Unified Pipeline**: Run `monthly_export_pipeline.py` with the new statement.
3. **Verification**: Check logs for sync/import/export counts and any errors.

**Recommended schedule:**
- Run pipeline monthly after credit card statement is available
- Use `--overwrite` mode to handle any retroactive transactions
- Monitor merchant review file for new merchants needing categorization

**Future enhancements:**
- Cron job or GitHub Actions for scheduled execution
- Email/Slack notifications on completion or errors
- Automatic merchant review aggregation and reporting

## Troubleshooting

**Import fails with "ModuleNotFoundError"**: Set PYTHONPATH to project root (e.g., `export PYTHONPATH=$PWD`)  
**Duplicate expenses created**: Check cache in `data/splitwise_expense_details_*.json`  
**Wrong categories**: Review and correct in `config/merchant_category_lookup.json`  
**Deleted expenses appearing**: Use `--overwrite` flag when exporting to filter them out  
**Date mismatch (one day off)**: Fixed in export - dates no longer use UTC conversion  
**Category updates not reflected**: Run export with `--overwrite` after bulk updates  
**Wrong year data**: Update `START_DATE`, `END_DATE`, and `EXPENSES_WORKSHEET_NAME` in `config/.env`


