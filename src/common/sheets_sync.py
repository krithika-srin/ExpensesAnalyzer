"""Google Sheets synchronization functionality."""

# Standard library
from typing import Optional

# Third-party
import pandas as pd
import pygsheets

# Local application
from src.constants.export_columns import ExportColumns
from src.constants.gsheets import (
    CURRENCY_COLUMNS,
    CURRENCY_FORMAT_PATTERN,
    DATE_FORMAT_PATTERN,
    DEFAULT_COLUMN_WIDTH,
    SHEETS_AUTHENTICATION_FILE,
    WORKSHEET_MONTHLY_SUMMARY,
)
from src.common.utils import LOG


def read_from_sheets(
    spreadsheet_key: str,
    worksheet_name: str,
    numerize: bool = False,
) -> Optional[pd.DataFrame]:
    """Read a DataFrame from a Google Sheets worksheet.

    Args:
        spreadsheet_key: Google Sheet key/ID
        worksheet_name: Name of the worksheet to read from
        numerize: Whether to convert numeric strings to numbers

    Returns:
        DataFrame with the data, or None if the worksheet doesn't exist
    """
    if not spreadsheet_key or not worksheet_name:
        return None

    gc = pygsheets.authorize(service_account_file=SHEETS_AUTHENTICATION_FILE)
    sheet = gc.open_by_key(spreadsheet_key)
    worksheet = sheet.worksheet_by_title(worksheet_name)
    df = worksheet.get_as_df(numerize=numerize, empty_value=None)
    return df if not df.empty else None


def _colnum_to_a1(column_number: int) -> str:
    """Convert a 1-based column index to its Google Sheets A1 notation.

    Args:
        column_number: One-based column index (e.g. 1 => A, 27 => AA).

    Returns:
        The corresponding A1-style column label.
    """
    column_label = ""
    value = column_number
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        column_label = chr(65 + remainder) + column_label
    return column_label


def _ensure_size_for_append(worksheet, start_row: int, num_rows: int, num_cols: int):
    # Ensure worksheet has enough rows and cols for an append. Use attribute checks instead of catching broad exceptions.
    needed_rows = start_row + num_rows - 1
    curr_rows = getattr(worksheet, "rows", None)
    if curr_rows is not None and needed_rows > curr_rows:
        add = needed_rows - curr_rows
        LOG.info("Adding %d rows to worksheet to accommodate append", add)
        if hasattr(worksheet, "add_rows"):
            worksheet.add_rows(add)
        else:
            # If add_rows not available, try resize API if present
            if hasattr(worksheet, "resize"):
                worksheet.resize(rows=needed_rows)
            else:
                raise RuntimeError(
                    "Worksheet does not support add_rows or resize; cannot expand rows"
                )

    needed_cols = max(num_cols, 1)
    curr_cols = getattr(worksheet, "cols", None)
    if curr_cols is not None and needed_cols > curr_cols:
        addc = needed_cols - curr_cols
        LOG.info("Adding %d cols to worksheet to accommodate columns", addc)
        if hasattr(worksheet, "add_cols"):
            worksheet.add_cols(addc)
        else:
            if hasattr(worksheet, "resize"):
                worksheet.resize(cols=needed_cols)
            else:
                raise RuntimeError(
                    "Worksheet does not support add_cols or resize; cannot expand cols"
                )


def _apply_column_formats(worksheet, write_data: pd.DataFrame):
    if not hasattr(worksheet, "apply_format"):
        LOG.info(
            "Worksheet object does not support .apply_format(); skipping column formatting"
        )
        return

    if getattr(worksheet, "title", None) == WORKSHEET_MONTHLY_SUMMARY:
        currency_format = {
            "numberFormat": {"type": "CURRENCY", "pattern": CURRENCY_FORMAT_PATTERN}
        }
        percentage_format = {"numberFormat": {"type": "PERCENT", "pattern": "0.00%"}}
        for col in ["B", "C", "E", "F", "G"]:
            worksheet.apply_format(f"{col}2:{col}", currency_format)
        worksheet.apply_format("H2:H", percentage_format)
        return

    # Format entire columns so formatting persists even if rows are added later.
    # Columns B, H, I, J are currency fields (amount, my_paid, my_owed, my_net).
    currency_format = {
        "numberFormat": {"type": "CURRENCY", "pattern": CURRENCY_FORMAT_PATTERN}
    }
    for col_letter in CURRENCY_COLUMNS:
        cell_range = f"{col_letter}2:{col_letter}"
        worksheet.apply_format(cell_range, currency_format)

    # date -> date (column A)
    cols = list(write_data.columns)
    if ExportColumns.DATE in cols:
        idx = cols.index(ExportColumns.DATE) + 1
        col_a1 = _colnum_to_a1(idx)
        cell_range = f"{col_a1}2:{col_a1}"
        worksheet.apply_format(
            cell_range,
            {"numberFormat": {"type": "DATE", "pattern": DATE_FORMAT_PATTERN}},
        )


