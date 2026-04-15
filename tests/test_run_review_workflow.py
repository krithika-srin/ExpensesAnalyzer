import pytest
from unittest.mock import patch, MagicMock
from src.merchant_review.run_review_workflow import run_workflow

@patch("src.merchant_review.run_review_workflow.subprocess.run")
def test_run_workflow_all_steps(mock_run):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_run.return_value = mock_result
    
    success = run_workflow("dummy.csv", skip_generation=False, skip_review=False, skip_apply=False)
    
    assert success is True
    assert mock_run.call_count == 3
    # Check that generation, review, and apply were all called
    calls = mock_run.call_args_list
    assert "generate_review_file.py" in calls[0][0][0][1]
    assert "review_merchants.py" in calls[1][0][0][1]
    assert "apply_review_feedback.py" in calls[2][0][0][1]

@patch("src.merchant_review.run_review_workflow.subprocess.run")
def test_run_workflow_fails(mock_run):
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_run.return_value = mock_result
    
    success = run_workflow("dummy.csv", skip_generation=False)
    
    assert success is False
    assert mock_run.call_count == 1 # Stoppes at generation
