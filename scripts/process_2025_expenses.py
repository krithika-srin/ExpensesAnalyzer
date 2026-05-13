#!/usr/bin/env python3
"""Interactive Expense Workflow (Sheet-First).

Workflow:
1. (Optional) Export transactions from Splitwise to 'Expenses {YEAR}' Google Sheet.
2. Prompt for Chase statement CSV.
3. Read 'Expenses {YEAR}' and build fingerprints for deduplication.
4. Parse, categorize, and dedupe Chase transactions against the sheet.
5. Add new transactions to 'Statement Imports {YEAR}' tab for review.
6. Wait for user to review/update 'Statement Imports {YEAR}' (SKIP or category changes).
7. Append approved transactions from 'Statement Imports {YEAR}' to 'Expenses {YEAR}'.
"""

import argparse
import os
import sys
import pandas as pd
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.common.env import load_project_env
from src.common.utils import LOG, generate_fingerprint, infer_category, clean_merchant_name
from src.export.splitwise_export import fetch_and_write
from src.common.sheets_sync import read_from_sheets, write_to_sheets
from src.import_statement.parse_statement import parse_statement
from src.constants.export_columns import ExportColumns
from src.common.deduplication_engine import DeduplicationEngine
from src.common.transaction_filters import is_payment_transaction, is_excluded_description

load_project_env()

