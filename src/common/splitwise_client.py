"""Client for interacting with the Splitwise API.

This module provides a high-level interface for common Splitwise operations,
including expense management, search, and data export.
"""

# Standard library
import json
import os
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Third-party
import numpy as np
import pandas as pd
from splitwise import Expense, Splitwise
from splitwise.category import Category
from splitwise.user import ExpenseUser

# Local application
from src.common.env import load_project_env
from src.common.transaction_filters import is_deleted_expense
from src.common.utils import (
    LOG,
    infer_category,
    normalize_splitwise_date_to_local,
    parse_float_safe,
)
from src.constants.export_columns import ExportColumns
from src.constants.splitwise import (
    DEFAULT_CURRENCY,
    DELETED_AT_FIELD,
    DETAILS_COLUMN_NAME,
    REFUND_KEYWORDS,
    SPLIT_TYPE_PARTNER,
    SPLIT_TYPE_SELF,
    SPLIT_TYPE_SPLIT,
    SPLITWISE_PAGE_SIZE,
    SplitwiseUserId,
)

load_project_env()


# Handles Splitwise API/CSV integration
class SplitwiseClient:
    def __init__(self):
        self.consumer_key = os.getenv("SPLITWISE_CONSUMER_KEY")
        self.consumer_secret = os.getenv("SPLITWISE_CONSUMER_SECRET")
        self.api_key = os.getenv("SPLITWISE_API_KEY")
        # Error handling for missing env vars
        if not all([self.consumer_key, self.consumer_secret, self.api_key]):
            raise ValueError(
                "One or more Splitwise credentials are missing. Check config/.env and variable names."
            )
        self.sObj = Splitwise(
            self.consumer_key, self.consumer_secret, api_key=self.api_key
        )

    @cache
    def get_current_user(self):
        """Get current user from Splitwise API.

        Returns:
            Splitwise User object
        """
        return self.sObj.getCurrentUser()

    @cache
    def get_current_user_id(self):
        """Get current user ID from Splitwise API.

        Returns:
            int: User ID
        """
        return self.get_current_user().getId()

    def _fetch_expenses_paginated(
        self, start_date_str: str, end_date_str: str, fetch_full_details: bool = False
    ):
        """Core method to fetch expenses with pagination and optional full details.

        Args:
            start_date_str: Start date as string (YYYY-MM-DD)
            end_date_str: End date as string (YYYY-MM-DD)
            fetch_full_details: If True, fetches each expense individually to populate
                              the details field (slower but necessary for duplicate detection)

        Returns:
            list: List of expense objects from Splitwise API
        """
        LOG.info(
            f"Fetching expenses from {start_date_str} to {end_date_str}"
            + (" with full details" if fetch_full_details else "")
        )
        all_expenses = []
        offset = 0
        page_size = SPLITWISE_PAGE_SIZE
        has_more = True

        # First, get the list of expense IDs
        while has_more:
            try:
                expenses = self.sObj.getExpenses(
                    dated_after=start_date_str,
                    dated_before=end_date_str,
                    limit=page_size,
                    offset=offset,
                )

                if not expenses:
                    break

                # Filter out deleted expenses from the basic list
                non_deleted = [exp for exp in expenses if not is_deleted_expense(exp)]

                all_expenses.extend(non_deleted)

                if len(expenses) < page_size:
                    has_more = False
                else:
                    offset += page_size

                LOG.debug(
                    f"Fetched {len(expenses)} expenses (total: {len(all_expenses)})"
                )

            except Exception as e:
                LOG.error(f"Error fetching expense list (offset {offset}): {str(e)}")
                raise

        # If requested, fetch full details for each expense
        if fetch_full_details:
            LOG.info(
                f"Fetched {len(all_expenses)} expenses, now getting full details for each"
            )
            detailed_expenses = []
            for i, exp in enumerate(all_expenses):
                try:
                    expense_id = exp.getId()
                    # Fetch full expense details (includes the details field)
                    full_expense = self.sObj.getExpense(expense_id)

                    # Skip deleted expenses
                    if not (
                        hasattr(full_expense, DELETED_AT_FIELD)
                        and getattr(full_expense, DELETED_AT_FIELD)
                    ):
                        detailed_expenses.append(full_expense)

                    if (i + 1) % 20 == 0:
                        LOG.info(f"Processed {i + 1}/{len(all_expenses)} expenses")

                except Exception as e:
                    LOG.warning(
                        f"Error fetching details for expense {expense_id}: {str(e)}"
                    )
                    # Keep the original expense without full details
                    detailed_expenses.append(exp)
                    continue

            all_expenses = detailed_expenses

        LOG.info(f"Retrieved {len(all_expenses)} expenses")
        return all_expenses

    def _get_expense_cache_path(self, start_date_str: str, end_date_str: str) -> Path:
        """Get the path to the disk cache file for a date range."""
        # Extract year from date range for cache file naming
        start_year = start_date_str.split("-")[0]
        end_year = end_date_str.split("-")[0]
        if start_year == end_year:
            cache_name = f"splitwise_expense_details_{start_year}.json"
        else:
            cache_name = f"splitwise_expense_details_{start_year}_{end_year}.json"

        cache_dir = Path(__file__).parent.parent.parent / "data"
        cache_dir.mkdir(exist_ok=True)
        return cache_dir / cache_name

    def fetch_expenses_with_details(
        self, start_date_str: str, end_date_str: str, use_cache: bool = True
    ):
        """Fetch all expenses within a date range with full details populated.

        This fetches the expense list first, then calls getExpense(id) for each
        one to populate the details field. Results are cached to disk and reused
        on subsequent runs.

        Args:
            start_date_str: Start date as string (YYYY-MM-DD)
            end_date_str: End date as string (YYYY-MM-DD)
            use_cache: If True, use disk cache if available (default: True)

        Returns:
            dict: Mapping of expense_id -> expense dict with details field populated
        """
        cache_path = self._get_expense_cache_path(start_date_str, end_date_str)

        # Try to load from disk cache first
        if use_cache and cache_path.exists():
            try:
                with open(cache_path, "r") as f:
                    cached_data = json.load(f)
                LOG.info(
                    f"Loaded {len(cached_data)} expenses from disk cache: {cache_path.name}"
                )
                return cached_data
            except Exception as e:
                LOG.warning(f"Failed to load cache from {cache_path}: {e}")

        # Fetch from API if cache miss or disabled
        all_expenses = self._fetch_expenses_paginated(
            start_date_str, end_date_str, fetch_full_details=True
        )

        # Convert to dict format for duplicate detection
        expenses_with_details = {}
        for expense in all_expenses:
            expense_id = expense.getId()
            expenses_with_details[expense_id] = {
                "id": expense_id,
                "date": expense.getDate(),
                "description": expense.getDescription(),
                "cost": expense.getCost(),
                "details": expense.getDetails() or "",
                "category": (
                    expense.getCategory().getName() if expense.getCategory() else None
                ),
            }

        # Save to disk cache
        try:
            with open(cache_path, "w") as f:
                json.dump(expenses_with_details, f, indent=2)
            LOG.info(
                f"Cached {len(expenses_with_details)} expenses to disk: {cache_path.name}"
            )
        except Exception as e:
            LOG.warning(f"Failed to save cache to {cache_path}: {e}")

        return expenses_with_details

    def get_my_expenses_by_date_range(self, start_date, end_date):
        """Fetch all expenses within a date range with automatic pagination.

        This will page through the Splitwise API until no more results are
        returned for the date range. No hard cap is applied here; the function
        will continue paging until the API indicates the end of results.

        Args:
            start_date: Start date (datetime or date object)
            end_date: End date (datetime or date object)

        Returns:
            DataFrame containing all matching expenses
        """
        # Use the core pagination method (without full details for performance)
        all_expenses = self._fetch_expenses_paginated(
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            fetch_full_details=False,
        )

        # Process the expenses into a DataFrame
        my_user_id = self.get_current_user_id()
        data = []

        for expense in all_expenses:
            try:
                users = expense.getUsers() or []

                def _user_name(u) -> str:
                    first = u.getFirstName() or ""
                    return first.strip() or str(u.getId())

                user_rows = []
                for u in users:
                    user_rows.append(
                        {
                            "id": u.getId(),
                            "name": _user_name(u),
                            "paid": parse_float_safe(u.getPaidShare()),
                            "owed": parse_float_safe(u.getOwedShare()),
                        }
                    )

                user_rows_sorted = sorted(
                    user_rows, key=lambda r: (r["name"] or "").lower()
                )

                # Sheets-friendly: single deterministic string, easy to parse with SPLIT/REGEX
                # Example: "Alice|paid=10.00|owed=0.00; Bob|paid=0.00|owed=10.00"
                friends_split = "; ".join(
                    [
                        f"{r['name']}|paid={r['paid']:.2f}|owed={r['owed']:.2f}"
                        for r in user_rows_sorted
                    ]
                )

                participant_names = ", ".join([r["name"] for r in user_rows_sorted])

                my_row = next(
                    (r for r in user_rows_sorted if r["id"] == my_user_id), None
                )
                my_paid = my_row["paid"] if my_row else 0.0
                my_owed = my_row["owed"] if my_row else 0.0

                # Check if this is a refund by description keywords
                description = expense.getDescription() or ""
                is_refund = any(
                    keyword in description.lower() for keyword in REFUND_KEYWORDS
                )

                # For refunds, negate my_owed and my_paid to show as credits
                if is_refund:
                    my_owed = -my_owed
                    my_paid = -my_paid

                my_net = my_paid - my_owed

                participant_ids = {r["id"] for r in user_rows_sorted}

                has_self_user = SplitwiseUserId.SELF_EXPENSE in participant_ids
                is_partner_only = participant_ids == {
                    my_user_id,
                    SplitwiseUserId.PARTNER_EXPENSE,
                }

                if has_self_user:
                    split_type = SPLIT_TYPE_SELF
                elif is_partner_only:
                    split_type = SPLIT_TYPE_PARTNER
                else:
                    other_nonzero = any(
                        r["id"] != my_user_id and (r["paid"] > 0 or r["owed"] > 0)
                        for r in user_rows_sorted
                    )
                    split_type = (
                        SPLIT_TYPE_SPLIT if bool(other_nonzero) else SPLIT_TYPE_SELF
                    )

                data.append(
                    {
                        ExportColumns.DATE: normalize_splitwise_date_to_local(
                            expense.getDate()
                        ),
                        ExportColumns.AMOUNT: expense.getCost(),
                        ExportColumns.CATEGORY: (
                            expense.getCategory().getName()
                            if expense.getCategory()
                            else None
                        ),
                        ExportColumns.DESCRIPTION: expense.getDescription(),
                        ExportColumns.DETAILS: expense.getDetails() or "",
                        ExportColumns.SPLIT_TYPE: split_type,
                        ExportColumns.PARTICIPANT_NAMES: participant_names,
                        ExportColumns.MY_PAID: my_paid,
                        ExportColumns.MY_OWED: my_owed,
                        ExportColumns.MY_NET: my_net,
                        ExportColumns.FRIENDS_SPLIT: friends_split,
                        ExportColumns.ID: expense.getId(),
                    }
                )
            except Exception as e:
                LOG.warning(
                    f"Error processing expense {getattr(expense, 'id', 'unknown')}: {str(e)}"
                )
                continue

        LOG.info(f"Found {len(data)} expenses between {start_date} and {end_date}")
        return pd.DataFrame(data)

    def get_expense_by_id(
        self,
        expense_id: Union[int, str],
        use_cache: bool = True,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch a single Splitwise expense by ID.

        Optionally checks the local disk cache first (if a date range is provided),
        then falls back to the Splitwise API.

        Args:
            expense_id: Splitwise expense ID
            use_cache: If True, try disk cache first
            start_date: Cache search start date (YYYY-MM-DD)
            end_date: Cache search end date (YYYY-MM-DD)

        Returns:
            dict: Normalized expense dict, or None if not found / deleted
        """
        if expense_id is None:
            return None

        expense_id = int(expense_id)

        # -------------------------
        # 1. Try disk cache first
        # -------------------------
        if use_cache and start_date and end_date:
            try:
                cache = self.fetch_expenses_with_details(
                    start_date, end_date, use_cache=True
                )
                cached = cache.get(expense_id)
                if cached:
                    LOG.info(f"Found expense {expense_id} in disk cache")
                    return cached
            except Exception as e:
                LOG.debug(f"Cache lookup failed for expense {expense_id}: {e}")

        # -------------------------
        # 2. Fallback to API
        # -------------------------
        try:
            exp = self.sObj.getExpense(expense_id)
        except Exception as e:
            LOG.warning(f"Failed to fetch expense {expense_id} from API: {e}")
            return None

        # Skip deleted expenses
        if hasattr(exp, DELETED_AT_FIELD) and getattr(exp, DELETED_AT_FIELD):
            LOG.info(f"Expense {expense_id} is deleted")
            return None

        # -------------------------
        # 3. Normalize to dict
        # -------------------------
        normalized = {
            "id": exp.getId(),
            "date": normalize_splitwise_date_to_local(exp.getDate()),
            "description": exp.getDescription(),
            "cost": parse_float_safe(exp.getCost()),
            "details": exp.getDetails() or "",
            "category": (exp.getCategory().getName() if exp.getCategory() else None),
        }

        LOG.info(f"Fetched expense {expense_id} from API")
        return normalized

    def get_expense_by_id(
        self,
        expense_id: Union[int, str],
        use_cache: bool = True,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch a single Splitwise expense by ID.

        Optionally checks the local disk cache first (if a date range is provided),
        then falls back to the Splitwise API.

        Args:
            expense_id: Splitwise expense ID
            use_cache: If True, try disk cache first
            start_date: Cache search start date (YYYY-MM-DD)
            end_date: Cache search end date (YYYY-MM-DD)

        Returns:
            dict: Normalized expense dict, or None if not found / deleted
        """
        if expense_id is None:
            return None

        expense_id = int(expense_id)

        # -------------------------
        # 1. Try disk cache first
        # -------------------------
        if use_cache and start_date and end_date:
            try:
                cache = self.fetch_expenses_with_details(
                    start_date, end_date, use_cache=True
                )
                cached = cache.get(expense_id)
                if cached:
                    LOG.info(f"Found expense {expense_id} in disk cache")
                    return cached
            except Exception as e:
                LOG.debug(f"Cache lookup failed for expense {expense_id}: {e}")

        # -------------------------
        # 2. Fallback to API
        # -------------------------
        try:
            exp = self.sObj.getExpense(expense_id)
        except Exception as e:
            LOG.warning(f"Failed to fetch expense {expense_id} from API: {e}")
            return None

        # Skip deleted expenses
        if hasattr(exp, DELETED_AT_FIELD) and getattr(exp, DELETED_AT_FIELD):
            LOG.info(f"Expense {expense_id} is deleted")
            return None

        # -------------------------
        # 3. Normalize to dict
        # -------------------------
        normalized = {
            "id": exp.getId(),
            "date": normalize_splitwise_date_to_local(exp.getDate()),
            "description": exp.getDescription(),
            "cost": parse_float_safe(exp.getCost()),
            "details": exp.getDetails() or "",
            "category": (exp.getCategory().getName() if exp.getCategory() else None),
        }

        LOG.info(f"Fetched expense {expense_id} from API")
        return normalized

    def find_expense_by_cc_reference(
        self,
        cc_reference_id: str = None,
        amount: float = None,
        date: str = None,
        merchant: str = None,
        lookback_days: int = None,
        use_detailed_search: bool = False,
        start_date: str = None,
        end_date: str = None,
    ) -> Optional[Dict]:
        """Find an expense by its cc_reference_id or by matching transaction details.

        First tries to find an exact match by cc_reference_id in the details field.
        If not found and additional details (amount, date, merchant) are provided,
        attempts to find a matching transaction using those criteria.

        Args:
            cc_reference_id: The credit card reference ID to search for
            amount: Transaction amount (required for fuzzy matching)
            date: Transaction date in YYYY-MM-DD format (required for fuzzy matching)
            merchant: Merchant name (optional, improves fuzzy matching)
            lookback_days: Number of days to look back (deprecated, use start_date/end_date)
            start_date: Start date for search range (YYYY-MM-DD), defaults to 2025-01-01
            end_date: End date for search range (YYYY-MM-DD), defaults to 2025-12-31

        Returns:
            dict: The matching expense as a dictionary, or None if not found
        """
        if not cc_reference_id and not (amount is not None and date):
            LOG.debug("Either cc_reference_id or both amount and date must be provided")
            return None

        # Clean and validate the reference ID if provided
        if cc_reference_id:
            cc_reference_id = str(cc_reference_id).strip()
            if not cc_reference_id:
                cc_reference_id = None

        # Use detailed search if requested (fetches full details for each expense)
        if use_detailed_search and cc_reference_id:
            # Use provided date range or default to 2025
            if not start_date or not end_date:
                if lookback_days:
                    # Legacy behavior with lookback_days
                    end_date_obj = datetime.now().date()
                    start_date_obj = end_date_obj - timedelta(days=lookback_days)
                    start_date = start_date_obj.strftime("%Y-%m-%d")
                    end_date = end_date_obj.strftime("%Y-%m-%d")
                else:
                    # Default to full 2025 year
                    start_date = "2025-01-01"
                    end_date = "2025-12-31"

            # Call cached method with string dates
            expense_cache = self.fetch_expenses_with_details(start_date, end_date)

            # Search in the cache
            cc_ref_clean = cc_reference_id.strip().strip("'\"")
            for exp_id, exp_data in expense_cache.items():
                details_clean = str(exp_data.get("details", "")).strip().strip("'\"")
                if details_clean == cc_ref_clean:
                    LOG.info(
                        f"Found expense {exp_id} matching cc_reference_id: {cc_reference_id}"
                    )
                    return exp_data
            return None

        # Fallback: Fetch from API (legacy behavior, doesn't have details field)
        # Ensure lookback_days has a sensible default to avoid TypeError when None
        if lookback_days is None:
            try:
                lookback_days = int(os.getenv("CC_REFERENCE_LOOKBACK_DAYS", "365"))
            except Exception:
                lookback_days = 365

        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=lookback_days)

        df = self.get_my_expenses_by_date_range(start_date, end_date)
        if df.empty:
            return None

        # First, try exact match by cc_reference_id in details if provided
        if cc_reference_id and DETAILS_COLUMN_NAME in df.columns:
            # Strip quotes and whitespace from both sides for comparison
            # (Splitwise SDK may wrap details in DOUBLE quotes like ''value'')
            df_details_clean = df[DETAILS_COLUMN_NAME].astype(str).str.strip()
            # Strip multiple layers of quotes (Splitwise returns ''value'' with double quotes)
            for _ in range(3):
                df_details_clean = df_details_clean.str.strip("'\"")

            cc_ref_clean = str(cc_reference_id).strip()
            for _ in range(3):
                cc_ref_clean = cc_ref_clean.strip("'\"")

            details_matches = df_details_clean == cc_ref_clean
            matches = df[details_matches]

            if len(matches) == 1:
                LOG.info(f"Found exact match for cc_reference_id: {cc_reference_id}")
                return matches.iloc[0].to_dict()
            elif len(matches) > 1:
                LOG.warning(
                    "Multiple expenses found with cc_reference_id %s", cc_reference_id
                )
                return (
                    matches.sort_values("date_updated", ascending=False)
                    .iloc[0]
                    .to_dict()
                )
            else:
                LOG.debug(f"No exact details match found for '{cc_ref_clean}'")

        # If we have amount and date, try fuzzy matching
        if amount is not None and date:
            try:
                # Convert date string to datetime for comparison
                target_date = pd.to_datetime(date).date()

                # Filter for same amount (within a small tolerance for floating point)
                amount_matches = np.isclose(
                    df["amount"].astype(float), float(amount), rtol=1e-5
                )
                df_filtered = df[amount_matches]

                if not df_filtered.empty:
                    # Filter for same date
                    df_filtered["expense_date"] = pd.to_datetime(
                        df_filtered["date"]
                    ).dt.date
                    date_matches = df_filtered["expense_date"] == target_date
                    df_filtered = df_filtered[date_matches]

                    if not df_filtered.empty:
                        # If we have merchant info, try to match that too
                        if merchant:
                            merchant = str(merchant).lower().strip()
                            if merchant:
                                merchant_matches = (
                                    df_filtered["description"]
                                    .str.lower()
                                    .str.contains(merchant, regex=False)
                                )
                                merchant_matches = df_filtered[merchant_matches]
                                if not merchant_matches.empty:
                                    df_filtered = merchant_matches

                        # Return the best match (most recent if multiple)
                        if not df_filtered.empty:
                            best_match = df_filtered.sort_values(
                                "date_updated", ascending=False
                            ).iloc[0]
                            LOG.info("Found potential match by amount/date/merchant")
                            return best_match.to_dict()

            except Exception as e:
                LOG.warning("Error during fuzzy matching: %s", str(e), exc_info=True)
                return None

        LOG.debug("No matching expense found")
        return None

    def add_expense_from_txn(
        self,
        txn: Dict[str, Any],
        cc_reference_id: str,
        users: Optional[List[Dict]] = None,
    ) -> Union[str, int]:
        """Create a Splitwise expense from normalized transaction data.

        Args:
            txn: Dictionary containing:
                - date (str): Date in YYYY-MM-DD format
                - amount (float): Transaction amount
                - currency (str, optional): Currency code (default: USD)
                - description (str): Transaction description
                - merchant (str, optional): Merchant name (used if description is empty)
                - detail (str, optional): Additional transaction details (stored in notes)
            cc_reference_id: Credit card reference ID for this transaction
            users: Optional list of user participation details:
                - user_id (int): Splitwise user ID
                - paid_share (float): Amount paid by this user
                - owed_share (float): Amount owed by this user

        Returns:
            The created expense ID

        Raises:
            RuntimeError: If expense creation fails or cc_reference_id is missing
        """
        if not cc_reference_id:
            raise ValueError("cc_reference_id is required")

        desc = txn.get("description") or txn.get("merchant") or "Imported expense"
        cost = float(txn.get("amount", 0))
        date = txn.get("date")
        currency = txn.get("currency") or DEFAULT_CURRENCY

        # Only run category inference if not already provided
        if txn.get("category_id") is None:
            LOG.info("Category not provided, running inference")
            category_info = infer_category(txn)
            if category_info:
                txn.update(
                    {
                        "category_id": category_info["category_id"],
                        "subcategory_id": category_info.get("subcategory_id", 0),
                        "category_name": category_info.get("category_name"),
                        "subcategory_name": category_info.get("subcategory_name"),
                    }
                )
                LOG.info(
                    f"Assigned category: {category_info.get('category_name')} / {category_info.get('subcategory_name')}"
                )
            else:
                LOG.warning("No category could be inferred, using default category")
                txn.update(
                    {
                        "category_id": 18,  # Default "Other" category
                        "subcategory_id": 0,
                        "category_name": "Other",
                        "subcategory_name": "Other",
                    }
                )
        else:
            LOG.info(
                f"Using provided category: {txn.get('category_name')} / {txn.get('subcategory_name')} "
                f"(ID: {txn.get('category_id')}, Subcategory ID: {txn.get('subcategory_id')})"
            )

        # Use SDK Expense objects
        expense = Expense()
        expense.setCost(str(cost))
        expense.setDescription(desc)
        expense.setDetails(
            str(cc_reference_id)
        )  # Ensure it's a plain string without quotes

        # Convert date to ISO 8601 format with explicit time at noon to avoid timezone issues
        # Splitwise API expects dates in format like "2025-12-12T12:00:00Z"
        # Using noon ensures the date shows correctly regardless of timezone
        if isinstance(date, str) and "T" not in date:
            # Add time component if not present to avoid timezone interpretation issues
            date = f"{date}T12:00:00Z"

        expense.setDate(date)
        expense.setCurrencyCode(currency)

        # Set the category - fail if None (no default fallback)
        category_id = txn.get("category_id")
        subcategory_id = txn.get("subcategory_id")

        LOG.info(
            f"Setting category: ID={category_id}, Subcategory ID={subcategory_id}, "
            f"Name={txn.get('category_name')}/{txn.get('subcategory_name')}"
        )

        if category_id is None or category_id == 0:
            error_msg = (
                f"Cannot add expense without valid category. "
                f"Merchant: {desc}, "
                f"Category from inference: {txn.get('category_name')} / {txn.get('subcategory_name')}"
            )
            LOG.error(error_msg)
            raise ValueError(error_msg)

        # Create category object
        # Note: Splitwise expects the category.id to be the SUBCATEGORY id, not the parent category id
        category = Category()
        if subcategory_id is not None and subcategory_id != 0:
            # Use subcategory ID as the category ID
            LOG.info(f"Setting category ID to subcategory: {subcategory_id}")
            category.id = subcategory_id
        else:
            # No subcategory, use the parent category ID
            LOG.info(f"Setting category ID to parent category: {category_id}")
            category.id = category_id

        LOG.info(f"Category object created: id={category.id}")
        expense.setCategory(category)
        LOG.debug(
            f"Set category: {txn.get('category_name')} / {txn.get('subcategory_name')}"
        )

        # Handle user shares if provided
        if users:
            for user_data in users:
                user = ExpenseUser()
                user.setId(user_data.get("user_id"))
                user.setPaidShare(str(user_data.get("paid_share", "0.0")))
                user.setOwedShare(str(user_data.get("owed_share", "0.0")))
                expense.addUser(user)

        # Create the expense and return the ID
        try:
            created = self.sObj.createExpense(expense)

            # Handle tuple return (success, expense_object) or direct Expense object
            if isinstance(created, tuple):
                if len(created) >= 2 and created[1] is not None:
                    created = created[1]  # Get the expense object from tuple
                elif len(created) >= 1:
                    created = created[0]

            # Extract ID using various methods
            expense_id = None
            if hasattr(created, "getId") and callable(created.getId):
                expense_id = created.getId()
            elif hasattr(created, "id"):
                expense_id = created.id
            elif isinstance(created, (int, str)):
                expense_id = created

            if expense_id is None:
                LOG.error(
                    f"Could not extract expense ID. Type: {type(created)}, Dir: {dir(created) if hasattr(created, '__dict__') else 'N/A'}"
                )
                raise RuntimeError("Failed to get expense ID from created expense")

            LOG.info(f"Successfully created expense with ID: {expense_id}")
            return int(expense_id)
        except RuntimeError:
            raise
        except Exception as e:
            LOG.error(f"Error creating expense: {str(e)}", exc_info=True)
            raise RuntimeError(f"Failed to create expense: {str(e)}")

    @cache
    def get_categories(self):
        """Get all available Splitwise categories and subcategories.

        Returns:
            list: List of category dictionaries with 'id', 'name', and 'subcategories'
        """
        return self.sObj.getCategories()


def get_splitwise_client(dry_run: bool = False) -> Optional["SplitwiseClient"]:
    """Get SplitwiseClient instance (None in dry-run mode).

    Args:
        dry_run: If True, returns None (no API calls will be made)

    Returns:
        SplitwiseClient instance or None
    """
    return None if dry_run else SplitwiseClient()


# Example usage:
if __name__ == "__main__":
    client = SplitwiseClient()
    expense = client.get_expense_by_id(4291345617, use_cache=False)
    print(expense["details"])
