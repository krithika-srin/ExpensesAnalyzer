# ExpensesAnalyzer

A streamlined Python workflow for processing Chase bank statements, deduplicating against Google Sheets, and managing expenses with manual review for any timeframe.

## Project Overview

**Architecture:**
- **Google Sheets** = Source of Truth (Manual edits & expense tracking)
- **Sheet-First Workflow**: Interactive processing with deduplication and review steps

## Core Features

- **Interactive Expense Workflow**: Sheet-first processing for Chase statements with manual review.
- **Flexible Timeframes**: Process expenses for any year or custom date range.
- **Smart Deduplication**: Multi-layered matching using fingerprints and fuzzy logic (amount, date, merchant).
- **Category Inference**: Auto-categorization using merchant lookup and patterns.
- **Google Sheets Integration**: Direct read/write with data validation and formatting.

## Setup
1. Create a virtual environment: `python -m venv .venv`
2. Activate the environment: `source .venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Configure environment variables:
   - Create `config/.env` with your API keys (SPREADSHEET_KEY, etc.)
5. Set up Google Sheets access:
   - Place your service account JSON file at `config/gsheets_authentication.json`
   - Share your spreadsheet with the service account email address
6. Set PYTHONPATH: `export PYTHONPATH=$PWD`

## Quick Start

### Expense Processing Workflow

The primary workflow processes Chase bank statements interactively:

```bash
# Activate venv and set PYTHONPATH
source .venv/bin/activate
export PYTHONPATH=$PWD

# Run the expense workflow (defaults to current year)
python scripts/process_2025_expenses.py

# Or specify a year
python scripts/process_2025_expenses.py --year 2025
python scripts/process_2025_expenses.py --year 2026
```

**Workflow Steps:**
1. Optional: Sync Splitwise to 'Expenses {YEAR}' sheet
2. Input Chase CSV file path
3. Load existing sheet for deduplication
4. Parse, categorize, and dedupe transactions
5. Write to 'Statement Imports {YEAR}' for review
6. Manual review in Google Sheets (edit categories/status)
7. Append approved transactions to 'Expenses {YEAR}'

## File Structure

- `scripts/process_2025_expenses.py`: Main workflow script (processes any year)
- `src/common/deduplication_engine.py`: Deduplication logic
- `src/common/sheets_sync.py`: Google Sheets integration
- `src/common/utils.py`: Utilities (categorization, parsing)
- `config/`: Configuration files
- `data/bank_statements/`: Sample Chase statements

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


