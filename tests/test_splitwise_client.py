import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, date
import pandas as pd
import datetime as dt_module

from src.common.splitwise_client import SplitwiseClient

@pytest.fixture
def mock_env():
    with patch.dict("os.environ", {
        "SPLITWISE_CONSUMER_KEY": "fake_key",
        "SPLITWISE_CONSUMER_SECRET": "fake_secret",
        "SPLITWISE_API_KEY": "fake_api"
    }):
        yield

@pytest.fixture
def splitwise_client(mock_env):
    with patch("src.common.splitwise_client.Splitwise"):
        return SplitwiseClient()

def test_init_raises_value_error_if_missing_credentials():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError):
            SplitwiseClient()

def test_get_current_user_id(splitwise_client):
    mock_user = MagicMock()
    mock_user.getId.return_value = 12345
    splitwise_client.sObj.getCurrentUser.return_value = mock_user
    assert splitwise_client.get_current_user_id() == 12345

def test_fetch_expenses_paginated(splitwise_client):
    mock_exp1 = MagicMock()
    mock_exp1.deleted_at = None
    mock_exp2 = MagicMock()
    mock_exp2.deleted_at = "deleted_timestamp"
    splitwise_client.sObj.getExpenses.side_effect = [[mock_exp1, mock_exp2], []]
    res = splitwise_client._fetch_expenses_paginated("2026-01-01", "2026-01-31")
    assert len(res) == 1
    assert res[0] == mock_exp1
    splitwise_client.sObj.getExpenses.assert_called()

def test_find_expense_by_cc_reference(splitwise_client):
    mock_df = pd.DataFrame({
        "id": [11, 22],
        "amount": [50.0, 100.0],
        "date": ["2026-04-01T00:00:00Z", "2026-04-02T00:00:00Z"],
        "description": ["Target Purchase", "Amazon.com"],
        "date_updated": ["2026-04-01", "2026-04-02"],
        "Details": ["TXN-11", "TXN-22"]
    })
    with patch.object(splitwise_client, "get_my_expenses_by_date_range", return_value=mock_df):
        match = splitwise_client.find_expense_by_cc_reference(cc_reference_id="TXN-22")
        assert match["id"] == 22
        match2 = splitwise_client.find_expense_by_cc_reference(amount=50.0, date="2026-04-01")
        assert match2["id"] == 11

@patch("os.getenv")
def test_get_my_expenses_pagination_detailed(mock_getenv):
    mock_getenv.return_value = "dummy_val"
    client = SplitwiseClient()
    mock_sw = MagicMock()
    client.sObj = mock_sw
    
    expense1 = MagicMock()
    expense1.getId.return_value = 1
    expense1.getCost.return_value = "10.0"
    expense1.getDate.return_value = "2026-01-01T00:00:00Z"
    expense1.getDescription.return_value = "Test1"
    expense1.getDetails.return_value = "details"
    expense1.getCurrencyCode.return_value = "USD"
    expense1.deleted_at = None
    expense1.getDeletedAt.return_value = None
    expense1.getUpdatedAt.return_value = "2026-01-01T00:00:00Z"
    expense1.getCreatedAt.return_value = "2026-01-01T00:00:00Z"
    expense1.getCategory.return_value.getName.return_value = "Food"
    
    user1 = MagicMock()
    user1.getId.return_value = 12345
    user1.getPaidShare.return_value = "10.0"
    user1.getOwedShare.return_value = "5.0"
    user1.getFirstName.return_value = "Me"
    user1.getLastName.return_value = "Self"
    expense1.getUsers.return_value = [user1]
    
    mock_sw.getExpenses.side_effect = [[expense1], []]
    mock_sw.getCurrentUser.return_value.getId.return_value = 12345
    
    df = client.get_my_expenses_by_date_range(
        dt_module.date(2026, 1, 1), 
        dt_module.date(2026, 1, 2)
    )
    assert len(df) == 1

@patch("os.getenv")
def test_get_my_expenses_error_handling(mock_getenv):
    mock_getenv.return_value = "dummy_val"
    client = SplitwiseClient()
    mock_sw = MagicMock()
    client.sObj = mock_sw
    mock_sw.getExpenses.side_effect = Exception("API Error")
    
    with pytest.raises(Exception, match="API Error"):
        client.get_my_expenses_by_date_range(
            dt_module.date(2026, 1, 1), 
            dt_module.date(2026, 1, 2)
        )
