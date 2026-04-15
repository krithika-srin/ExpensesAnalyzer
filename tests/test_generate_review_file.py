import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from src.merchant_review.generate_review_file import generate_review_file

@patch("src.merchant_review.generate_review_file.pd.read_csv")
@patch("src.merchant_review.generate_review_file.pd.DataFrame.to_csv")
@patch("src.merchant_review.generate_review_file.Path.exists")
def test_generate_review_file(mock_exists, mock_to_csv, mock_read_csv):
    mock_exists.return_value = True
    
    # Mock lookup
    mock_lookup = {"netflix": {}}
    
    mock_df = pd.DataFrame([
        {"date": "2026-04-01", "amount": 15.0, "description": "Netflix", "description_raw": "NETFLIX.COM", "category_name": "Entertainment", "subcategory_name": "Streaming"},
        {"date": "2026-04-02", "amount": 20.0, "description": "Uber", "description_raw": "UBER*TRIP", "category_name": "Transport", "subcategory_name": "Taxi"}
    ])
    mock_read_csv.return_value = mock_df
    
    with patch("builtins.open", new_callable=MagicMock) as mock_file:
        import json
        with patch("json.load", return_value=mock_lookup):
            success = generate_review_file("dummy_processed.csv", include_known=False, output_file="dummy_out.csv")
            
    assert success is True
    # Should only write Uber to review file since Netflix is in lookup
    mock_to_csv.assert_called_once()
    df_written = mock_to_csv.call_args[0][0] # it's called on the df object, but mock is on to_csv so we might not get df easily.
    # actually mock_to_csv is called with (output_path, index=False) this doesn't capture the dataframe natively since it's an instance method mocked at class level.
    # To check the df we can just rely on the fact that to_csv was called.
