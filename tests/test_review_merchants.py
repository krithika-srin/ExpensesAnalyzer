import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
import sys
from src.merchant_review.review_merchants import (
    validate_category_subcategory,
    detect_lodging_in_description,
    interactive_review,
    load_review_data,
    main
)

@pytest.fixture
def sample_review_df():
    return pd.DataFrame([
        {
            "description_raw": "NETFLIX.COM",
            "description": "Netflix",
            "expected_merchant": "Netflix",
            "category_name": "Entertainment",
            "subcategory_name": "Movies",
            "date": "2026-04-01",
            "amount": 15.99,
            "count": 1
        },
        {
            "description_raw": "UBER* RIDE",
            "description": "Uber",
            "expected_merchant": "Uber",
            "category_name": "Transportation",
            "subcategory_name": "Taxi",
            "date": "2026-04-02",
            "amount": 25.0,
            "count": 1
        }
    ])

def test_validate_category_subcategory():
    is_valid, err = validate_category_subcategory("Food and drink", "Dining out")
    assert is_valid is True
    assert err is None
    
    is_valid, err = validate_category_subcategory("Invalid Category", "Dining out")
    assert is_valid is False
    assert "Invalid category" in err
    
    is_valid, err = validate_category_subcategory("Food and drink", "Invalid Sub")
    assert is_valid is False
    assert "not valid for category" in err

def test_detect_lodging_in_description():
    assert detect_lodging_in_description("HILTON LODGING NYC") is True
    assert detect_lodging_in_description("UBER RIDE") is False

def test_load_review_data_missing():
    with patch("src.merchant_review.review_merchants.REVIEW_FILE") as mock_file:
        mock_file.exists.return_value = False
        df = load_review_data()
        assert df.empty

@patch("src.merchant_review.review_merchants.get_user_input")
@patch("src.merchant_review.review_merchants.load_review_data")
@patch("src.merchant_review.review_merchants.load_feedback")
@patch("src.merchant_review.review_merchants.save_feedback")
def test_interactive_review_approve(mock_save, mock_feedback, mock_load, mock_input, capsys):
    mock_df = pd.DataFrame([
        {
            "description_raw": "NETFLIX",
            "description": "Netflix",
            "expected_merchant": "Netflix",
            "category_name": "Entertainment",
            "subcategory_name": "Other",
            "date": "2026-04-01",
            "amount": 10.0
        }
    ])
    mock_load.return_value = mock_df
    mock_feedback_data = {"approved": [], "corrected": [], "skipped": []}
    mock_feedback.return_value = mock_feedback_data
    
    mock_input.side_effect = ["a"]
    interactive_review(0, 1)
    
    assert len(mock_feedback_data["approved"]) == 1
    assert mock_feedback_data["approved"][0]["expected_merchant"] == "Netflix"
    mock_save.assert_called()

@patch("src.merchant_review.review_merchants.get_user_input")
@patch("src.merchant_review.review_merchants.load_review_data")
@patch("src.merchant_review.review_merchants.load_feedback")
@patch("src.merchant_review.review_merchants.save_feedback")
def test_interactive_review_skip_and_quit(mock_save, mock_feedback, mock_load, mock_input):
    mock_df = pd.DataFrame([
        {
            "description_raw": "NETFLIX", "description": "Netflix", "expected_merchant": "Netflix",
            "category_name": "Entertainment", "subcategory_name": "Other", "date": "2026-04-01", "amount": 10.0
        },
        {
            "description_raw": "UBER", "description": "Uber", "expected_merchant": "Uber",
            "category_name": "Transportation", "subcategory_name": "Taxi", "date": "2026-04-02", "amount": 20.0
        }
    ])
    mock_load.return_value = mock_df
    mock_feedback_data = {"approved": [], "corrected": [], "skipped": []}
    mock_feedback.return_value = mock_feedback_data
    
    mock_input.side_effect = ["s", "q"]
    interactive_review(0, 2)
    
    assert len(mock_feedback_data["skipped"]) == 1
    assert mock_feedback_data["skipped"][0]["expected_merchant"] == "Netflix"
    mock_save.assert_called()

@patch("src.merchant_review.review_merchants.get_user_input")
@patch("src.merchant_review.review_merchants.load_review_data")
@patch("src.merchant_review.review_merchants.save_feedback")
@patch("src.merchant_review.review_merchants.display_transaction")
def test_interactive_review_full_flow(mock_display, mock_save, mock_load, mock_input, sample_review_df):
    mock_load.return_value = sample_review_df
    # 1. Netflix - Approve (a)
    # 2. Uber - Correct (c) -> Uber Ride -> Transportation -> Taxi -> Actions: c
    # 3. Then Quit (q)
    mock_input.side_effect = ["a", "c", "Uber Ride", "Transportation", "Taxi", "q"]
    
    with patch("src.merchant_review.review_merchants.load_feedback", return_value={"approved": [], "corrected": [], "skipped": []}):
        interactive_review()
    
    mock_save.assert_called()
    saved_feedback = mock_save.call_args[0][0]
    assert len(saved_feedback["approved"]) == 1
    assert len(saved_feedback["corrected"]) == 1
    assert saved_feedback["corrected"][0]["corrected_merchant"] == "Uber Ride"

@patch("src.merchant_review.review_merchants.load_review_data")
@patch("src.merchant_review.review_merchants.load_feedback")
def test_main_stats(mock_load_fb, mock_load_data, capsys):
    mock_load_fb.return_value = {
        "approved": [{"description": "A"}],
        "corrected": [{"expected_merchant": "B", "corrected_merchant": "C", "category_name": "Food", "corrected_category": "T"}],
        "skipped": []
    }
    with patch("sys.argv", ["script", "--stats"]):
        main()
        captured = capsys.readouterr()
        assert "REVIEW STATISTICS" in captured.out
        assert "Approved: 1" in captured.out

@patch("src.merchant_review.review_merchants.load_review_data")
@patch("src.merchant_review.review_merchants.interactive_review")
def test_main_cli(mock_review, mock_load, sample_review_df):
    mock_load.return_value = sample_review_df
    with patch("sys.argv", ["script", "--start", "0"]):
        main()
        mock_review.assert_called_once()
