"""Extended SplitwiseClient tests for get_expense_by_id, add_expense_from_txn, and get_splitwise_client."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from pathlib import Path

import pandas as pd
from src.common.splitwise_client import SplitwiseClient, get_splitwise_client
from src.constants.export_columns import ExportColumns

@pytest.fixture
def mock_env():
    with patch.dict("os.environ", {
        "SPLITWISE_CONSUMER_KEY": "fake",
        "SPLITWISE_CONSUMER_SECRET": "fake",
        "SPLITWISE_API_KEY": "fake"
    }):
        yield

@pytest.fixture
def client(mock_env):
    with patch("src.common.splitwise_client.Splitwise"):
        return SplitwiseClient()

# === get_expense_by_id ===
def test_get_expense_by_id_none(client):
    assert client.get_expense_by_id(None) is None

def test_get_expense_by_id_from_api(client):
    mock_exp = MagicMock()
    mock_exp.getId.return_value = 1
    mock_exp.getDate.return_value = "2026-01-01"
    mock_exp.getDescription.return_value = "Test"
    mock_exp.getCost.return_value = "10.0"
    mock_exp.getDetails.return_value = "det"
    mock_exp.getCategory.return_value.getName.return_value = "Cat"
    mock_exp.deleted_at = None
    client.sObj.getExpense.return_value = mock_exp
    
    result = client.get_expense_by_id(1, use_cache=False)
    assert result is not None
    assert result["id"] == 1
    assert result["description"] == "Test"

def test_get_expense_by_id_deleted(client):
    mock_exp = MagicMock()
    mock_exp.deleted_at = "2026-01-05"
    client.sObj.getExpense.return_value = mock_exp
    
    result = client.get_expense_by_id(1, use_cache=False)
    assert result is None

def test_get_expense_by_id_api_error(client):
    client.sObj.getExpense.side_effect = Exception("API fail")
    result = client.get_expense_by_id(1, use_cache=False)
    assert result is None

# === add_expense_from_txn ===
def test_add_expense_from_txn_success(client):
    mock_created = MagicMock()
    mock_created.getId.return_value = 555
    client.sObj.createExpense.return_value = mock_created
    
    txn = {
        "date": "2026-04-01",
        "amount": 50.0,
        "description": "Test expense",
        "category_id": 5,
        "subcategory_id": 10,
        "category_name": "Food",
        "subcategory_name": "Dining",
    }
    result = client.add_expense_from_txn(txn, cc_reference_id="REF123")
    assert result == 555

def test_add_expense_from_txn_no_ref():
    with patch.dict("os.environ", {"SPLITWISE_CONSUMER_KEY": "f", "SPLITWISE_CONSUMER_SECRET": "f", "SPLITWISE_API_KEY": "f"}):
        with patch("src.common.splitwise_client.Splitwise"):
            c = SplitwiseClient()
            with pytest.raises(ValueError, match="cc_reference_id is required"):
                c.add_expense_from_txn({}, cc_reference_id="")

def test_add_expense_from_txn_no_category(client):
    txn = {
        "date": "2026-04-01",
        "amount": 50.0,
        "description": "Test",
        "category_id": None,
    }
    # infer_category should run and assign one, but if it returns None category_id...
    with patch("src.common.splitwise_client.infer_category", return_value={"category_id": None}):
        # Still None => should raise
        # Actually the code sets it to 18 as fallback when infer returns None
        pass
    
    # Test the case where category_id ends up 0
    txn["category_id"] = 0
    with pytest.raises(ValueError, match="Cannot add expense without valid category"):
        client.add_expense_from_txn(txn, cc_reference_id="REF")

def test_add_expense_from_txn_with_users(client):
    mock_created = MagicMock()
    mock_created.getId.return_value = 777
    client.sObj.createExpense.return_value = mock_created
    
    txn = {
        "date": "2026-04-01",
        "amount": 100.0,
        "description": "Split dinner",
        "category_id": 5,
        "subcategory_id": 10,
    }
    users = [
        {"user_id": 101, "paid_share": 100.0, "owed_share": 0.0},
        {"user_id": 202, "paid_share": 0.0, "owed_share": 100.0},
    ]
    result = client.add_expense_from_txn(txn, cc_reference_id="REF456", users=users)
    assert result == 777

def test_add_expense_from_txn_tuple_return(client):
    mock_exp = MagicMock()
    mock_exp.getId.return_value = 888
    client.sObj.createExpense.return_value = (True, mock_exp)
    
    txn = {"date": "2026-04-01", "amount": 10, "description": "T", "category_id": 1, "subcategory_id": 2}
    assert client.add_expense_from_txn(txn, cc_reference_id="R") == 888

def test_add_expense_from_txn_create_error(client):
    client.sObj.createExpense.side_effect = Exception("API fail")
    txn = {"date": "2026-04-01", "amount": 10, "description": "T", "category_id": 1, "subcategory_id": 2}
    with pytest.raises(RuntimeError, match="Failed to create expense"):
        client.add_expense_from_txn(txn, cc_reference_id="R")

def test_add_expense_infers_category(client):
    mock_created = MagicMock()
    mock_created.getId.return_value = 999
    client.sObj.createExpense.return_value = mock_created
    
    txn = {"date": "2026-04-01", "amount": 10, "description": "Test"}
    with patch("src.common.splitwise_client.infer_category", return_value={
        "category_id": 5, "subcategory_id": 10, "category_name": "Food", "subcategory_name": "Dining"
    }):
        result = client.add_expense_from_txn(txn, cc_reference_id="R")
        assert result == 999

# === get_categories ===
def test_get_categories(client):
    client.sObj.getCategories.return_value = [{"id": 1, "name": "Food"}]
    cats = client.get_categories()
    assert len(cats) == 1

# === get_splitwise_client ===
def test_get_splitwise_client_dry_run():
    assert get_splitwise_client(dry_run=True) is None

# === _fetch_expenses_paginated ===
def test_fetch_paginated_full_details(client):
    mock_exp = MagicMock()
    mock_exp.getId.return_value = 1
    mock_exp.deleted_at = None
    
    mock_full = MagicMock()
    mock_full.getId.return_value = 1
    mock_full.deleted_at = None
    
    client.sObj.getExpenses.side_effect = [[mock_exp], []]
    client.sObj.getExpense.return_value = mock_full
    
    res = client._fetch_expenses_paginated("2026-01-01", "2026-01-02", fetch_full_details=True)
    assert len(res) == 1

def test_fetch_paginated_api_error(client):
    client.sObj.getExpenses.side_effect = Exception("Connection error")
    with pytest.raises(Exception, match="Connection error"):
        client._fetch_expenses_paginated("2026-01-01", "2026-01-02")

# === fetch_expenses_with_details ===
def test_fetch_expenses_with_details_cache(client, tmp_path):
    cache_file = tmp_path / "cache.json"
    client._get_expense_cache_path = MagicMock(return_value=cache_file)
    
    mock_exp = MagicMock()
    mock_exp.getId.return_value = 42
    mock_exp.getDate.return_value = "2026-01-01"
    mock_exp.getDescription.return_value = "Test"
    mock_exp.getCost.return_value = "10"
    mock_exp.getDetails.return_value = "d"
    mock_exp.getCategory.return_value.getName.return_value = "C"
    
    client._fetch_expenses_paginated = MagicMock(return_value=[mock_exp])
    
    # miss
    res = client.fetch_expenses_with_details("2026-01-01", "2026-12-31")
    assert 42 in res
    assert cache_file.exists()
    
    # hit
    client._fetch_expenses_paginated.reset_mock()
    res2 = client.fetch_expenses_with_details("2026-01-01", "2026-12-31")
    client._fetch_expenses_paginated.assert_not_called()

# === get_my_expenses_by_date_range ===
def test_get_my_expenses_partner_split(client):
    from src.constants.splitwise import SplitwiseUserId, SPLIT_TYPE_PARTNER
    client.get_current_user_id = MagicMock(return_value=101)
    
    mock_exp = MagicMock()
    mock_exp.getId.return_value = 1
    mock_exp.getDate.return_value = "2026-01-01T00:00:00Z"
    mock_exp.getCreatedAt.return_value = "2026-01-01T00:00:00Z"
    mock_exp.getUpdatedAt.return_value = "2026-01-01T00:00:00Z"
    mock_exp.getDescription.return_value = "Groceries"
    mock_exp.getCost.return_value = "50.0"
    mock_exp.getDetails.return_value = ""
    mock_exp.getCategory.return_value.getName.return_value = "Food"
    mock_exp.getCreationMethod.return_value = "equal"
    
    mock_user_me = MagicMock()
    mock_user_me.getId.return_value = 101
    mock_user_me.getFirstName.return_value = "Me"
    mock_user_me.getPaidShare.return_value = "50.0"
    mock_user_me.getOwedShare.return_value = "25.0"
    
    mock_ids = MagicMock()
    mock_ids.SELF_EXPENSE = 303
    mock_ids.PARTNER_EXPENSE = 202
    
    with patch("src.common.splitwise_client.SplitwiseUserId", mock_ids):
        
        mock_user_partner = MagicMock()
        mock_user_partner.getId.return_value = 202
        mock_user_partner.getFirstName.return_value = "Partner"
        mock_user_partner.getPaidShare.return_value = "0.0"
        mock_user_partner.getOwedShare.return_value = "25.0"
        
        mock_exp.getUsers.return_value = [mock_user_me, mock_user_partner]
        client._fetch_expenses_paginated = MagicMock(return_value=[mock_exp])
        
        df = client.get_my_expenses_by_date_range(datetime(2026, 1, 1), datetime(2026, 1, 31))
        assert len(df) == 1
        assert df.iloc[0][ExportColumns.SPLIT_TYPE] == SPLIT_TYPE_PARTNER

# === _get_expense_cache_path ===
def test_get_expense_cache_path_same_year(client):
    path = client._get_expense_cache_path("2026-01-01", "2026-12-31")
    assert "2026" in str(path)

def test_get_expense_cache_path_diff_year(client):
    path = client._get_expense_cache_path("2025-01-01", "2026-12-31")
    assert "2025_2026" in str(path)
