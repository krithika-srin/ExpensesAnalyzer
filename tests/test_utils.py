"""Additional utils tests to boost coverage for uncovered functions/branches."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, date
import dateparser
import os
import json
import tempfile

from src.common.utils import (
    parse_date_string,
    format_date,
    load_yaml,
    clean_description_for_splitwise,
    clean_merchant_name,
    mkdir_p,
    now_iso,
    load_state,
    save_state_atomic,
    merchant_slug,
    compute_import_id,
    parse_date_safe,
    parse_date,
    normalize_splitwise_date_to_local,
    parse_float_safe,
    generate_fingerprint,
    infer_category,
    _resolve_category_ids,
)

# === parse_date_string ===
def test_parse_date_string():
    assert parse_date_string("2026-04-01") == date(2026, 4, 1)
    with pytest.raises(ValueError):
        parse_date_string("invalid")

# === format_date ===
def test_format_date_datetime():
    assert format_date(datetime(2026, 4, 1, 12, 0)) == "2026-04-01"

def test_format_date_date():
    assert format_date(date(2026, 4, 1)) == "2026-04-01"

# === load_yaml ===
def test_load_yaml(tmp_path):
    f = tmp_path / "test.yaml"
    f.write_text("key: value\n")
    result = load_yaml(str(f))
    assert result == {"key": "value"}

# === clean_description multiline ===
@patch("src.common.utils._load_merchant_lookup", return_value={})
def test_clean_description_multiline(mock_lookup):
    desc = "LODGING\nHilton Garden Inn\n12345678 99999"
    result = clean_description_for_splitwise(desc)
    assert "Hilton" in result

@patch("src.common.utils._load_merchant_lookup", return_value={})
def test_clean_description_empty(mock_lookup):
    assert clean_description_for_splitwise("") == ""
    assert clean_description_for_splitwise(None) == ""

@patch("src.common.utils._load_merchant_lookup", return_value={})
def test_clean_description_with_url(mock_lookup):
    result = clean_description_for_splitwise("UBER EATS help.uber.com CA")
    assert "uber.com" not in result.lower()

@patch("src.common.utils._load_merchant_lookup", return_value={})
def test_clean_description_with_phone(mock_lookup):
    result = clean_description_for_splitwise("LULULEMON ATHLETICA (877)263-9300")
    assert "(877)" not in result

@patch("src.common.utils._load_merchant_lookup", return_value={})
def test_clean_description_concat_words(mock_lookup):
    result = clean_description_for_splitwise("McDonalds")
    assert "Mc Donalds" in result or "McDonalds" in result  # might or might not split

@patch("src.common.utils._load_merchant_lookup", return_value={})
def test_clean_description_fallback_short(mock_lookup):
    # Short result after cleaning triggers fallback
    result = clean_description_for_splitwise("AB")
    assert len(result) >= 2

@patch("src.common.utils._load_merchant_lookup", return_value={"netflix": {"canonical_name": "Netflix", "category": "Entertainment"}})
def test_clean_description_merchant_lookup(mock_lookup):
    result = clean_description_for_splitwise("NETFLIX")
    assert result == "Netflix"

# === clean_merchant_name ===
def test_clean_merchant_name_empty():
    assert clean_merchant_name("") == ""
    assert clean_merchant_name(None) == ""

def test_clean_merchant_name_with_prefix():
    result = clean_merchant_name("GglPay CINEMARK     PLANO               TX")
    assert "Cinemark" in result

def test_clean_merchant_name_with_phone():
    result = clean_merchant_name("LULULEMON ATHLETICA (877)263-9300       CA")
    assert "Lululemon" in result

# === mkdir_p ===
def test_mkdir_p(tmp_path):
    new_dir = tmp_path / "a" / "b" / "c"
    mkdir_p(str(new_dir))
    assert os.path.isdir(str(new_dir))

# === now_iso ===
def test_now_iso():
    result = now_iso()
    assert "T" in result

# === load_state / save_state_atomic ===
def test_load_state_missing():
    assert load_state("/nonexistent/path.json") == {}

def test_save_and_load_state(tmp_path):
    path = str(tmp_path / "state.json")
    save_state_atomic(path, {"key": "value"})
    state = load_state(path)
    assert state == {"key": "value"}

# === merchant_slug ===
def test_merchant_slug():
    assert merchant_slug("Amazon Inc") == "amazon"
    assert merchant_slug("") == ""
    assert merchant_slug("UBER EATS LLC") == "uber-eats"

# === compute_import_id ===
def test_compute_import_id():
    h1 = compute_import_id("2026-04-01", 50.0, "Test")
    h2 = compute_import_id("2026-04-01", 50.0, "Test")
    assert h1 == h2
    h3 = compute_import_id("2026-04-01", 50.0, "Other")
    assert h1 != h3

# === parse_date_safe ===
def test_parse_date_safe():
    assert parse_date_safe("2026-04-01") == "2026-04-01"
    assert parse_date_safe("") is None
    assert parse_date_safe(None) is None

def test_parse_date_safe_ambiguous():
    # Test with a format that needs year appended
    result = parse_date_safe("Apr 1")
    assert result is not None

# === parse_date ===
def test_parse_date():
    assert parse_date("2026-04-01") == date(2026, 4, 1)


def test_normalize_splitwise_date_to_local():
    timestamp = "2026-04-07T02:35:44Z"
    expected = dateparser.parse(timestamp).astimezone().date().isoformat()
    assert normalize_splitwise_date_to_local(timestamp) == expected
    assert normalize_splitwise_date_to_local("2026-04-06") == "2026-04-06"


def test_parse_date_invalid():
    with pytest.raises(ValueError):
        parse_date(None)
    with pytest.raises(ValueError):
        parse_date("not_a_date_zzz_xyz")

# === parse_float_safe ===
def test_parse_float_safe():
    assert parse_float_safe("10.5") == 10.5
    assert parse_float_safe(None) == 0.0
    assert parse_float_safe("abc") == 0.0

# === generate_fingerprint ===
def test_generate_fingerprint():
    fp = generate_fingerprint("2026-04-01", "50.00", "Test")
    assert isinstance(fp, str)
    assert len(fp) == 64

def test_generate_fingerprint_bad_amount():
    fp = generate_fingerprint("2026-04-01", "bad", "Test")
    assert isinstance(fp, str)

def test_generate_fingerprint_errors():
    # Trigger exception path
    fp = generate_fingerprint(None, None, None)
    assert isinstance(fp, str)

# === _resolve_category_ids ===
@patch("src.common.utils._load_splitwise_category_ids")
def test_resolve_category_ids_exact(mock_load):
    mock_load.return_value = {
        "category_mapping": {"Food > Dining": {"category_id": 1, "subcategory_id": 2}},
        "category_lookup": {}
    }
    result = _resolve_category_ids("Food > Dining")
    assert result["category_id"] == 1

@patch("src.common.utils._load_splitwise_category_ids")
def test_resolve_category_ids_lookup(mock_load):
    mock_load.return_value = {
        "category_mapping": {},
        "category_lookup": {"Dining": [{"category_id": 1, "category_name": "Food", "subcategory_id": 2}]}
    }
    result = _resolve_category_ids("Food > Dining")
    assert result is not None

@patch("src.common.utils._load_splitwise_category_ids")
def test_resolve_category_ids_not_found(mock_load):
    mock_load.return_value = {"category_mapping": {}, "category_lookup": {}}
    result = _resolve_category_ids("Unknown > Thing")
    assert result is None

# === infer_category ===
def test_infer_category_empty():
    assert infer_category(None) == {}
    assert infer_category({}) == {}

@patch("src.common.utils._load_merchant_lookup", return_value={})
@patch("src.common.utils._load_category_config")
def test_infer_category_default(mock_config, mock_lookup):
    mock_config.return_value = {
        "default_category": {"id": 2, "name": "Uncategorized", "subcategory_id": 18, "subcategory_name": "General"},
        "patterns": []
    }
    result = infer_category({"description": "random thing", "amount": 10})
    assert result["category_name"] == "Uncategorized"
    assert result["confidence"] == "low"

@patch("src.common.utils._load_merchant_lookup")
@patch("src.common.utils._load_category_config")
@patch("src.common.utils._resolve_category_ids")
def test_infer_category_merchant_match(mock_resolve, mock_config, mock_lookup):
    mock_lookup.return_value = {"uber": {"category": "Transportation", "subcategory": "Taxi", "confidence": 0.95, "count": 10}}
    mock_config.return_value = {"default_category": {}, "patterns": []}
    mock_resolve.return_value = {"category_id": 5, "category_name": "Transportation", "subcategory_id": 9, "subcategory_name": "Taxi"}
    
    result = infer_category({"description": "Uber ride", "merchant": "Uber", "amount": 15})
    assert result["matched_in"] == "merchant_lookup"

@patch("src.common.utils._load_merchant_lookup", return_value={})
@patch("src.common.utils._load_amex_category_mapping")
@patch("src.common.utils._load_category_config")
@patch("src.common.utils._resolve_category_ids")
def test_infer_category_amex_match(mock_resolve, mock_config, mock_amex, mock_lookup):
    mock_amex.return_value = {"Restaurant": "Food and drink > Dining out"}
    mock_config.return_value = {"default_category": {}, "patterns": []}
    mock_resolve.return_value = {"category_id": 1, "category_name": "Food and drink", "subcategory_id": 2, "subcategory_name": "Dining out"}
    
    result = infer_category({"description": "Some restaurant", "amex_category": "Restaurant", "amount": 50})
    assert result["matched_in"] == "amex_category"

@patch("src.common.utils._load_merchant_lookup", return_value={})
@patch("src.common.utils._load_amex_category_mapping", return_value={"Unknown Cat": "Missing > Path"})
@patch("src.common.utils._load_category_config")
@patch("src.common.utils._resolve_category_ids", return_value=None)
def test_infer_category_amex_no_ids(mock_resolve, mock_config, mock_amex, mock_lookup):
    mock_config.return_value = {"default_category": {}, "patterns": []}
    result = infer_category({"description": "thing", "amex_category": "Unknown Cat", "amount": 5})
    assert result["matched_in"] == "amex_category"
    assert result["category_id"] is None

@patch("src.common.utils._load_merchant_lookup", return_value={})
@patch("src.common.utils._load_category_config")
def test_infer_category_regex_pattern(mock_config, mock_lookup):
    mock_config.return_value = {
        "default_category": {"id": 2, "name": "Uncategorized", "subcategory_id": 18, "subcategory_name": "General"},
        "patterns": [{
            "name": "Transportation",
            "id": 30,
            "subcategories": [{
                "name": "Taxi",
                "id": 31,
                "patterns": ["uber", "lyft"]
            }]
        }]
    }
    result = infer_category({"description": "UBER ride to airport", "amount": 25})
    assert result["category_name"] == "Transportation"
    assert result["subcategory_name"] == "Taxi"
    assert result["confidence"] == "high"
