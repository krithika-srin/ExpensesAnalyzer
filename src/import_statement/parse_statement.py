"""
Parse CSV statements into a pandas DataFrame with columns:
  - date (YYYY-MM-DD)
  - description (string)
  - amount (positive float)
  - raw_line (string)

Bank-specific parsing is determined by the file's directory:
  - data/bank_statements/amex/amex2026.csv → Amex format
  - data/bank_statements/bofa/bofa2026.csv → BoFA format
"""

import os
import re
import pandas as pd

from src.constants.config import CFG_PATHS
from src.common.utils import LOG, load_yaml, parse_date_safe
from src.common.transaction_filters import is_payment_transaction
from src.import_statement.bank_config import BankConfig

# Load configuration
CFG = None
for env_path in CFG_PATHS:
    if env_path.exists():
        try:
            CFG = load_yaml(env_path)
            break
        except (OSError, ValueError) as e:
            LOG.exception("Failed to load config %s: %s", env_path, e)
            CFG = None
            break

# Initialize bank configuration
BANK_CONFIG = BankConfig()


def _find_column(dataframe, search_term):
    """Find a column by searching column names and lowercased values.

    Args:
        dataframe: Pandas DataFrame
        search_term: Column name pattern to find ('date', 'description', 'amount')

    Returns:
        Column name or None if not found
    """
    for column_name in dataframe.columns:
        if search_term.lower() in column_name.lower():
            return column_name
    return None


def _is_credit(row):
    """Check if transaction is a credit based on amount and bank."""
    bank = row.get("_bank", "amex")
    amount = row["amount"]
    if bank == "amex":
        return amount < 0
    elif bank == "bofa":
        # For BoFA, positive amounts are credits (payments, refunds), negative are expenses
        return amount > 0
    return amount < 0


def _is_likely_refund(row):
    """Check if transaction is likely a refund based on description.

    Treats any valid credit operation as a refund unless it matches
    known payment/reward patterns.
    """
    if not row["is_credit"]:
        return False

    # Combine description and category for pattern matching
    category_text = row.get("category", "") or ""
    combined_text = f"{row['description']} {category_text}".lower()

    # Exclude payment patterns, including BoFA debit transfers from checking.
    if is_payment_transaction(row["description"]):
        return False

    payment_keywords = [
        "payment",
        "autopay",
        "thank you",
        "settle",
        "points for",
        "reward",
        "recurring from chk",
        "recurring from checking",
        "online/mobile recurring",
        "mobile recurring",
        "from chk",
        "from checking",
    ]
    if any(keyword in combined_text for keyword in payment_keywords):
        return False

    # Since it is a credit and NOT a payment, assume it is a refund
    return True


