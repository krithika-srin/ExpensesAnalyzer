import os
import json
import pandas as pd

import dateparser
from datetime import datetime, date, timezone
import logging
import yaml
import hashlib
import re
import tempfile
from functools import cache
from typing import Union, Optional, Dict, Any

from src.constants.config import CFG_PATHS
from src.common.env import load_project_env

# Load environment once
load_project_env()

LOG = logging.getLogger("cc_splitwise")
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
LOG.addHandler(handler)
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO"))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

# Date format constants
DATE_FORMAT = "%Y-%m-%d"


def parse_date_string(date_str: str) -> date:
    """Parse YYYY-MM-DD date string to date object.

    Args:
        date_str: Date string in YYYY-MM-DD format

    Returns:
        date object

    Raises:
        ValueError: If date_str is not in valid format
    """
    return datetime.strptime(date_str, DATE_FORMAT).date()


def format_date(date_obj: Union[date, datetime]) -> str:
    """Format date/datetime object to YYYY-MM-DD string.

    Args:
        date_obj: date or datetime object

    Returns:
        Date string in YYYY-MM-DD format
    """
    if isinstance(date_obj, datetime):
        date_obj = date_obj.date()
    return date_obj.strftime(DATE_FORMAT)


def load_yaml(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)


def clean_description_for_splitwise(
    description: str, config: Optional[Dict] = None
) -> str:
    """Clean and normalize transaction descriptions for human readability in Splitwise.

    Removes technical noise like transaction IDs, payment method prefixes, URLs, country codes,
    and formats the result to be human-readable.

    Args:
        description: Raw description from credit card statement
        config: Optional configuration for cleaning rules

    Returns:
        str: Clean, human-readable description suitable for Splitwise

    Examples:
        >>> clean_description_for_splitwise("GRAB*A-8PXHISMWWU9TASINGAPORE           SG")
        'Grab'
        >>> clean_description_for_splitwise("GglPay GUARDIAN HEALTH & BEAUTY-1110104105")
        'Guardian Health & Beauty'
        >>> clean_description_for_splitwise("UBER EATS           help.uber.com       CA")
        'Uber Eats'
    """
    if not description or not isinstance(description, str):
        return description or ""

    # Start with original
    cleaned = description.strip()

    # Try merchant lookup first - if we know this merchant, use canonical name
    merchant_lookup = _load_merchant_lookup()
    normalized_merchant = clean_merchant_name(cleaned).lower()
    if normalized_merchant in merchant_lookup:
        merchant_info = merchant_lookup[normalized_merchant]
        # Use canonical_name if available, otherwise title-case the merchant key
        canonical_name = merchant_info.get("canonical_name")
        if not canonical_name:
            canonical_name = " ".join(
                word.title() for word in normalized_merchant.split()
            )
        LOG.info(f"Using canonical merchant name: '{canonical_name}' (from lookup)")
        return canonical_name

    # 0. Extract meaningful lines from multiline descriptions
    if "\n" in cleaned:
        lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
        # Strategy: look for the second or third line as it often has the merchant name
        # Skip generic category labels (LODGING, RESTAURANT, ONLINE SUBS, etc.)
        category_words = {
            "LODGING",
            "RESTAURANT",
            "ONLINE",
            "SUBS",
            "TAXICAB",
            "LIMOUSINE",
            "BEAUTY",
            "BARBER",
            "SHOP",
            "MASSAGE",
            "PARLOR",
            "DUTY-FREE",
            "STORE",
        }
        best_line = ""
        for line in lines:
            # Skip transaction IDs (long hex or numeric codes at start)
            if re.match(r"^[0-9a-f]{8,}", line, re.IGNORECASE):
                continue
            if re.match(
                r"^\d{4,}\s+\d+", line
            ):  # Skip lines like "3152388905  88099554"
                continue
            # Skip lines that are just category labels
            words = set(line.upper().split())
            if words and words.issubset(category_words):
                continue
            # Skip very short lines (less than 3 chars)
            if len(line) <= 3:
                continue
            # Prefer lines with actual merchant names (containing letters and meaningful length)
            if re.search(r"[a-zA-Z]{3,}", line) and len(line) > 3:
                best_line = line
                break
        if best_line:
            cleaned = best_line
        elif lines:
            # Fallback: try to find any line with letters
            for line in lines:
                if re.search(r"[a-zA-Z]{3,}", line):
                    cleaned = line
                    break
            else:
                cleaned = lines[0]

    # 1. Remove transaction IDs (alphanumeric codes after * or -)
    cleaned = re.sub(r"[*-][A-Z0-9]{10,}", "", cleaned)

    # 2. Remove payment method prefixes (more comprehensive)
    payment_prefixes = [
        r"^GglPay\s+",
        r"^ApplePay\s+",
        r"^AMZN\s+Mktp\s+",
        r"^SQ\s*\*\s*",
        r"^Grab\*\s*",
        r"^PayPal\s*\*\s*",
        r"^TST\*\s+",
        r"^SP\s+",
    ]
    for prefix in payment_prefixes:
        cleaned = re.sub(prefix, "", cleaned, flags=re.IGNORECASE)

    # 3. Remove URLs and domains
    cleaned = re.sub(r"https?://[^\s]+", "", cleaned)
    cleaned = re.sub(r"www\.[^\s]+", "", cleaned)
    cleaned = re.sub(r"\bhelp\.[a-z]+\.com\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b[a-z]+\.com\b", "", cleaned, flags=re.IGNORECASE)

    # 4. Remove reference numbers and codes
    cleaned = re.sub(r"^[A-Z0-9]{6,}\s+", "", cleaned)
    cleaned = re.sub(r"^\d{4,}\s+", "", cleaned)
    cleaned = re.sub(r"-\d{6,}", "", cleaned)  # Remove trailing codes like -1110104105

    # 5. Remove phone numbers in various formats
    cleaned = re.sub(r"\(\d{3}\)\d{3}-\d{4}", "", cleaned)
    cleaned = re.sub(r"\+?\d{10,}", "", cleaned)

    # 6. Remove country codes and location patterns
    location_patterns = [
        r"\s+SINGAPORE\s*\d*",
        r"\s+BADUNG\s*-?\s*BALI?",
        r"\s+JAKARTA\s+[A-Z]{3}",
        r"\s+GIANYAR\s*-?\s*BAL?",
        r"\s+DENPASAR",
        r",?\s*[A-Z]{2}\s*\d{5}",  # State code + zip
        r"\s+[A-Z]{2}$",  # Country code at end
        r"\s+NA$",  # Remove "NA" at end
    ]
    for pattern in location_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # 7. Remove trailing/leading category descriptions
    cleaned = re.sub(
        r"^\s*(ONLINE\s+SUBS?|LODGING|RESTAURANT|TAXICAB|BEAUTY|BARBER\s+SHOP)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s+(ONLINE\s+SUBS?|LODGING|RESTAURANT|TAXICAB|BEAUTY|BARBER\s+SHOP)$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    # 8. Fix concatenated words (missing spaces) - lowercase followed by uppercase
    cleaned = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)

    # 9. Remove trailing special characters, numbers, and extra codes
    cleaned = re.sub(r"[*#\-]+$", "", cleaned)
    cleaned = re.sub(r"\s+\d{4,}$", "", cleaned)  # Remove trailing long numbers
    cleaned = re.sub(r"\s+[A-Z0-9]{5,}$", "", cleaned)  # Remove trailing codes
    cleaned = re.sub(r"\s+HO$", "", cleaned, flags=re.IGNORECASE)  # Remove " HO" suffix

    # 10. Collapse multiple spaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # 11. Remove standalone very short words and numeric-only words
    words = cleaned.split()
    words = [w for w in words if not (w.isdigit() and len(w) < 5)]
    cleaned = " ".join(words)

    # 12. Title case for better readability
    words = cleaned.split()
    formatted_words = []
    for word in words:
        if len(word) <= 3 and word.isupper():
            # Keep short all-caps words (e.g., "USA", "NYC", "BMW")
            formatted_words.append(word)
        elif word.isupper() and len(word) > 3:
            # Title case long all-caps words
            formatted_words.append(word.title())
        elif word.islower():
            # Title case lowercase words
            formatted_words.append(word.title())
        else:
            # Keep mixed case as-is (likely proper nouns)
            formatted_words.append(word)
    cleaned = " ".join(formatted_words)

    # 13. Fallback: if we cleaned too much, return a shortened original
    if not cleaned or len(cleaned) < 3:
        # Take first meaningful part of original
        cleaned = description.replace("\n", " ").strip()[:50]
        cleaned = re.sub(r"[*-][A-Z0-9]{10,}", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # Simple title case
        cleaned = " ".join(word.title() for word in cleaned.split())

    return cleaned


def clean_merchant_name(description: str, config: Optional[Dict] = None) -> str:
    """Clean up and standardize merchant names from transaction descriptions.

    Simplified approach: Extract merchant name from Description field only.
    Format: "MERCHANT_NAME   LOCATION_INFO   STATE"

    Examples:
        "AMERICAN AIRLINES   800-433-7300        TX" → "American Airlines"
        "SP BERNAL CUTLERY   SAN FRANCISCO       CA" → "Bernal Cutlery"
        "GglPay CINEMARK     PLANO               TX" → "Cinemark"
        "LULULEMON ATHLETICA (877)263-9300       CA" → "Lululemon Athletica"

    Args:
        description: Raw description string from the transaction (Description field from CSV)
        config: Optional configuration dictionary (unused in simplified version)
        description: Raw description string from the transaction (Description field from CSV)
        config: Optional configuration dictionary (unused in simplified version)

    Returns:
        str: Cleaned and standardized merchant name
    """
    if not description or not isinstance(description, str):
        return description or ""

    # Remove prefixes that aren't part of merchant name
    description = description.strip()

    # Remove common payment processor prefixes
    prefixes_to_remove = [
        r"^SP\s+",  # Square point of sale prefix
        r"^GglPay\s+",  # Google Pay prefix
        r"^PayPal\s*\*\s*",  # PayPal prefix
        r"^SQ\s*\*\s*",  # Square prefix
    ]

    for prefix_pattern in prefixes_to_remove:
        description = re.sub(prefix_pattern, "", description, flags=re.IGNORECASE)

    description = description.strip()

    # Split on multiple spaces (typically separates merchant from location/phone)
    # The pattern "  " (2+ spaces) typically separates sections
    parts = re.split(r"\s{2,}", description)

    if not parts:
        return description

    # First part is typically the merchant name
    merchant_name = parts[0].strip()

    # Remove phone numbers in format (XXX)XXX-XXXX or XXX-XXX-XXXX at the end
    merchant_name = re.sub(r"\s*\(?\d{3}\)?\s*\d{3}-\d{4}\s*$", "", merchant_name)

    # Remove state codes at the end (like "CA", "TX", "NY" etc)
    merchant_name = re.sub(r"\s+[A-Z]{2}$", "", merchant_name)

    # Title case the result for readability
    merchant_name = " ".join(word.title() for word in merchant_name.split())

    return merchant_name


def mkdir_p(path):
    os.makedirs(path, exist_ok=True)


def now_iso():
    # Use timezone-aware UTC timestamp
    return datetime.now(timezone.utc).isoformat()


def load_state(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def save_state_atomic(path, obj):
    """Write JSON to a temp file then atomically replace the destination."""
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        # If replace failed, try to remove the temp file. Only catch OSError for filesystem ops.
        try:
            os.remove(tmp)
        except OSError:
            # If we can't remove the temp file, log and re-raise the original exception.
            LOG.warning("Failed to remove temp file %s: %s", tmp, e)
        raise


def merchant_slug(s: str) -> str:
    """Create a compact slug from merchant/description text."""
    if not s:
        return ""
    s = str(s).lower()
    # remove common company suffixes
    s = re.sub(r"\b(inc|llc|ltd|co|corp|company|the)\b", "", s)
    # keep alnum and replace others with hyphens
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def compute_import_id(date: str, amount: float, merchant: str) -> str:
    """Deterministic import id for a transaction.

    Uses date (ISO), amount in cents (rounded), and normalized merchant slug.
    Returns a sha256 hex digest.
    """
    cents = int(round(float(amount) * 100))
    key = f"{date}|{cents}|{merchant_slug(merchant)}"
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return h


def parse_date_safe(s):
    """Safely parse a date string into ISO format (YYYY-MM-DD).

    Args:
        s: Input date string to parse

    Returns:
        str: Date in YYYY-MM-DD format, or None if parsing fails
    """
    if pd.isna(s) or not s:
        return None

    s = str(s).strip()
    current_year = datetime.now().year

    # Try parsing the date as-is first
    dt = dateparser.parse(s)
    if dt is not None:
        return dt.date().isoformat()

    # If first attempt fails, try appending current year
    dt = dateparser.parse(f"{s} {current_year}")
    if dt is not None:
        return dt.date().isoformat()

    return None


def parse_date(s: str) -> date:
    """Parse a date string and return a datetime.date.

    Raises ValueError if parsing fails. This is a small helper intended for
    callers that want a date object (unlike parse_date_safe which returns an ISO
    string or None).
    """
    if s is None:
        raise ValueError("No date string provided")
    parsed = dateparser.parse(str(s))
    if not parsed:
        raise ValueError(f"Could not parse date: {s}")
    return parsed.date()


def normalize_splitwise_date_to_local(date_str: str) -> str:
    """Normalize Splitwise date/time strings into a local YYYY-MM-DD date.

    Some Splitwise API results include UTC timestamps like
    "2026-04-07T02:35:44Z". Those should be converted to the local calendar
    date before storing/exporting so the sheet matches the user-visible Splitwise
    date.
    """
    if not date_str:
        return date_str

    try:
        parsed = dateparser.parse(str(date_str))
        if parsed is None:
            raise ValueError("Could not parse date")

        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()

        return parsed.date().isoformat()
    except Exception:
        normalized = str(date_str)
        if "T" in normalized:
            return normalized.split("T")[0]
        return normalized


def parse_float_safe(v) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def generate_fingerprint(
    date_val: str, amount_val: Union[str, float], desc_val: str
) -> str:
    """Generate a stable fingerprint for a transaction.

    Args:
        date_val: Date string in any parseable format
        amount_val: Transaction amount (string or float)
        desc_val: Transaction description

    Returns:
        A stable fingerprint string for the transaction
    """
    try:
        # Parse and normalize date
        date_obj = dateparser.parse(str(date_val))
        date_str = date_obj.strftime("%Y-%m-%d") if date_obj else "unknown_date"

        # Normalize amount to 2 decimal places as string
        try:
            amount = float(amount_val)
            amount_str = f"{amount:.2f}"
        except (ValueError, TypeError):
            amount_str = str(amount_val).strip()

        # Normalize description
        desc = (desc_val or "").strip()

        # Create fingerprint
        fingerprint_str = f"{date_str}|{amount_str}|{desc}"
        return hashlib.sha256(fingerprint_str.encode("utf-8")).hexdigest()
    except Exception as e:
        LOG.error(f"Error generating fingerprint: {e}")
        # Fallback to a less reliable but more robust method
        return hashlib.sha256(
            f"{date_val}|{amount_val}|{desc_val}".encode("utf-8")
        ).hexdigest()


@cache
def _load_amex_category_mapping() -> Dict:
    """Load and cache the Amex category to Splitwise category mapping.

    Returns:
        Dict mapping Amex category names to Splitwise category paths (Category > Subcategory).
    """
    mapping_path = os.path.join(PROJECT_ROOT, "config", "amex_category_mapping.json")
    try:
        if os.path.exists(mapping_path):
            with open(mapping_path, "r") as f:
                result = json.load(f)
            LOG.info(f"Loaded {len(result)} Amex category mappings")
            return result
        else:
            LOG.warning(f"Amex category mapping file not found: {mapping_path}")
            return {}
    except Exception as e:
        LOG.error(f"Error loading Amex category mapping: {e}")
        return {}


@cache
def _load_splitwise_category_ids() -> Dict[str, Any]:
    """Load Splitwise category ID mappings from JSON (cached).

    Returns:
        Dict with 'category_mapping' (full path -> IDs) and 'category_lookup' (name -> [IDs])
    """
    mapping_path = os.path.join(PROJECT_ROOT, "config", "splitwise_category_ids.json")
    try:
        if os.path.exists(mapping_path):
            with open(mapping_path, "r") as f:
                result = json.load(f)
            LOG.debug(
                f"Loaded {len(result.get('category_mapping', {}))} category ID mappings"
            )
            return result
        else:
            LOG.warning(f"Splitwise category IDs file not found: {mapping_path}")
            return {"category_mapping": {}, "category_lookup": {}}
    except Exception as e:
        LOG.error(f"Error loading Splitwise category IDs: {e}")
        return {"category_mapping": {}, "category_lookup": {}}


def _resolve_category_ids(category_path: str) -> Optional[Dict[str, Any]]:
    """Resolve a category path (e.g., 'Transportation > Taxi') to category and subcategory IDs.

    Args:
        category_path: Full category path in format 'Category > Subcategory'

    Returns:
        Dict with category_id, category_name, subcategory_id, subcategory_name, or None
    """
    category_ids = _load_splitwise_category_ids()
    category_mapping = category_ids.get("category_mapping", {})

    if category_path in category_mapping:
        return category_mapping[category_path]

    # Try to find by subcategory name alone (if unambiguous)
    category_lookup = category_ids.get("category_lookup", {})
    if " > " in category_path:
        subcategory_name = category_path.split(" > ")[1]
        matches = category_lookup.get(subcategory_name, [])
        if len(matches) == 1:
            # Unambiguous match
            match = matches[0]
            return {
                "category_id": match["category_id"],
                "category_name": match["category_name"],
                "subcategory_id": match["subcategory_id"],
                "subcategory_name": subcategory_name,
            }

    LOG.warning(f"Could not resolve category path: {category_path}")
    return None


@cache
def _load_merchant_lookup() -> Dict:
    """Load and cache the merchant category lookup from JSON.

    Returns:
        Dict mapping normalized merchant names to category info.
    """
    lookup_path = os.path.join(PROJECT_ROOT, "config", "merchant_category_lookup.json")
    try:
        if os.path.exists(lookup_path):
            with open(lookup_path, "r") as f:
                result = json.load(f)
            LOG.info(f"Loaded {len(result)} merchants from lookup")
            return result
        else:
            LOG.warning(f"Merchant lookup file not found: {lookup_path}")
            return {}
    except Exception as e:
        LOG.error(f"Error loading merchant lookup: {e}")
        return {}


@cache
def _load_category_config() -> Dict:
    """Load and cache the category configuration from YAML.

    Returns:
        Dict containing the category configuration with default values if not found.
    """
    default_config = {
        "default_category": {
            "id": 2,  # Uncategorized category
            "name": "Uncategorized",
            "subcategory_id": 18,  # General subcategory
            "subcategory_name": "General",
        },
        "patterns": [],
    }

    try:
        LOG.info(f"Looking for config files in: {CFG_PATHS}")
        for path in CFG_PATHS:
            LOG.info(f"Checking if config file exists: {path} - {path.exists()}")
            if path.exists():
                LOG.info(f"Loading config from: {path}")
                config = load_yaml(path)
                LOG.info(f"Loaded config keys: {list(config.keys())}")
                if "category_inference" in config:
                    LOG.info("Successfully loaded category_inference config")
                    return config["category_inference"]

        # Fallback to default config if no config file found
        LOG.warning(f"No config file found in any of: {CFG_PATHS}")
        LOG.warning("Using default category configuration")
        return default_config
    except Exception as e:
        LOG.error(f"Error loading category config: {e}")
        return default_config


def infer_category(transaction: Dict[str, Any]) -> Dict[str, Any]:
    """Infer the most likely category for a transaction using config patterns.

    Args:
        transaction: Dictionary containing transaction details with:
            - description (str): Transaction description
            - merchant (str, optional): Merchant name
            - amount (float): Transaction amount
            - category (str, optional): Amex-provided category

    Returns:
        dict: Dictionary with 'category_id', 'category_name', 'subcategory_id',
              'subcategory_name', and 'confidence' if found
    """
    if not transaction:
        return {}

    # Clean the merchant name first
    merchant = clean_merchant_name(
        transaction.get("merchant") or transaction.get("description", "")
    )
    description = (transaction.get("description") or "").lower()

    # Get category config
    category_config = _load_category_config()
    default_category = category_config.get("default_category", {})

    # Log the transaction being processed with cleaned merchant
    LOG.info(
        f"Processing transaction - Description: '{description}', Cleaned Merchant: '{merchant}'"
    )

    # STEP 1: Try merchant lookup first (highest confidence)
    merchant_lookup = _load_merchant_lookup()
    merchant_key = merchant.lower()
    if merchant_key in merchant_lookup:
        merchant_info = merchant_lookup[merchant_key]
        category_name = merchant_info["category"]
        subcategory_name = merchant_info.get("subcategory")
        confidence_score = merchant_info.get("confidence", 1.0)

        # Construct full category path if subcategory exists
        if subcategory_name and " > " not in category_name:
            category_path = f"{category_name} > {subcategory_name}"
        else:
            category_path = category_name

        LOG.info(
            f"Merchant lookup match: '{merchant}' → {category_path} "
            f"(confidence: {confidence_score:.2f}, occurrences: {merchant_info.get('count', 0)})"
        )

        # Try to resolve to IDs (category_path might be a full path or just a name)
        if " > " not in category_path:
            # Old format without subcategory - try to find the category
            category_ids = _resolve_category_ids(f"Food and drink > {category_path}")
            if not category_ids:
                category_ids = _resolve_category_ids(
                    f"Transportation > {category_path}"
                )
            if not category_ids:
                category_ids = _resolve_category_ids(f"Home > {category_path}")
            # Add more categories as needed
        else:
            # New format with full path
            category_ids = _resolve_category_ids(category_path)

        if category_ids:
            return {
                **category_ids,
                "confidence": f"high_{confidence_score:.2f}",
                "matched_pattern": None,
                "matched_in": "merchant_lookup",
            }
        else:
            # Fallback to name-only if ID resolution fails
            return {
                "category_id": None,
                "category_name": category_name,
                "subcategory_id": None,
                "subcategory_name": None,
                "confidence": f"high_{confidence_score:.2f}",
                "matched_pattern": None,
                "matched_in": "merchant_lookup",
            }

    # STEP 2: Try Amex category field (high confidence - from credit card statement)
    amex_category = transaction.get("amex_category") or transaction.get("category")
    if amex_category and isinstance(amex_category, str) and amex_category.strip():
        amex_category = amex_category.strip()
        amex_mapping = _load_amex_category_mapping()

        if amex_category in amex_mapping:
            category_path = amex_mapping[amex_category]
            LOG.info(f"Amex category match: '{amex_category}' → {category_path}")

            # Resolve to IDs
            category_ids = _resolve_category_ids(category_path)
            if category_ids:
                return {
                    **category_ids,
                    "confidence": "high_0.95",
                    "matched_pattern": amex_category,
                    "matched_in": "amex_category",
                }
            else:
                # Fallback if ID resolution fails
                return {
                    "category_id": None,
                    "category_name": category_path,
                    "subcategory_id": None,
                    "subcategory_name": None,
                    "confidence": "high_0.95",
                    "matched_pattern": amex_category,
                    "matched_in": "amex_category",
                }
        else:
            # Unknown Amex category - log it for future mapping
            LOG.warning(
                f"Unknown Amex category: '{amex_category}' - add to mapping file"
            )

    # STEP 3: Try regex patterns (existing logic)

    # STEP 2: Try regex patterns - check for matches in both description and merchant
    for category in category_config.get("patterns", []):
        for subcategory in category.get("subcategories", []):
            for pattern in subcategory.get("patterns", []):
                try:
                    # Compile pattern with case-insensitive flag
                    regex = re.compile(pattern, re.IGNORECASE)
                    desc_match = bool(description and regex.search(description))
                    merchant_match = bool(merchant and regex.search(merchant.lower()))

                    if desc_match or merchant_match:
                        match_type = "description" if desc_match else "merchant"
                        LOG.info(
                            f"Matched pattern '{pattern}' in {match_type} to category '{category['name']} > {subcategory['name']}'"
                        )
                        return {
                            "category_id": category["id"],
                            "category_name": category["name"],
                            "subcategory_id": subcategory["id"],
                            "subcategory_name": subcategory["name"],
                            "confidence": "high",
                            "matched_pattern": pattern,
                            "matched_in": match_type,
                        }
                except re.error as e:
                    LOG.warning(f"Invalid regex pattern '{pattern}': {e}")
                    continue

    # Log when no match is found
    LOG.info(
        f"No category match found for transaction. Description: '{description}', Cleaned Merchant: '{merchant}'"
    )

    # Return the default "Uncategorized" category
    return {
        "category_id": default_category.get("id", 2),  # Uncategorized category
        "category_name": default_category.get("name", "Uncategorized"),
        "subcategory_id": default_category.get(
            "subcategory_id", 18
        ),  # General subcategory
        "subcategory_name": default_category.get("subcategory_name", "General"),
        "confidence": "low",
        "matched_pattern": None,
        "matched_in": None,
    }
