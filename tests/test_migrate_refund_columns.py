import pytest
from unittest.mock import patch, MagicMock
from src.database.migrate_refund_columns import get_existing_columns, migrate_database, main

def test_get_existing_columns():
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [(0, "id"), (1, "date")]
    
    cols = get_existing_columns(mock_cursor)
    assert cols == {"id", "date"}
    mock_cursor.execute.assert_called_once_with("PRAGMA table_info(transactions)")

@patch("src.database.migrate_refund_columns.sqlite3.connect")
def test_migrate_database_adds_columns(mock_connect):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    
    # First call to get_existing_columns returns empty set, second call returns full set
    mock_cursor.fetchall.side_effect = [
        [], # initial 'id', 'date' missing, meaning nothing is present
        [(0, "cc_reference_id")] # verification step
    ]
    
    migrate_database("dummy.db", dry_run=False)
    
    assert mock_cursor.execute.call_count > 5 # PRAGMA + multiple ALTER TABLE + CREATE INDEX
    mock_conn.commit.assert_called_once()

@patch("src.database.migrate_refund_columns.sqlite3.connect")
def test_migrate_database_already_exists(mock_connect):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    
    # Mock existing columns to include all the new ones
    mock_cursor.fetchall.return_value = [
        (0, "cc_reference_id"),
        (1, "refund_for_txn_id"),
        (2, "refund_for_splitwise_id"),
        (3, "refund_created_at"),
        (4, "reconciliation_status"),
        (5, "refund_match_method"),
        (6, "is_partial_refund"),
        (7, "refund_percentage")
    ]
    
    migrate_database("dummy.db", dry_run=False)
    
    # It should only call PRAGMA once and nothing else
    mock_cursor.execute.assert_called_once_with("PRAGMA table_info(transactions)")

@patch("src.database.migrate_refund_columns.Path.exists")
@patch("src.database.migrate_refund_columns.migrate_database")
def test_main(mock_migrate, mock_exists):
    mock_exists.return_value = True
    
    with patch("sys.argv", ["script", "--db-path", "test.db", "--dry-run"]):
        assert main() == 0
        mock_migrate.assert_called_once()
