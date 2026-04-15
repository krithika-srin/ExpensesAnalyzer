import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
import sys
from src.import_statement.pipeline import process_statement, main

@pytest.fixture
def sample_df():
    return pd.DataFrame([
        {"date": "2026-04-01", "amount": 50.0, "description": "Amazon", "cc_reference_id": "ref123", "is_credit": False},
        {"date": "2026-04-02", "amount": -25.0, "description": "Refund", "cc_reference_id": "ref456", "is_credit": True},
    ])

@patch("src.import_statement.pipeline.parse_statement")
@patch("src.import_statement.pipeline.DatabaseManager")
@patch("src.import_statement.pipeline.SplitwiseClient")
@patch("src.import_statement.pipeline.BankConfig")
def test_process_statement_dry_run(MockBankConfig, MockClient, MockDB, mock_parse_statement):
    mock_parse_statement.return_value = pd.DataFrame([{
        "date": "2026-04-01",
        "description": "Amazon",
        "amount": 10.0,
        "detail": "ref123",
        "cc_reference_id": "ref123",
        "is_credit": False
    }])
    
    mock_db = MagicMock()
    MockDB.return_value = mock_db
    mock_db.get_transaction_by_cc_reference.return_value = None
    
    mock_client = MagicMock()
    MockClient.return_value = mock_client
    mock_client.find_expense_by_cc_reference.return_value = None
    
    with patch("src.import_statement.pipeline.write_to_sheets") as mock_write, patch("src.import_statement.pipeline.mkdir_p"):
        with patch("pandas.DataFrame.to_csv"):
            df = process_statement(
                path="data/bank_statements/amex/statement.csv",
                dry_run=True,
                no_sheet=True,
                start_date="2026-01-01",
                end_date="2026-12-31"
            )
        
    assert df is not None
    assert len(df) == 1
    assert df.iloc[0]["status"] == "would_add"

@patch("src.import_statement.pipeline.parse_statement")
@patch("src.import_statement.pipeline.DatabaseManager")
@patch("src.import_statement.pipeline.SplitwiseClient")
@patch("src.import_statement.pipeline.BankConfig")
def test_process_statement_db_exists(MockBankConfig, MockClient, MockDB, mock_parse_statement):
    mock_parse_statement.return_value = pd.DataFrame([{
        "date": "2026-04-01",
        "description": "Uber",
        "amount": 5.0,
        "detail": "ref456",
        "cc_reference_id": "ref456",
        "is_credit": False
    }])
    
    mock_db = MagicMock()
    MockDB.return_value = mock_db
    
    mock_txn = MagicMock()
    mock_txn.splitwise_id = 999
    mock_db.get_transaction_by_cc_reference.return_value = mock_txn
    
    mock_client = MagicMock()
    MockClient.return_value = mock_client
    
    with patch("pandas.DataFrame.to_csv"), patch("src.import_statement.pipeline.mkdir_p"):
        df = process_statement(
            path="data/bank_statements/amex/statement.csv",
            dry_run=False,
            no_sheet=True,
            start_date="2026-01-01",
            end_date="2026-12-31"
        )
        
    assert len(df) == 1
    assert df.iloc[0]["status"] == "db_exists"
    assert df.iloc[0]["splitwise_id"] == 999
    mock_client.add_expense_from_txn.assert_not_called()

@patch("src.import_statement.pipeline.parse_statement")
@patch("src.import_statement.pipeline.DatabaseManager")
@patch("src.import_statement.pipeline.SplitwiseClient")
@patch("src.import_statement.pipeline.RefundProcessor")
def test_process_statement_live(mock_refund_proc, mock_client_cls, mock_db_cls, mock_parse, sample_df):
    mock_parse.return_value = sample_df
    mock_db = mock_db_cls.return_value
    mock_db.get_transaction_by_cc_reference.return_value = None
    mock_db.insert_transaction.return_value = 100
    
    mock_client = mock_client_cls.return_value
    mock_client.find_expense_by_cc_reference.return_value = None
    mock_client.get_current_user_id.return_value = 1
    mock_client.add_expense_from_txn.return_value = "sw_123"
    
    with patch("pandas.DataFrame.to_csv"), patch("src.import_statement.pipeline.mkdir_p"):
        res = process_statement("test.csv", dry_run=False, no_sheet=True)
    
    assert len(res) == 2
    assert res.iloc[0]["status"] == "added"
    assert res.iloc[1]["status"] == "added"
    
    assert mock_client.add_expense_from_txn.call_count == 1
    assert mock_db.insert_transaction.call_count == 2
    mock_refund_proc.return_value.process_refund.assert_called()

@patch("src.import_statement.pipeline.parse_statement")
@patch("src.import_statement.pipeline.DatabaseManager")
@patch("src.import_statement.pipeline.SplitwiseClient")
@patch("src.import_statement.pipeline.RefundProcessor")
def test_process_statement_remote_error(mock_refund_proc, mock_client_cls, mock_db_cls, mock_parse, sample_df):
    mock_parse.return_value = sample_df
    mock_db = mock_db_cls.return_value
    mock_db.get_transaction_by_fingerprint.return_value = None
    mock_db.get_transaction_by_cc_reference.return_value = None
    mock_client = mock_client_cls.return_value
    mock_client.find_expense_by_cc_reference.side_effect = RuntimeError("Remote fail")
    
    with patch("pandas.DataFrame.to_csv"), patch("src.import_statement.pipeline.mkdir_p"):
        res = process_statement("test.csv", dry_run=True, no_sheet=True)
    
    assert len(res) == 2
    assert res.iloc[0]["status"] == "would_add"

@patch("src.import_statement.pipeline.parse_statement")
@patch("src.import_statement.pipeline.DatabaseManager")
@patch("src.import_statement.pipeline.SplitwiseClient")
@patch("src.import_statement.pipeline.write_to_sheets")
def test_process_statement_with_sheets(mock_write, mock_client_cls, mock_db_cls, mock_parse, sample_df):
    mock_parse.return_value = sample_df
    with patch("pandas.DataFrame.to_csv"), patch("src.import_statement.pipeline.mkdir_p"):
        process_statement("test.csv", dry_run=True, sheet_key="test_key", no_sheet=False)
    mock_write.assert_called_once()

@patch("src.import_statement.pipeline.process_statement")
def test_main_cli(mock_process):
    with patch("sys.argv", ["script", "--statement", "test.csv", "--dry-run", "--no-sheet"]):
        assert main() == 0
        mock_process.assert_called_once()
