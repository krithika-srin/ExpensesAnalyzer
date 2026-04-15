"""Bank statement format configuration and detection."""

import json
from pathlib import Path
from typing import Optional, Dict, Any

from src.common.utils import LOG


class BankConfig:
    """Load and manage bank statement configurations."""

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize bank configuration from JSON file.

        Args:
            config_path: Path to bank_config.json. If None, uses default location.
        """
        if config_path is None:
            config_path = (
                Path(__file__).parent.parent.parent / "config" / "bank_config.json"
            )

        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from JSON file."""
        try:
            with open(self.config_path, "r") as f:
                return json.load(f)
        except Exception as e:
            LOG.error("Failed to load bank config from %s: %s", self.config_path, e)
            raise

    def get_bank_config(self, bank_name: str) -> Dict[str, Any]:
        """Get configuration for a specific bank.

        Args:
            bank_name: Bank key (e.g., 'amex', 'bofa')

        Returns:
            Bank configuration dictionary
        """
        if bank_name not in self.config["banks"]:
            raise ValueError(f"Unknown bank: {bank_name}")
        return self.config["banks"][bank_name]

    def detect_bank_from_path(self, file_path: str) -> str:
        """Detect bank from file path directory structure.

        Uses path_patterns from bank configurations to determine bank type.
        Expected directory structure: data/bank_statements/{path_pattern}/filename.csv

        Args:
            file_path: Path to statement file

        Returns:
            Bank key (e.g., 'amex', 'bofa')

        Raises:
            ValueError: If bank cannot be determined from path
        """
        path_obj = Path(file_path)
        parent_dir = path_obj.parent.name.lower()

        # Check each bank's path_patterns
        for bank_name, bank_config in self.config["banks"].items():
            path_patterns = bank_config.get("path_patterns", [])
            if parent_dir in [pattern.lower() for pattern in path_patterns]:
                LOG.info("Detected bank from path: %s (directory: %s)", bank_name, parent_dir)
                return bank_name

        # Build list of expected directories for error message
        expected_dirs = []
        for bank_name, bank_config in self.config["banks"].items():
            patterns = bank_config.get("path_patterns", [])
            expected_dirs.extend(f"data/bank_statements/{pattern}/" for pattern in patterns)

        raise ValueError(
            f"Cannot determine bank from file path: {file_path}. "
            f"Expected directories: {', '.join(expected_dirs)}"
        )

    def validate_csv_headers(self, csv_columns: list[str], bank_name: str) -> None:
        """Validate that CSV columns match the bank's required columns.

        Args:
            csv_columns: List of column names from the CSV file
            bank_name: Bank key (e.g., 'amex', 'bofa')

        Raises:
            ValueError: If required columns are missing
        """
        if "detection_rules" not in self.config or bank_name not in self.config["detection_rules"]:
            LOG.warning("No detection rules found for bank: %s", bank_name)
            return

        rules = self.config["detection_rules"][bank_name]
        required_columns = rules.get("required_columns", [])

        # Normalize column names for comparison (case-insensitive)
        csv_columns_lower = [col.lower() for col in csv_columns]
        required_lower = [col.lower() for col in required_columns]

        missing_columns = []
        for req_col in required_lower:
            if req_col not in csv_columns_lower:
                # Find the original case version for error message
                original_req = next((col for col in required_columns if col.lower() == req_col), req_col)
                missing_columns.append(original_req)

        if missing_columns:
            raise ValueError(
                f"CSV file for bank '{bank_name}' is missing required columns: {missing_columns}. "
                f"Found columns: {csv_columns}"
            )

        LOG.info("CSV header validation passed for bank: %s", bank_name)

    def get_category_mapping(self, bank_name: str) -> Dict[str, str]:
        """Get category mapping for a bank.

        Args:
            bank_name: Bank key (e.g., 'amex', 'bofa')

        Returns:
            Merchant-to-category mapping dictionary
        """
        bank_cfg = self.get_bank_config(bank_name)
        mapping_file = bank_cfg.get("category_mapping_file")

        if not mapping_file:
            return {}

        mapping_path = Path(__file__).parent.parent.parent / "config" / mapping_file
        try:
            with open(mapping_path, "r") as f:
                return json.load(f)
        except Exception as e:
            LOG.warning("Failed to load category mapping for %s: %s", bank_name, e)
            return {}