def main(year=None):
    sheet_key = os.getenv("SPREADSHEET_KEY")
    
    # Use provided year or default to current year
    if year is None:
        year = datetime.now().year
    
    expenses_worksheet = f"Expenses {year}"
    imports_worksheet = f"Statement Imports {year}"

    if not sheet_key:
        print("Error: SPREADSHEET_KEY not found in .env")
        return

    print(f"\n--- Step 1: Initial Sync (Optional) ---")
    sync_choice = input(f"Do you want to refresh '{expenses_worksheet}' from Splitwise first? (y/n): ").lower()
    if sync_choice == 'y':
        print(f"Exporting Splitwise {year} transactions to '{expenses_worksheet}'...")
        try:
            fetch_and_write(
                start_date=f"{year}-01-01",
                end_date=f"{year}-12-31",
                sheet_key=sheet_key,
                worksheet_name=expenses_worksheet,
                append=False # Full refresh
            )
            print("Splitwise sync complete.")
        except Exception as e:
            print(f"\n⚠️  Splitwise sync failed: {e}")
            print("Continuing with existing sheet data...\n")

    print(f"\n--- Step 2: Prompt for Chase Statement ---")
    statement_path = input("Enter the path to your Chase statement CSV file: ").strip().strip("'\"")
    if not os.path.exists(statement_path):
        print(f"Error: File not found at {statement_path}")
        return

    print(f"\n--- Step 3: Reading '{expenses_worksheet}' for Deduplication ---")
    existing_df = read_from_sheets(sheet_key, expenses_worksheet)
    if existing_df is not None and not existing_df.empty:
        print(f"Loaded {len(existing_df)} existing transactions from sheet.")

    print(f"\n--- Step 4: Parsing & Deduping Chase Statement ---")
    chase_df = parse_statement(statement_path)
    if chase_df is None or chase_df.empty:
        print("No transactions found in statement.")
        return

    # Initialize Deduplication Engine
    engine = DeduplicationEngine(existing_df)

    results = []
    new_count = 0
    dup_count = 0

    for _, row in chase_df.iterrows():
        date = row.get('date')
        
        # User requested: Sales are -ve and refunds are +ve in the CSV.
        # We want Expenses to be positive in the sheet, so we negate the amount.
        raw_amount = float(row.get('amount', 0))
        amount = -raw_amount
        
        tx_type = str(row.get('type', '')).lower()
        desc_raw = row.get('description', '')
        
        # Clean description
        desc_clean = clean_merchant_name(desc_raw)
        
        # Logic for Deduplication (Multi-layered)
        # Using the absolute amount for matching as per deduplication logic
        match = engine.find_match(date, abs(amount), desc_raw)
        
        status = "ADD"
        if amount < 0:
            status = "REFUND"
            
        if match:
            status = "MATCH_FOUND" if match["match_type"] == "EXACT" else "FUZZY_MATCH"
            dup_count += 1
        
        # Rule: Exclude payments and specific merchants (like AT&T)
        is_payment = tx_type == 'payment' or is_payment_transaction(desc_raw) or is_excluded_description(desc_raw) or 'att* bill payment' in desc_raw.lower()
        if is_payment:
            if status not in ["ADD", "REFUND"]: dup_count -= 1 # Don't count as duplicate if we are skipping anyway
            status = "SKIP"
            
        if status in ["ADD", "REFUND"]:
            new_count += 1
            
        # Infer category
        cat_info = infer_category({
            "description": desc_raw,
            "merchant": desc_clean,
            "amount": amount
        })
        
        # Generate fingerprint for the record — always abs() to match Splitwise convention
        amount_abs = abs(amount)
        fp = generate_fingerprint(date, amount_abs, desc_clean)
        
        # Clean subcategory
        subcat = cat_info.get("subcategory_name", "General")
        if str(subcat).endswith("- Other"):
            subcat = "Other"
        
        results.append({
            ExportColumns.DATE: date,
            ExportColumns.AMOUNT: amount_abs,
            ExportColumns.CATEGORY: cat_info.get("category_name", "Uncategorized"),
            ExportColumns.SUBCATEGORY: subcat,
            ExportColumns.DESCRIPTION: desc_clean,
            "description_raw": desc_raw,
            "status": status,
            ExportColumns.FINGERPRINT: fp,
            "category_id": cat_info.get("category_id"),
            "subcategory_id": cat_info.get("subcategory_id")
        })

    print(f"Processed {len(results)} transactions: {new_count} new, {dup_count} duplicates.")

    print(f"\n--- Step 5: Updating '{imports_worksheet}' for Review ---")
    results_df = pd.DataFrame(results)
    print(f"Parsed {len(results_df)} statement rows into review results.")
    if not results_df.empty and "status" in results_df.columns:
        status_counts = results_df["status"].value_counts(dropna=False).to_dict()
        print(f"Status distribution: {status_counts}")
    
    # Ensure column order is clean for review — no internal fields
    cols_order = [
        ExportColumns.DATE,
        ExportColumns.AMOUNT,
        ExportColumns.CATEGORY,
        ExportColumns.SUBCATEGORY,
        ExportColumns.DESCRIPTION,
        "status",
        ExportColumns.FINGERPRINT
    ]
    # Filter for columns that actually exist
    cols_order = [c for c in cols_order if c in results_df.columns]
    results_df = results_df[cols_order]

    # Delete and recreate the Statement Imports tab to guarantee a clean slate
    # (avoids leftover data validation / currency formatting from old sessions)
    import pygsheets
    from src.common.sheets_sync import SHEETS_AUTHENTICATION_FILE
    gc = pygsheets.authorize(service_account_file=SHEETS_AUTHENTICATION_FILE)
    spreadsheet = gc.open_by_key(sheet_key)
    try:
        old_ws = spreadsheet.worksheet_by_title(imports_worksheet)
        spreadsheet.del_worksheet(old_ws)
    except Exception:
        pass  # Sheet didn't exist — that's fine
    new_ws = spreadsheet.add_worksheet(imports_worksheet, rows=len(results_df)+1, cols=len(results_df.columns))
    new_ws.set_dataframe(results_df, (1, 1), copy_head=True, copy_index=False)
    print(f"Wrote {len(results_df)} rows to '{imports_worksheet}' in spreadsheet {sheet_key}.")
    
    # Apply Data Validation
    # Get total rows
    num_rows = len(results_df) + 1
    if num_rows > 1:
        # Category is C (col 3), Subcategory is D (col 4), status is F (col 6)
        # Assuming the exact positions based on cols_order (A=Date, B=Amount, C=Category, D=Subcategory, E=Description, F=status, G=Fingerprint)
        try:
            # Data validation for Category and Subcategory from Category Source
            new_ws.set_data_validation(start='C2', end=f'C{num_rows}', condition_type='ONE_OF_RANGE', condition_values=['=\'Category Source\'!$C$2:$C'])
            new_ws.set_data_validation(start='D2', end=f'D{num_rows}', condition_type='ONE_OF_RANGE', condition_values=['=\'Category Source\'!$D$2:$D'])
            
            # Data validation for status
            status_values = ['ADD', 'REFUND', 'FUZZY_MATCH', 'MATCH_FOUND', 'SKIP']
            new_ws.set_data_validation(start='F2', end=f'F{num_rows}', condition_type='ONE_OF_LIST', condition_values=status_values)
        except Exception as e:
            print(f"Warning: Could not set data validation: {e}")

    print(f"Preview written to '{imports_worksheet}'.")

    print(f"\n--- Step 6: Manual Review ---")
    print(f"Please check the '{imports_worksheet}' tab in your Google Sheet.")
    print("1. Set 'status' to 'SKIP' for any transactions you want to ignore.")
    print("2. Verify/Correct the 'Category' and 'subcategory_name'.")
    input("\nPress Enter once you have finished the review and are ready to append to 'Expenses 2025'...")

    print(f"\n--- Step 7: Appending to '{expenses_worksheet}' ---")
    review_df = read_from_sheets(sheet_key, imports_worksheet)
    if review_df is None or review_df.empty:
        print("Could not read back the review sheet.")
        return

    # Filter for approved transactions
    to_append = review_df[
        review_df['status'].str.upper().isin(['ADD', 'REFUND'])
    ].copy()

    if to_append.empty:
        print("No new transactions to append.")
    else:
        # Prepare for Expenses sheet format (matches ExportColumns)
        # We need to map subcategory_name into the Category column if desired, 
        # but the standard export often just uses the Category name or path.
        # Let's keep it simple and just use the columns the Expenses sheet expects.
        
        # Select and rename columns to match the Expenses 2025 tab structure
        final_append = pd.DataFrame()
        final_append[ExportColumns.DATE] = to_append[ExportColumns.DATE]
        final_append[ExportColumns.AMOUNT] = to_append[ExportColumns.AMOUNT]
        
        # If user updated subcategory, maybe combine them? 
        # For now, let's just use the Category column as they edited it.
        final_append[ExportColumns.CATEGORY] = to_append[ExportColumns.CATEGORY]
        
        # Add Subcategory support
        subcat = to_append[ExportColumns.SUBCATEGORY] if ExportColumns.SUBCATEGORY in to_append.columns else "General"
        # Clean any "- Other" values in Subcategory
        final_append[ExportColumns.SUBCATEGORY] = subcat.apply(lambda x: "Other" if str(x).endswith("- Other") else x)
        
        final_append[ExportColumns.DESCRIPTION] = to_append[ExportColumns.DESCRIPTION]
        final_append[ExportColumns.DETAILS] = "" # No Splitwise ID
        final_append[ExportColumns.SPLIT_TYPE] = "self"
        final_append[ExportColumns.PARTICIPANT_NAMES] = ""
        final_append[ExportColumns.MY_PAID] = to_append[ExportColumns.AMOUNT]
        final_append[ExportColumns.MY_OWED] = to_append[ExportColumns.AMOUNT]
        final_append[ExportColumns.MY_NET] = 0.0
        final_append[ExportColumns.ID] = ""
        final_append[ExportColumns.FINGERPRINT] = to_append[ExportColumns.FINGERPRINT]

        write_to_sheets(
            final_append,
            worksheet_name=expenses_worksheet,
            spreadsheet_key=sheet_key,
            append=True
        )
        print(f"Successfully appended {len(final_append)} transactions to '{expenses_worksheet}'.")

    print("\nWorkflow complete! Your spreadsheet is the Source of Truth.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Interactive expense workflow for processing bank statements with Google Sheets"
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Year to process (e.g., 2025, 2026). Defaults to current year."
    )
    args = parser.parse_args()
    main(year=args.year)
