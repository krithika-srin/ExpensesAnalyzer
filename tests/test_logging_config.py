import pytest
from unittest.mock import patch, MagicMock
from src.constants.logging_config import setup_file_logging, LOG

@patch("src.constants.logging_config.RotatingFileHandler")
def test_setup_file_logging(mock_handler):
    mock_handler_instance = MagicMock()
    mock_handler.return_value = mock_handler_instance
    
    setup_file_logging("test.log", max_bytes=1000, backup_count=3)
    
    mock_handler.assert_called_once_with("test.log", maxBytes=1000, backupCount=3)
    mock_handler_instance.setFormatter.assert_called_once()
    assert mock_handler_instance in LOG.handlers
    
    # cleanup handler for other tests to not be affected
    LOG.removeHandler(mock_handler_instance)