def parse_csv(path):
    """Parse a CSV statement file.

    Bank format is determined from the file's directory:
    - data/bank_statements/amex/* → Amex format
    - data/bank_statements/bofa/* → BoFA format

    Args:
        path: Path to CSV file

    Returns:
        Parsed DataFrame with normalized columns
    """
    LOG.info("Parsing CSV: %s", path)
    dataframe = pd.read_csv(path, dtype=str)

    # Store original row count for logging
    original_count = len(dataframe)

    # Determine bank from file path
    bank_name = BANK_CONFIG.detect_bank_from_path(path)
    LOG.info("Processing %s statement: %s", bank_name, path)

    # Validate CSV headers against bank's required columns
    BANK_CONFIG.validate_csv_headers(list(dataframe.columns), bank_name)

    # Get bank-specific configuration
    bank_cfg = BANK_CONFIG.get_bank_config(bank_name)

    # Map columns based on bank configuration
    column_mapping = {}

    # Map date column
    date_col = bank_cfg.get("date_column")
    column_mapping["date"] = (
        date_col if date_col in dataframe.columns else _find_column(dataframe, "date")
    )

    # Map description column (may have multiple options)
    desc_cols = bank_cfg.get("description_columns", [])
    column_mapping["description"] = next(
        (col for col in desc_cols if col in dataframe.columns),
        _find_column(dataframe, "description"),
    )

    # Map amount column
    amount_col = bank_cfg.get("amount_column")
    column_mapping["amount"] = (
        amount_col
        if amount_col in dataframe.columns
        else _find_column(dataframe, "amount")
    )

    # Map optional columns
    ref_col = bank_cfg.get("reference_column")
    if ref_col and ref_col in dataframe.columns:
        column_mapping["detail"] = ref_col

    cat_col = bank_cfg.get("category_column")
    if cat_col and cat_col in dataframe.columns:
        column_mapping["category"] = cat_col

    addr_col = bank_cfg.get("address_column")
    if addr_col and addr_col in dataframe.columns:
        column_mapping["address"] = addr_col

    # Fallback to first three columns if mapping failed
    if (
        "date" not in column_mapping
        or "description" not in column_mapping
        or "amount" not in column_mapping
    ):
        col_names = list(dataframe.columns)
        column_mapping["date"] = column_mapping.get("date", col_names[0])
        column_mapping["description"] = column_mapping.get("description", col_names[1])
        column_mapping["amount"] = column_mapping.get("amount", col_names[2])

    LOG.info("Column mapping for %s: %s", bank_name, column_mapping)

    # Create output dataframe with basic columns
    processed_df = pd.DataFrame()
    processed_df["date"] = dataframe[column_mapping["date"]].apply(parse_date_safe)
    processed_df["description"] = (
        dataframe[column_mapping["description"]].astype(str).str.strip()
    )
    processed_df["amount"] = dataframe[column_mapping["amount"]].apply(
        parse_amount_safe
    )

    # Add category column if it exists in the input
    if "category" in column_mapping:
        processed_df["category"] = (
            dataframe[column_mapping["category"]].astype(str).str.strip()
        )

    # Extract cc_reference_id from detail/reference column if available
    if "detail" in column_mapping:
        processed_df["detail"] = (
            dataframe[column_mapping["detail"]].astype(str).str.strip()
        )
        processed_df["cc_reference_id"] = processed_df["detail"].apply(
            extract_reference_id
        )
    else:
        processed_df["cc_reference_id"] = None

    processed_df["raw_line"] = dataframe.apply(
        lambda row: " | ".join([str(row[col]) for col in dataframe.columns]), axis=1
    )

    # Store bank name for later use in amount handling
    processed_df["_bank"] = bank_name

    # Filter out rows with null dates
    processed_df = processed_df.dropna(subset=["date"])

    LOG.info("[TEMP] Starting transaction filtering...")

    # Filter out transactions with null categories (if category column exists)
    if "category" in processed_df.columns:
        before_filter = len(processed_df)
        processed_df = processed_df[
            ~processed_df["category"].isin(["None", "null", "", None, "nan"])
        ]
        null_filtered = before_filter - len(processed_df)
        if null_filtered > 0:
            LOG.info(
                "[TEMP] Filtered out %d transactions with null/empty categories",
                null_filtered,
            )

    # Filter out transactions containing "Fees & Adjustments" in description
    before_fee_filter = len(processed_df)
    fee_filter = processed_df["description"].str.contains(
        "Fees & Adjustments", case=False, na=False
    )
    filtered_fees = processed_df[fee_filter]
    processed_df = processed_df[~fee_filter]
    fee_filtered = before_fee_filter - len(processed_df)
    if fee_filtered > 0:
        LOG.info(
            "[TEMP] Filtered out %d transactions containing 'Fees & Adjustments' in description",
            fee_filtered,
        )
        if not filtered_fees.empty:
            LOG.info("[TEMP] Sample of filtered 'Fees & Adjustments' transactions:")
            for _, row in filtered_fees.head(3).iterrows():
                truncated_desc = (
                    row["description"][:50] + "..."
                    if len(row["description"]) > 50
                    else row["description"]
                )
                LOG.info(
                    "  [TEMP] %s - %s - $%.2f",
                    row["date"],
                    truncated_desc,
                    row["amount"],
                )

    # Identify credits and refunds
    processed_df["is_credit"] = processed_df.apply(_is_credit, axis=1)
    processed_df["is_refund"] = processed_df.apply(_is_likely_refund, axis=1)

    credits_count = processed_df["is_credit"].sum()
    refunds_count = processed_df["is_refund"].sum()

    if credits_count > 0:
        LOG.info(
            "Found %d credit transactions (amount < 0): %d refunds, %d other credits (payments)",
            credits_count,
            refunds_count,
            credits_count - refunds_count,
        )

    # Normalize amounts to positive
    processed_df["amount"] = processed_df["amount"].abs()

    # Filter out all non-refund credits (e.g. payments, statement credits, rewards)
    non_refund_credit_filter = (processed_df["is_credit"]) & (
        ~processed_df["is_refund"]
    )
    filtered_credits = processed_df[non_refund_credit_filter]
    processed_df = processed_df[~non_refund_credit_filter]

    credit_filtered = len(filtered_credits)
    if credit_filtered > 0:
        LOG.info(
            "[TEMP] Filtered out %d non-refund credit (payment/reward) transactions",
            credit_filtered,
        )
        if not filtered_credits.empty:
            LOG.info("[TEMP] Sample of filtered credit transactions:")
            for _, row in filtered_credits.head(5).iterrows():
                truncated_desc = (
                    row["description"][:50] + "..."
                    if len(row["description"]) > 50
                    else row["description"]
                )
                LOG.info(
                    "  [TEMP] %s - %s - $%.2f",
                    row["date"],
                    truncated_desc,
                    row["amount"],
                )

    filtered_count = original_count - len(processed_df)
    if filtered_count > 0:
        LOG.info(
            "[TEMP] Filtered out %d of %d total transactions (%.1f%%)",
            filtered_count,
            original_count,
            (filtered_count / original_count) * 100,
        )

    if not processed_df.empty:
        LOG.info("[TEMP] Sample of transactions after filtering (first 3):")
        for _, row in processed_df.head(3).iterrows():
            truncated_desc = (
                row["description"][:50] + "..."
                if len(row["description"]) > 50
                else row["description"]
            )
            LOG.info(
                "  [TEMP] %s - %s - $%.2f", row["date"], truncated_desc, row["amount"]
            )

    LOG.info("[TEMP] Transaction filtering complete")

    if "_bank" in processed_df.columns:
        processed_df = processed_df.drop(columns=["_bank"])

    return processed_df


