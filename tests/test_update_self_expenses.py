import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from src.update.update_self_expenses import update_self_expense, main
from src.constants.export_columns import ExportColumns
from src.constants.splitwise import SPLIT_TYPE_SELF

def test_update_self_expense_success():
    client = MagicMock()
    mock_expense = MagicMock()
    mock_user_me = MagicMock()
    mock_user_me.getId.return_value = 101
    mock_user_other = MagicMock()
    mock_user_other.getId.return_value = 202
    mock_expense.getUsers.return_value = [mock_user_me, mock_user_other]
    client.sObj.getExpense.return_value = mock_expense
    success = update_self_expense(client, 999, 100.0, 101)
    assert success is True

def test_update_self_expense_wrong_users():
    client = MagicMock()
    mock_expense = MagicMock()
    mock_user_other1 = MagicMock()
    mock_user_other1.getId.return_value = 202
    mock_user_other2 = MagicMock()
    mock_user_other2.getId.return_value = 303
    mock_expense.getUsers.return_value = [mock_user_other1, mock_user_other2]
    client.sObj.getExpense.return_value = mock_expense
    success = update_self_expense(client, 999, 100.0, 101)
    assert success is False

@patch("src.update.update_self_expenses.SplitwiseClient")
@patch("src.update.update_self_expenses.update_self_expense")
def test_main(mock_update, mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.get_current_user_id.return_value = 101
    
    # Mock df with 3 expenses:
    # 1. Self expense (should be mapped) -> Participant Names: "Balaji, Balaji", SPLIT_TYPE: SPLIT_TYPE_SELF
    # 2. Regular expense (ignored)
    # 3. Another self expense, but without amount (ignored)
    
    mock_df = pd.DataFrame([
        {
            ExportColumns.ID: 900,
            ExportColumns.AMOUNT: "50.0",
            ExportColumns.FRIENDS_SPLIT: "Balaji|paid=25|owed=25; Balaji|paid=25|owed=25",
            ExportColumns.PARTICIPANT_NAMES: "Balaji, Balaji",
            ExportColumns.SPLIT_TYPE: SPLIT_TYPE_SELF,
            ExportColumns.DATE: "2026-04-01",
            ExportColumns.DESCRIPTION: "Uber"
        },
        {
            ExportColumns.ID: 901,
            ExportColumns.AMOUNT: "75.0",
            ExportColumns.FRIENDS_SPLIT: "Balaji|paid=75|owed=37.5; Other|paid=0|owed=37.5",
            ExportColumns.PARTICIPANT_NAMES: "Balaji, Other",
            ExportColumns.SPLIT_TYPE: "equal",
            ExportColumns.DATE: "2026-04-02",
            ExportColumns.DESCRIPTION: "Netflix"
        }
    ])
    
    mock_client.get_my_expenses_by_date_range.return_value = mock_df
    mock_update.return_value = True
    
    with patch("sys.argv", ["script"]):
        with patch("builtins.input", return_value="yes"):
            main()
        
    mock_update.assert_called_once_with(mock_client, 900, 50.0, 101)

@patch("src.update.update_self_expenses.SplitwiseClient")
@patch("src.update.update_self_expenses.update_self_expense")
def test_main_single_expense(mock_update, mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.get_current_user_id.return_value = 101
    
    mock_expense = MagicMock()
    mock_expense.getCost.return_value = "100.0"
    mock_client.sObj.getExpense.return_value = mock_expense
    
    mock_update.return_value = True
    
    with patch("sys.argv", ["script", "--expense-id", "855", "--dry-run"]):
        main()
        
    mock_update.assert_not_called() # dry run
    
    with patch("sys.argv", ["script", "--expense-id", "855"]):
        with patch("builtins.input", return_value="yes"):
            main()
    
    mock_update.assert_called_once_with(mock_client, 855, 100.0, 101)
