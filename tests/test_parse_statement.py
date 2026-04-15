import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from src.import_statement.parse_statement import (
    _is_credit,
    _is_likely_refund,
    extract_reference_id,
    parse_amount_safe,
    parse_csv,
    parse_statement,
)

# Base Path
TEST_DATA_DIR = Path(__file__).parent / "data"

def test_parse_amount_safe():
    assert parse_amount_safe("1200.50") == 1200.50
    assert parse_amount_safe("$1,200.50") == 1200.50
    assert parse_amount_safe("(150.50)") == -150.50
    assert parse_amount_safe("($1,500.25)") == -1500.25
    assert parse_amount_safe(-50) == -50.0
    assert parse_amount_safe(pd.NA) == 0.0

def test_extract_reference_id():
    assert extract_reference_id("1234567890123") == "1234567890123"
    assert extract_reference_id("REF: 123456789") == "123456789"
    assert extract_reference_id("Ticket Number: 0987654321") == "0987654321"
    assert extract_reference_id("TXN123ABC456") == "TXN123ABC456"
    assert extract_reference_id("NaN") is None
    assert extract_reference_id("") is None

def test_is_credit():
    # Amex logic: negative is credit
    assert _is_credit({"_bank": "amex", "amount": -100}) is True
    assert _is_credit({"_bank": "amex", "amount": 100}) is False
    # BoFA logic: positive is credit
    assert _is_credit({"_bank": "bofa", "amount": 50}) is True
    assert _is_credit({"_bank": "bofa", "amount": -50}) is False

def test_is_likely_refund():
    assert _is_likely_refund({"is_credit": False, "description": "Refund", "category": ""}) is False
    assert _is_likely_refund({"is_credit": True, "description": "Autopay Payment - Thank You", "category": ""}) is False
    assert _is_likely_refund({"is_credit": True, "description": "reward points", "category": ""}) is False
    assert _is_likely_refund({"is_credit": True, "description": "TARGET RETURN", "category": "Shopping"}) is True

def test_parse_csv_amex():
    path = TEST_DATA_DIR / "amex" / "amex_sample.csv"
    df = parse_csv(str(path))
    assert len(df) == 4
    assert all(df["amount"] > 0)
    refund_row = df[df["description"].str.contains("AIRBNB")].iloc[0]
    assert bool(refund_row["is_refund"]) is True
    assert bool(refund_row["is_credit"]) is True
    assert refund_row["amount"] == 2190.75
    purchase_row = df[df["description"] == "DELTA AIR LINES"].iloc[0]
    assert bool(purchase_row["is_refund"]) is False
    assert bool(purchase_row["is_credit"]) is False
    assert purchase_row["amount"] == 11.20

def test_parse_csv_bofa():
    path = TEST_DATA_DIR / "bofa" / "bofa_sample.csv"
    df = parse_csv(str(path))
    assert len(df) == 4
    assert all(df["amount"] > 0)
    refund_row = df[df["description"] == "TARGET RETURN"].iloc[0]
    assert bool(refund_row["is_refund"]) is True
    assert bool(refund_row["is_credit"]) is True
    assert refund_row["amount"] == 50.0
    expense_row = df[df["description"].str.contains("AMAZON")].iloc[0]
    assert bool(expense_row["is_refund"]) is False
    assert bool(expense_row["is_credit"]) is False
    assert expense_row["amount"] == 39.54


def test_parse_csv_bofa_skips_recurring_check_payments():
    with patch("src.import_statement.parse_statement.BANK_CONFIG") as mock_cfg:
        mock_cfg.detect_bank_from_path.return_value = "bofa"
        mock_cfg.validate_csv_headers.return_value = None
        mock_cfg.get_bank_config.return_value = {
            "name": "bofa",
            "date_column": "Date",
            "description_columns": ["Description"],
            "amount_column": "Amount",
            "category_column": "Category",
            "reference_column": "Reference",
            "address_column": "Address",
            "date_format": "%m/%d/%Y",
            "skip_rows": 0,
        }
        with patch("src.import_statement.parse_statement.pd.read_csv") as mock_read:
            mock_read.return_value = pd.DataFrame([
                {
                    "Date": "04/06/2026",
                    "Description": "ONLINE/MOBILE RECURRING FROM CHK 9200",
                    "Amount": "77.00",
                },
                {
                    "Date": "04/06/2026",
                    "Description": "TARGET RETURN",
                    "Amount": "50.00",
                },
            ])
            df = parse_csv("data/bank_statements/bank of america/bofa_card2_2026.csv")
            assert len(df) == 1
            assert df.iloc[0]["description"] == "TARGET RETURN"


def test_parse_bofa_custom_mock():
    with patch("src.import_statement.parse_statement.BANK_CONFIG") as mock_cfg:
        mock_cfg.get_bank_config.return_value = {
            "name": "bofa",
            "date_col": "Date",
            "description_col": "Description",
            "amount_col": "Amount",
            "date_format": "%m/%d/%Y",
            "skip_rows": 0
        }
        with patch("src.import_statement.parse_statement.pd.read_csv") as mock_read:
            mock_read.return_value = pd.DataFrame([
                {"Date": "04/01/2026", "Description": "STARBUCKS", "Amount": "-10.0"}
            ])
            df = parse_statement("data/bank_statements/bofa/dummy_bofa.csv")
            assert not df.empty
            assert df.iloc[0]["description"] == "STARBUCKS"
