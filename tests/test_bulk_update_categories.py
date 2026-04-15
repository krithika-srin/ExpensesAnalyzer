import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
from src.update.bulk_update_categories import (
    find_expenses_to_update,
    update_expenses,
    main,
)
from src.constants.export_columns import ExportColumns

@pytest.fixture
def sample_expenses():
    return pd.DataFrame([
        {ExportColumns.ID: 1, ExportColumns.DESCRIPTION: "SpotHero Parking", ExportColumns.CATEGORY: "Travel", ExportColumns.DATE: "2026-01-01", ExportColumns.AMOUNT: 15.0},
        {ExportColumns.ID: 2, ExportColumns.DESCRIPTION: "Amazon order", ExportColumns.CATEGORY: "Shopping", ExportColumns.DATE: "2026-01-02", ExportColumns.AMOUNT: 50.0},
        {ExportColumns.ID: 3, ExportColumns.DESCRIPTION: "AWS Monthly", ExportColumns.CATEGORY: "Business", ExportColumns.DATE: "2026-01-03", ExportColumns.AMOUNT: 100.0},
    ])

def test_find_expenses_to_update(sample_expenses):
    client = MagicMock()
    client.get_my_expenses_by_date_range.return_value = sample_expenses
    
    # Merchant filter
    res = find_expenses_to_update(client, MagicMock(), MagicMock(), merchant_filter="SpotHero")
    assert len(res) == 1
    
    # Exclude filter
    res = find_expenses_to_update(client, MagicMock(), MagicMock(), merchant_filter="Amazon", exclude_merchant="AWS")
    assert len(res) == 1
    assert "order" in res.iloc[0][ExportColumns.DESCRIPTION]
    
    # Category filter
    res = find_expenses_to_update(client, MagicMock(), MagicMock(), current_category_filter="Travel")
    assert len(res) == 1

def test_update_expenses(sample_expenses):
    client = MagicMock()
    # Mock the nested Splitwise object
    exp_mock = MagicMock()
    client.sObj.getExpense.return_value = exp_mock
    
    res = update_expenses(client, sample_expenses.head(1), 9, dry_run=False)
    assert res == 1
    client.sObj.updateExpense.assert_called_once()

def test_update_expenses_dry_run(sample_expenses):
    client = MagicMock()
    res = update_expenses(client, sample_expenses, 9, dry_run=True)
    assert res == 0
    client.sObj.updateExpense.assert_not_called()

@patch("src.update.bulk_update_categories.SplitwiseClient")
@patch("src.update.bulk_update_categories.find_expenses_to_update")
@patch("src.update.bulk_update_categories.update_expenses")
def test_main_dry_run(mock_update, mock_find, mock_client_cls, sample_expenses):
    mock_find.return_value = sample_expenses
    mock_update.return_value = 0
    
    with patch("sys.argv", ["script", "--merchant", "SpotHero", "--subcategory-id", "9", "--dry-run"]):
        from src.update.bulk_update_categories import main
        assert main() == 0
        mock_update.assert_called_once_with(mock_client_cls.return_value, sample_expenses, 9, dry_run=True)

@patch("src.update.bulk_update_categories.SplitwiseClient")
@patch("src.update.bulk_update_categories.find_expenses_to_update")
@patch("src.update.bulk_update_categories.update_expenses")
@patch("builtins.input", return_value="yes")
def test_main_live_with_confirmation(mock_input, mock_update, mock_find, mock_client_cls, sample_expenses):
    mock_find.return_value = sample_expenses
    mock_update.return_value = 3
    
    with patch("sys.argv", ["script", "--merchant", "SpotHero", "--subcategory", "parking"]):
        from src.update.bulk_update_categories import main
        assert main() == 3
        mock_update.assert_called_once_with(mock_client_cls.return_value, sample_expenses, 9, dry_run=False)
