import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from src.merchant_review.preview_review import show_samples

@patch("src.merchant_review.preview_review.pd.read_csv")
@patch("src.merchant_review.preview_review.Path.exists")
def test_show_samples_success(mock_exists, mock_read_csv, capsys):
    mock_exists.return_value = True
    mock_df = pd.DataFrame([
        {
            "expected_merchant": "Netflix",
            "amount": 15.0,
            "date": "2026-04-01",
            "category_name": "Entertainment",
            "subcategory_name": "Streaming",
            "description_raw": "NETFLIX.COM"
        }
    ])
    mock_read_csv.return_value = mock_df
    
    show_samples(n=1)
    
    captured = capsys.readouterr()
    assert "Netflix" in captured.out
    assert "Entertainment / Streaming" in captured.out

@patch("src.merchant_review.preview_review.Path.exists")
def test_show_samples_no_file(mock_exists, capsys):
    mock_exists.return_value = False
    
    show_samples()
    
    captured = capsys.readouterr()
    assert "ERROR: Review file not found" in captured.out
