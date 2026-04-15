import pytest
import json
from pathlib import Path
from unittest.mock import patch, mock_open

from src.import_statement.bank_config import BankConfig

@patch("builtins.open", new_callable=mock_open, read_data='''
{
  "banks": {
    "amex": {
      "path_patterns": ["american express"],
      "category_mapping_file": "amex_map.json"
    },
    "bofa": {
      "path_patterns": ["bank of america", "bofa_card2"],
      "category_mapping_file": "bofa_map.json"
    }
  },
  "detection_rules": {
    "amex": {
      "required_columns": ["Date", "Description", "Amount"]
    },
    "bofa": {
      "required_columns": ["Posted Date", "Payee", "Amount"]
    }
  }
}
''')
def test_detect_bank_from_path_and_config(mock_file):
    # init will load the config
    config = BankConfig(config_path=Path("dummy_path.json"))
    
    assert config.detect_bank_from_path("data/bank_statements/american express/amex2026.csv") == "amex"
    assert config.detect_bank_from_path("data/bank_statements/bank of america/bofa2026.csv") == "bofa"
    assert config.detect_bank_from_path("data/bank_statements/bofa_card2/statement.csv") == "bofa"
    assert config.get_bank_config("amex")["category_mapping_file"] == "amex_map.json"

    with pytest.raises(ValueError):
        config.detect_bank_from_path("data/bank_statements/chase/chase2026.csv")
        
    with pytest.raises(ValueError):
        config.get_bank_config("chase")


@patch("builtins.open", new_callable=mock_open, read_data='''
{
  "banks": {
    "amex": {
      "path_patterns": ["american express"],
      "category_mapping_file": "amex_map.json"
    },
    "bofa": {
      "path_patterns": ["bank of america", "bofa_card2"],
      "category_mapping_file": "bofa_map.json"
    }
  },
  "detection_rules": {
    "amex": {
      "required_columns": ["Date", "Description", "Amount"]
    },
    "bofa": {
      "required_columns": ["Posted Date", "Payee", "Amount"]
    }
  }
}
''')
def test_validate_csv_headers(mock_file):
    config = BankConfig(config_path=Path("dummy_path.json"))
    
    # Valid headers for amex
    valid_amex_columns = ["Date", "Description", "Amount", "Category"]
    config.validate_csv_headers(valid_amex_columns, "amex")
    
    # Valid headers for bofa
    valid_bofa_columns = ["Posted Date", "Payee", "Amount", "Address"]
    config.validate_csv_headers(valid_bofa_columns, "bofa")
    
    # Missing required column for amex
    invalid_amex_columns = ["Date", "Amount", "Category"]  # missing Description
    with pytest.raises(ValueError, match="missing required columns.*Description"):
        config.validate_csv_headers(invalid_amex_columns, "amex")
    
    # Case insensitive matching
    case_insensitive_columns = ["date", "DESCRIPTION", "amount"]
    config.validate_csv_headers(case_insensitive_columns, "amex")
    
    # Bank without detection rules (should not raise error)
    config.validate_csv_headers(["Any", "Columns"], "unknown_bank")