def parse_any(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in [".csv", ".txt"]:
        return parse_csv(path)
    else:
        raise ValueError("Unsupported extension: " + ext)


def parse_statement(path):
    return parse_any(path)


def parse_amount_safe(amount_str):
    if pd.isna(amount_str):
        return 0.0
    amount_str = str(amount_str).strip()
    amount_str = amount_str.replace("$", "").replace(",", "")
    try:
        return float(amount_str)
    except ValueError:
        # handle parentheses as negative
        if "(" in amount_str and ")" in amount_str:
            clean_amount_str = amount_str.replace("(", "").replace(")", "")
            try:
                return -float(clean_amount_str)
            except ValueError:
                raise
        raise


def extract_reference_id(detail_str):
    """Extract credit card reference/transaction ID from detail field.

    Handles various formats:
    - Pure numeric IDs (e.g., "123456789")
    - Alphanumeric IDs (e.g., "TXN123ABC456")
    - IDs with prefixes (e.g., "REF: 123456789")

    Returns:
        Cleaned reference ID string or None if not found/invalid
    """
    if pd.isna(detail_str) or detail_str in ["None", "null", "", "nan"]:
        return None

    raw_detail_str = str(detail_str).strip()

    # Skip empty or placeholder values
    if not raw_detail_str or raw_detail_str.lower() in ["none", "null", "nan", "n/a"]:
        return None

    # Remove obvious prefixes that are not part of an ID
    for prefix in ["REF:", "REFERENCE:", "TXN:", "TRANS:", "ID:"]:
        if raw_detail_str.upper().startswith(prefix):
            raw_detail_str = raw_detail_str[len(prefix) :].strip()

    # Prefer explicit patterns: ticket numbers, 'Ticket Number: <digits>', short alphanumeric refs, or 6-25 digit numbers
    patterns = [
        r"\b(\d{13})\b",  # 13-digit ticket numbers
        r"\bTicket Number\s*[:]?\s*(\d{10,})\b",
        r"\b([A-Z0-9]{6,12}-?\d{0,4})\b",  # short alphanumeric refs (e.g. RPR8EGX8)
        r"\b(\d{6,25})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_detail_str)
        if match:
            groups = (
                [group for group in match.groups() if group]
                if match.groups()
                else [match.group(0)]
            )
            # Return the first suitable group (prefer longer)
            for group in sorted(groups, key=len, reverse=True):
                candidate_id = re.sub(r"[^0-9A-Za-z]", "", group)
                if len(candidate_id) >= 6:
                    return candidate_id

    # Fallback: remove non-alphanumerics and accept if reasonably long
    candidate_id = re.sub(r"[^0-9A-Za-z]", "", raw_detail_str).strip()

    # If the original detail is multiline or contains many words, avoid
    # returning a long concatenation of the whole text as the reference id.
    words = [word for word in re.split(r"\s+", raw_detail_str) if word]
    if "\n" in raw_detail_str or len(words) > 6:
        # allow numeric-only ids (ticket numbers) even in multiline text
        if candidate_id.isdigit() and 6 <= len(candidate_id) <= 30:
            return candidate_id
        return None

    # Short single-line fallback: accept cleaned alphanumerics of reasonable length
    if 8 <= len(candidate_id) <= 30:
        return candidate_id

    return None
