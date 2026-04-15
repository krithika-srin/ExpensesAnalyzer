import pytest
import json
import pandas as pd
from unittest.mock import patch, MagicMock
import sys
from src.merchant_review.apply_review_feedback import (
    load_feedback,
    load_merchant_lookup,
    normalize_merchant_key,
    apply_corrections,
    move_reviewed_to_done,
    generate_report,
    analyze_correction_patterns,
    main,
)

@pytest.fixture
def sample_feedback():
    return {
        "approved": [
            {
                "description_raw": "NETFLIX.COM",
                "description": "Netflix",
                "expected_merchant": "Netflix",
                "category_name": "Entertainment",
                "subcategory_name": "Other",
            }
        ],
        "corrected": [
            {
                "description_raw": "UBER   *RIDE",
                "description": "Uber",
                "expected_merchant": "Uber",
                "category_name": "Transportation",
                "subcategory_name": "Taxi",
                "corrected_merchant": "Uber",
                "corrected_category": "Transportation",
                "corrected_subcategory": "Taxi",
            }
        ],
        "skipped": []
    }

def test_normalize_merchant_key():
    assert normalize_merchant_key("  Netflix  ") == "netflix"
    assert normalize_merchant_key(None) == ""
    assert normalize_merchant_key(123) == ""

@patch("src.merchant_review.apply_review_feedback.FEEDBACK_FILE")
def test_load_feedback_missing(mock_file):
    mock_file.exists.return_value = False
    res = load_feedback()
    assert res == {"approved": [], "corrected": [], "skipped": []}

@patch("src.merchant_review.apply_review_feedback.MERCHANT_LOOKUP_FILE")
def test_load_merchant_lookup_missing(mock_file):
    mock_file.exists.return_value = False
    assert load_merchant_lookup() == {}

@patch("src.merchant_review.apply_review_feedback.load_merchant_lookup", return_value={})
@patch("src.merchant_review.apply_review_feedback.save_merchant_lookup")
def test_apply_corrections_added(mock_save, mock_load, sample_feedback):
    stats = apply_corrections(sample_feedback, dry_run=False)
    assert stats["added"] == 2
    assert stats["updated"] == 0
    mock_save.assert_called_once()

@patch("src.merchant_review.apply_review_feedback.load_merchant_lookup")
@patch("src.merchant_review.apply_review_feedback.save_merchant_lookup")
def test_apply_corrections_updated(mock_save, mock_load, sample_feedback):
    mock_load.return_value = {
        "netflix": {"category": "Entertainment", "subcategory": "Movies", "canonical_name": "Netflix"}
    }
    stats = apply_corrections(sample_feedback, dry_run=False)
    assert stats["added"] == 1
    assert stats["unchanged"] == 1
    mock_save.assert_called_once()

@patch("src.merchant_review.apply_review_feedback.REVIEW_FILE")
@patch("src.merchant_review.apply_review_feedback.DONE_REVIEW_FILE")
@patch("pandas.read_csv")
def test_move_reviewed_to_done(mock_read, mock_done_file, mock_review_file, sample_feedback):
    mock_review_file.exists.return_value = True
    mock_done_file.exists.return_value = False
    df_review = pd.DataFrame([
        {"description_raw": "NETFLIX.COM", "description": "Netflix"},
        {"description_raw": "UBER   *RIDE", "description": "Uber"},
        {"description_raw": "STAYING_LATER", "description": "Other"},
    ])
    mock_read.return_value = df_review
    with patch.object(pd.DataFrame, "to_csv") as mock_to_csv:
        move_reviewed_to_done(sample_feedback)
        assert mock_to_csv.call_count == 2

def test_generate_report(capsys):
    stats = {
        "added": 1, "updated": 1, "unchanged": 1,
        "changes": [
            {"action": "added", "merchant": "Netflix", "new_category": "Ent", "new_subcategory": "Other"},
            {"action": "updated", "merchant": "Uber", "corrected_merchant": "Uber Ride", "old_category": "T", "new_category": "T", "old_subcategory": "Bus", "new_subcategory": "Taxi"}
        ]
    }
    generate_report(stats)
    captured = capsys.readouterr()
    assert "FEEDBACK APPLICATION REPORT" in captured.out
    assert "Added:     1" in captured.out

def test_analyze_correction_patterns(capsys):
    feedback = {
        "corrected": [
            {
                "expected_merchant": "Netflix",
                "corrected_merchant": "Netflix Inc",
                "category_name": "Entertainment",
                "corrected_category": "Services"
            }
        ]
    }
    analyze_correction_patterns(feedback)
    captured = capsys.readouterr()
    assert "CORRECTION PATTERNS ANALYSIS" in captured.out
    assert "Merchant name corrections: 1" in captured.out

@patch("src.merchant_review.apply_review_feedback.load_feedback")
@patch("src.merchant_review.apply_review_feedback.apply_corrections")
@patch("src.merchant_review.apply_review_feedback.generate_report")
@patch("src.merchant_review.apply_review_feedback.move_reviewed_to_done")
def test_main_cli_live(mock_move, mock_report, mock_apply, mock_load):
    mock_load.return_value = {"approved": [{"id": 1}], "corrected": [], "skipped": []}
    mock_apply.return_value = {"added": 1, "updated": 0, "unchanged": 0, "changes": []}
    with patch("sys.argv", ["script"]):
        main()
        mock_apply.assert_called_once()
        mock_move.assert_called_once()

@patch("src.merchant_review.apply_review_feedback.load_feedback")
@patch("src.merchant_review.apply_review_feedback.apply_corrections")
def test_main_cli_dry_run(mock_apply, mock_load):
    mock_load.return_value = {"approved": [{"id": 1}], "corrected": [], "skipped": []}
    mock_apply.return_value = {"added": 1, "updated": 0, "unchanged": 0, "changes": []}
    with patch("sys.argv", ["script", "--dry-run"]):
        main()
        mock_apply.assert_called_once_with(mock_load.return_value, dry_run=True)

@patch("src.merchant_review.apply_review_feedback.load_feedback")
def test_main_cli_no_feedback(mock_load, capsys):
    mock_load.return_value = {"approved": [], "corrected": [], "skipped": []}
    with patch("sys.argv", ["script"]):
        main()
    captured = capsys.readouterr()
    assert "No feedback to apply yet" in captured.out