def write_to_sheets(
    write_data: pd.DataFrame,
    worksheet_name: str,
    spreadsheet_key: str = None,
    append: bool = False,
    skip_formatting: bool = False,
):
    """Write a DataFrame to a Google Sheets worksheet.

    If append=True, the data will be appended after existing rows (header not duplicated).
    Otherwise the worksheet is cleared (or created) and rewritten.
    After writing, attempt to format key columns (date, amount) and freeze the header row.

    Args:
        write_data: DataFrame to write
        worksheet_name: Name of the worksheet
        spreadsheet_key: Google Sheets spreadsheet key
        append: If True, append to existing data; if False, overwrite
        skip_formatting: If True, skip column formatting (useful for non-transaction sheets)
    """
    if not spreadsheet_key:
        raise ValueError("spreadsheet_key is required")

    # Inline small steps directly here instead of tiny helpers so flow is explicit
    gc = pygsheets.authorize(service_account_file=SHEETS_AUTHENTICATION_FILE)

    # Open spreadsheet by key
    sheet = gc.open_by_key(spreadsheet_key)

    # Ensure worksheet exists: scan existing worksheets, else create
    worksheet = None
    for ws in sheet.worksheets():
        if getattr(ws, "title", None) == worksheet_name:
            worksheet = ws
            break
    if worksheet is None:
        worksheet = sheet.add_worksheet(worksheet_name)

    num_cols = len(write_data.columns)

    if append:
        # get values with the include_tailing_empty fallback
        try:
            values = worksheet.get_all_values(include_tailing_empty=False)
        except TypeError:
            values = worksheet.get_all_values()
        used_rows = len(values) if values else 0
        if used_rows == 0:
            LOG.info(
                "Appending to empty sheet; writing header and %d rows", len(write_data)
            )
            worksheet.set_dataframe(
                write_data, (1, 1), copy_index=False, copy_head=True
            )
        else:
            start_row = used_rows + 1
            LOG.info(
                "Appending %d rows starting at row %d (existing rows=%d)",
                len(write_data),
                start_row,
                used_rows,
            )
            _ensure_size_for_append(worksheet, start_row, len(write_data), num_cols)
            worksheet.set_dataframe(
                write_data, (start_row, 1), copy_index=False, copy_head=False
            )
    else:
        # Clear and resize to remove trailing rows from previous exports.
        # First unfreeze rows to avoid "cannot delete all non-frozen rows" error
        worksheet.frozen_rows = 0
        worksheet.clear()
        rows_needed = max(1, len(write_data) + 1)
        worksheet.resize(rows=rows_needed, cols=num_cols)
        LOG.info("Resized worksheet to %d rows x %d cols", rows_needed, num_cols)
        LOG.info("Writing %d rows to sheet (overwrite)", len(write_data))
        worksheet.set_dataframe(write_data, (1, 1), copy_index=False, copy_head=True)

    # Post-write formatting: freeze header, autosize and format columns
    # Only freeze if there are data rows (can't freeze when no data rows exist)
    if len(write_data) > 0:
        worksheet.frozen_rows = 1

    # Autosize columns if API available (best-effort)
    for i in range(1, num_cols + 1):
        if hasattr(worksheet, "adjust_column_width"):
            worksheet.adjust_column_width(i, DEFAULT_COLUMN_WIDTH)

    if not skip_formatting:
        _apply_column_formats(worksheet, write_data)

    LOG.info("Updated Google sheet successfully: %s", sheet.url)
    return sheet.url
