import pytest
from unittest.mock import patch, MagicMock
import sys
from src.export.monthly_export_pipeline import (
    run_import_statement,
    run_sync_database,
    run_export_to_sheets,
    run_generate_summaries,
    main,
)

@patch("src.export.monthly_export_pipeline.import_main")
def test_run_import_statement(mock_import):
    mock_import.return_value = 0
    assert run_import_statement("test.csv", "2026-01-01", "2026-01-31") is True
    assert sys.argv[2] == "test.csv"
    
    mock_import.return_value = 1
    assert run_import_statement("test.csv", "2026-01-01", "2026-01-31") is False

@patch("src.export.monthly_export_pipeline.sync_from_splitwise")
def test_run_sync_database(mock_sync):
    mock_sync.return_value = {"updated": 1, "inserted": 2, "marked_deleted": 0}
    assert run_sync_database(2026) is True
    mock_sync.assert_called_once()

@patch("src.export.monthly_export_pipeline.export_main")
def test_run_export_to_sheets(mock_export):
    mock_export.return_value = 0
    assert run_export_to_sheets(2026) is True
    assert "--overwrite" in sys.argv
    
    assert run_export_to_sheets(2026, append_only=True) is True
    assert "--append-only" in sys.argv

@patch("src.export.monthly_export_pipeline.summaries_main")
def test_run_generate_summaries(mock_summaries):
    mock_summaries.return_value = 0
    assert run_generate_summaries(2026) is True
    mock_summaries.assert_called_once()

@patch("src.export.monthly_export_pipeline.run_sync_database")
@patch("src.export.monthly_export_pipeline.run_export_to_sheets")
@patch("src.export.monthly_export_pipeline.run_generate_summaries")
def test_main_sync_only(mock_summaries, mock_export, mock_sync):
    mock_sync.return_value = True
    mock_export.return_value = True
    mock_summaries.return_value = True
    
    with patch("sys.argv", ["script", "--year", "2026", "--sync-only"]):
        assert main() == 0
        mock_sync.assert_called_once()
        mock_export.assert_called_once()
        mock_summaries.assert_called_once()

@patch("src.export.monthly_export_pipeline.run_sync_database")
@patch("src.export.monthly_export_pipeline.run_import_statement")
@patch("src.export.monthly_export_pipeline.run_export_to_sheets")
@patch("src.export.monthly_export_pipeline.run_generate_summaries")
def test_main_full_pipeline(mock_summaries, mock_export, mock_import, mock_sync, tmp_path):
    mock_sync.return_value = True
    mock_import.return_value = True
    mock_export.return_value = True
    mock_summaries.return_value = True
    
    statement = tmp_path / "jan.csv"
    statement.write_text("date,description,amount\n2026-01-01,Test,10.0")
    
    with patch("sys.argv", ["script", "--year", "2026", "--statement", str(statement), "--start-date", "2026-01-01", "--end-date", "2026-01-31"]):
        assert main() == 0
        assert mock_sync.call_count == 2
        mock_import.assert_called_once()
