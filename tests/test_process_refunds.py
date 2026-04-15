import pytest
from unittest.mock import patch, MagicMock
from src.import_statement.process_refunds import RefundProcessor, main
from src.database.models import Transaction

def make_refund_txn(**kwargs):
    defaults = {
        "id": 1,
        "date": "2026-04-01",
        "amount": -25.0,
        "merchant": "Amazon",
        "description": "Refund Amazon",
        "is_refund": True,
        "cc_reference_id": "REF123",
        "source": "amex",
        "imported_at": "2026-04-01T00:00:00Z",
    }
    defaults.update(kwargs)
    return Transaction(**defaults)

def test_process_refund_dry_run():
    db = MagicMock()
    processor = RefundProcessor(db=db, client=None)
    txn = make_refund_txn()
    result = processor.process_refund(txn, dry_run=True)
    assert result["status"] == "would_create"
    db.update_transaction.assert_not_called()

def test_process_refund_creates_in_splitwise():
    db = MagicMock()
    client = MagicMock()
    client.get_current_user_id.return_value = 101
    client.add_expense_from_txn.return_value = 999
    
    processor = RefundProcessor(db=db, client=client)
    txn = make_refund_txn()
    result = processor.process_refund(txn, dry_run=False)
    
    assert result["status"] == "created"
    assert result["splitwise_id"] == 999
    client.add_expense_from_txn.assert_called_once()
    db.update_transaction.assert_called_once()

def test_process_refund_error():
    db = MagicMock()
    client = MagicMock()
    client.get_current_user_id.return_value = 101
    client.add_expense_from_txn.side_effect = Exception("API Error")
    
    processor = RefundProcessor(db=db, client=client)
    txn = make_refund_txn()
    result = processor.process_refund(txn, dry_run=False)
    
    assert result["status"] == "error"
    assert "API Error" in result["error"]

def test_create_refund_no_client():
    db = MagicMock()
    processor = RefundProcessor(db=db, client=None)
    txn = make_refund_txn()
    with pytest.raises(ValueError, match="SplitwiseClient required"):
        processor._create_refund_in_splitwise(txn)

def test_create_refund_no_cc_reference():
    db = MagicMock()
    client = MagicMock()
    client.get_current_user_id.return_value = 101
    client.add_expense_from_txn.return_value = 888
    
    processor = RefundProcessor(db=db, client=client)
    txn = make_refund_txn(cc_reference_id=None, description=None)
    sid = processor._create_refund_in_splitwise(txn)
    assert sid == 888
    # Should have generated a UUID-based ref
    call_kwargs = client.add_expense_from_txn.call_args
    assert "CREDIT_" in call_kwargs[1]["cc_reference_id"]

def test_process_all_pending_refunds():
    db = MagicMock()
    client = MagicMock()
    client.get_current_user_id.return_value = 101
    client.add_expense_from_txn.return_value = 111
    
    db.get_pending_refunds.return_value = [
        make_refund_txn(id=1),
        make_refund_txn(id=2),
    ]
    
    processor = RefundProcessor(db=db, client=client)
    summary = processor.process_all_pending_refunds(dry_run=False)
    
    assert summary["total"] == 2
    assert summary["created"] == 2
    assert summary["errors"] == 0

def test_process_all_pending_refunds_dry_run():
    db = MagicMock()
    db.get_pending_refunds.return_value = [make_refund_txn()]
    
    processor = RefundProcessor(db=db, client=None)
    summary = processor.process_all_pending_refunds(dry_run=True)
    assert summary["would_create"] == 1
    assert summary["created"] == 0

@patch("src.import_statement.process_refunds.DatabaseManager")
@patch("src.import_statement.process_refunds.RefundProcessor")
def test_main_dry_run(mock_processor_cls, mock_db_cls):
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db
    mock_db.get_pending_refunds.return_value = [make_refund_txn()]
    
    mock_processor = MagicMock()
    mock_processor_cls.return_value = mock_processor
    mock_processor.process_all_pending_refunds.return_value = {
        "total": 1, "created": 0, "errors": 0, "would_create": 1, "results": []
    }
    
    with patch("sys.argv", ["script", "--dry-run"]):
        main()
    mock_processor.process_all_pending_refunds.assert_called_once_with(dry_run=True)

@patch("src.import_statement.process_refunds.DatabaseManager")
def test_main_no_pending(mock_db_cls):
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db
    mock_db.get_pending_refunds.return_value = []
    
    with patch("sys.argv", ["script", "--dry-run"]):
        main()

@patch("src.import_statement.process_refunds.DatabaseManager")
@patch("src.import_statement.process_refunds.RefundProcessor")
def test_main_verbose_with_year(mock_proc_cls, mock_db_cls):
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db
    txn = make_refund_txn(date="2026-04-01")
    mock_db.get_pending_refunds.return_value = [txn]
    
    mock_proc = MagicMock()
    mock_proc_cls.return_value = mock_proc
    mock_proc.process_all_pending_refunds.return_value = {
        "total": 1, "created": 0, "errors": 0, "would_create": 1,
        "results": [{"status": "would_create"}]
    }
    
    with patch("sys.argv", ["script", "--dry-run", "--verbose", "--year", "2026"]):
        main()

@patch("src.import_statement.process_refunds.DatabaseManager")
@patch("src.import_statement.process_refunds.RefundProcessor")
def test_main_with_errors_verbose(mock_proc_cls, mock_db_cls):
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db
    txn = make_refund_txn()
    mock_db.get_pending_refunds.return_value = [txn]
    
    mock_proc = MagicMock()
    mock_proc_cls.return_value = mock_proc
    mock_proc.process_all_pending_refunds.return_value = {
        "total": 1, "created": 0, "errors": 1, "would_create": 0,
        "results": [{"status": "error", "refund_txn_id": 1, "date": "2026-04-01",
                      "merchant": "Amazon", "amount": 25.0, "error": "fail"}]
    }
    
    with patch("sys.argv", ["script", "--verbose"]):
        with patch("src.import_statement.process_refunds.SplitwiseClient"):
            main()
