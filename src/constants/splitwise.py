"""Constants related to Splitwise integration.

This module contains all the constants used for interacting with the Splitwise API,
including payload keys, default values, and other configuration parameters.
"""

# Standard library
import json
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Dict

# Local application
from src.common.env import get_env

# Marker used to identify imported transactions in Splitwise descriptions
IMPORTED_ID_MARKER = "[ImportedID:"

# Default currency code used for transactions
DEFAULT_CURRENCY = "USD"

# Splitwise API pagination settings
SPLITWISE_PAGE_SIZE = 50  # Maximum allowed by Splitwise API
DEFAULT_LOOKBACK_DAYS = (
    30  # Default number of days to look back for duplicate detection
)

# Column name for transaction details/notes field in exported data
DETAILS_COLUMN_NAME = "Details"

# Field name for deleted expense timestamp in Splitwise API response
DELETED_AT_FIELD = "deleted_at"

# Keywords used to identify refund/credit transactions in descriptions
REFUND_KEYWORDS = ("refund", "credit", "return")

# Split type constants for transaction categorization
SPLIT_TYPE_SELF = "self"
SPLIT_TYPE_SPLIT = "split"
SPLIT_TYPE_PARTNER = "partner"


class SubcategoryMapper:
    """Manages Splitwise subcategory ID mappings.

    Loads mappings from config/splitwise_category_ids.json and provides
    convenient access to subcategory IDs by snake_case names.
    """

    def __init__(self):
        self._ids: Dict[str, int] = {}
        self._names: Dict[int, str] = {}
        self._load_mappings()

    def _load_mappings(self):
        """Load subcategory mappings from the JSON configuration file."""
        project_root = Path(__file__).parent.parent.parent
        json_path = project_root / "config" / "splitwise_category_ids.json"

        if not json_path.exists():
            return

        with open(json_path, "r") as f:
            data = json.load(f)

        # Build mapping from snake_case names to subcategory IDs
        category_mapping = data.get("category_mapping", {})

        for _, info in category_mapping.items():
            subcategory = info.get("subcategory_name", "")
            subcategory_id = info.get("subcategory_id")

            if subcategory and subcategory_id:
                # Convert to snake_case: "Household supplies" -> "household_supplies"
                snake_case_name = (
                    subcategory.lower().replace("/", "_").replace(" ", "_")
                )
                self._ids[snake_case_name] = subcategory_id
                self._names[subcategory_id] = snake_case_name

    @property
    def ids(self) -> Dict[str, int]:
        """Get mapping of snake_case names to subcategory IDs."""
        return self._ids.copy()

    @property
    def names(self) -> Dict[int, str]:
        """Get mapping of subcategory IDs to snake_case names."""
        return self._names.copy()

    def get_id(self, name: str) -> int:
        """Get subcategory ID by snake_case name.

        Args:
            name: Snake_case subcategory name (e.g., 'household_supplies')

        Returns:
            Subcategory ID

        Raises:
            KeyError: If name not found
        """
        return self._ids[name]

    def get_name(self, subcategory_id: int) -> str:
        """Get snake_case name by subcategory ID.

        Args:
            subcategory_id: The subcategory ID

        Returns:
            Snake_case subcategory name

        Raises:
            KeyError: If ID not found
        """
        return self._names[subcategory_id]


# Module-level instance - instantiate where you need access to mapper methods
SUBCATEGORY_MAPPER = SubcategoryMapper()

# Convenient dict access for scripts that just need the ID mappings
SUBCATEGORY_IDS = SUBCATEGORY_MAPPER.ids
SUBCATEGORY_NAMES = SUBCATEGORY_MAPPER.names


class SplitwiseUserId(IntEnum):
    SELF_EXPENSE = int(get_env("SPLITWISE_SELF_ID", "0"))
    PARTNER_EXPENSE = int(get_env("SPLITWISE_PARTNER_ID", "0"))


class ExcludedSplitwiseDescriptions(StrEnum):
    """Well-known Splitwise-generated descriptions that should be excluded from budgeting exports.

    These are exact-match strings (after trimming and case-normalization) that represent
    settlement/payment style records rather than expense items.
    """

    SETTLE_ALL_BALANCES = "Settle all balances"
    PAYMENT = "Payment"
