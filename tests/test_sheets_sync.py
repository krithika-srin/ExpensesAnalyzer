import pytest
import pandas as pd
from unittest.mock import patch, MagicMock, PropertyMock
from src.common.sheets_sync import (
    read_from_sheets,
    write_to_sheets,
    _colnum_to_a1,
    _ensure_size_for_append,
    _apply_column_formats,
)
from src.constants.export_columns import ExportColumns

def test_colnum_to_a1():
    assert _colnum_to_a1(1) == "A"
    assert _colnum_to_a1(26) == "Z"
    assert _colnum_to_a1(27) == "AA"
    assert _colnum_to_a1(28) == "AB"

def test_read_from_sheets_empty_args():
    assert read_from_sheets("", "ws") is None
    assert read_from_sheets("key", "") is None

@patch("src.common.sheets_sync.pygsheets.authorize")
def test_read_from_sheets_success(mock_auth):
    mock_gc = MagicMock()
    mock_auth.return_value = mock_gc
    mock_sheet = MagicMock()
    mock_gc.open_by_key.return_value = mock_sheet
    mock_ws = MagicMock()
    mock_sheet.worksheet_by_title.return_value = mock_ws
    mock_ws.get_as_df.return_value = pd.DataFrame({"a": [1]})
    
    result = read_from_sheets("key123", "Sheet1")
    assert result is not None
    assert len(result) == 1

@patch("src.common.sheets_sync.pygsheets.authorize")
def test_read_from_sheets_not_found(mock_auth):
    import pygsheets
    mock_gc = MagicMock()
    mock_auth.return_value = mock_gc
    mock_sheet = MagicMock()
    mock_gc.open_by_key.return_value = mock_sheet
    mock_sheet.worksheet_by_title.side_effect = pygsheets.WorksheetNotFound("nope")
    
    with pytest.raises(pygsheets.WorksheetNotFound):
        read_from_sheets("key123", "Missing")

def test_ensure_size_for_append_add_rows():
    ws = MagicMock()
    ws.rows = 10
    ws.cols = 5
    _ensure_size_for_append(ws, 15, 5, 5)
    ws.add_rows.assert_called_once_with(9)

def test_ensure_size_for_append_resize_fallback():
    ws = MagicMock(spec=["rows", "cols", "resize"])
    ws.rows = 10
    ws.cols = 3
    _ensure_size_for_append(ws, 12, 2, 5)
    ws.resize.assert_called()

def test_ensure_size_for_append_no_action():
    ws = MagicMock()
    ws.rows = 100
    ws.cols = 20
    _ensure_size_for_append(ws, 5, 3, 10)
    ws.add_rows.assert_not_called()
    ws.add_cols.assert_not_called()

def test_apply_column_formats_no_apply_format():
    ws = MagicMock(spec=[])  # no apply_format
    _apply_column_formats(ws, pd.DataFrame({"a": [1]}))
    # Should not raise

def test_apply_column_formats_regular():
    ws = MagicMock()
    ws.title = "Expenses 2026"
    df = pd.DataFrame({ExportColumns.DATE: ["2026-01-01"], ExportColumns.AMOUNT: [10.0]})
    _apply_column_formats(ws, df)
    ws.apply_format.assert_called()

@patch("src.common.sheets_sync.pygsheets.authorize")
def test_write_to_sheets_overwrite(mock_auth):
    mock_gc = MagicMock()
    mock_auth.return_value = mock_gc
    mock_sheet = MagicMock()
    mock_gc.open_by_key.return_value = mock_sheet
    mock_ws = MagicMock()
    mock_ws.title = "TestSheet"
    mock_sheet.worksheets.return_value = [mock_ws]
    mock_sheet.url = "https://example.com"
    
    df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
    url = write_to_sheets(df, "TestSheet", spreadsheet_key="key123", append=False, skip_formatting=True)
    assert url == "https://example.com"
    mock_ws.clear.assert_called_once()
    mock_ws.set_dataframe.assert_called_once()

@patch("src.common.sheets_sync.pygsheets.authorize")
def test_write_to_sheets_append(mock_auth):
    mock_gc = MagicMock()
    mock_auth.return_value = mock_gc
    mock_sheet = MagicMock()
    mock_gc.open_by_key.return_value = mock_sheet
    mock_ws = MagicMock()
    mock_ws.title = "TestSheet"
    mock_ws.rows = 100
    mock_ws.cols = 10
    mock_ws.get_all_values.return_value = [["h1", "h2"], ["v1", "v2"]]
    mock_sheet.worksheets.return_value = [mock_ws]
    mock_sheet.url = "https://example.com"
    
    df = pd.DataFrame({"A": [5], "B": [6]})
    write_to_sheets(df, "TestSheet", spreadsheet_key="key123", append=True, skip_formatting=True)
    mock_ws.set_dataframe.assert_called_once()

@patch("src.common.sheets_sync.pygsheets.authorize")
def test_write_to_sheets_creates_worksheet(mock_auth):
    mock_gc = MagicMock()
    mock_auth.return_value = mock_gc
    mock_sheet = MagicMock()
    mock_gc.open_by_key.return_value = mock_sheet
    mock_sheet.worksheets.return_value = []  # no worksheets
    mock_new_ws = MagicMock()
    mock_new_ws.title = "NewSheet"
    mock_sheet.add_worksheet.return_value = mock_new_ws
    mock_sheet.url = "https://example.com"
    
    df = pd.DataFrame({"A": [1]})
    write_to_sheets(df, "NewSheet", spreadsheet_key="key123", skip_formatting=True)
    mock_sheet.add_worksheet.assert_called_once_with("NewSheet")

def test_write_to_sheets_no_key():
    with pytest.raises(ValueError, match="spreadsheet_key is required"):
        write_to_sheets(pd.DataFrame(), "ws")

@patch("src.common.sheets_sync.pygsheets.authorize")
def test_write_to_sheets_append_empty_sheet(mock_auth):
    mock_gc = MagicMock()
    mock_auth.return_value = mock_gc
    mock_sheet = MagicMock()
    mock_gc.open_by_key.return_value = mock_sheet
    mock_ws = MagicMock()
    mock_ws.title = "EmptySheet"
    mock_ws.rows = 100
    mock_ws.cols = 10
    mock_ws.get_all_values.return_value = []  # empty
    mock_sheet.worksheets.return_value = [mock_ws]
    mock_sheet.url = "https://example.com"
    
    df = pd.DataFrame({"A": [1]})
    write_to_sheets(df, "EmptySheet", spreadsheet_key="key123", append=True, skip_formatting=True)
    # Should call set_dataframe with copy_head=True since sheet is empty
    mock_ws.set_dataframe.assert_called_once()
