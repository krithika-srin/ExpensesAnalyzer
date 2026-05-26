import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from src.common.utils import clean_merchant_name, LOG, generate_fingerprint
from src.constants.export_columns import ExportColumns

class DeduplicationEngine:
    def __init__(self, existing_data: pd.DataFrame):
        """
        Initialize with existing data from the Google Sheet.
        
        Args:
            existing_data: DataFrame containing transactions from 'Expenses 2025'
        """
        self.existing_df = existing_data
        self.existing_fps = set()
        
        if self.existing_df is not None and not self.existing_df.empty:
            print(f"DeduplicationEngine initialized with {len(self.existing_df)} rows")
            print(f"Sheet Columns: {self.existing_df.columns.tolist()}")
            # Pre-calculate fingerprints for efficiency
            for _, row in self.existing_df.iterrows():
                desc = row.get(ExportColumns.DESCRIPTION, "")
                amt = row.get(ExportColumns.AMOUNT)
                dt = row.get(ExportColumns.DATE)
                try:
                    # Strip currency symbols and commas (e.g. "$12.50" → 12.50)
                    amt_clean = str(amt).replace("$", "").replace(",", "").strip()
                    amt_abs = abs(float(amt_clean)) if amt_clean not in ("", "nan") else 0.0
                except (ValueError, TypeError):
                    amt_abs = 0.0
                fp = generate_fingerprint(dt, amt_abs, clean_merchant_name(str(desc)))
                self.existing_fps.add(fp)
            print(f"Pre-computed {len(self.existing_fps)} fingerprints from sheet.")

    def find_match(self, date: str, amount: float, description: str) -> Optional[Dict[str, Any]]:
        """
        Multi-layered deduplication logic.
        
        Layers:
        1. Exact Fingerprint Match
        2. Fuzzy Match (Amount + Date Window + Name Similarity)
        """
        # Layer 1: Exact Fingerprint — always use absolute amount
        desc_clean = clean_merchant_name(description)
        amount_abs = abs(float(amount))
        fp = generate_fingerprint(date, amount_abs, desc_clean)
        
        if fp in self.existing_fps:
            return {"match_type": "EXACT", "reason": "Fingerprint match"}

        # Layer 2: Fuzzy Match
        if self.existing_df is None or self.existing_df.empty:
            return None

        try:
            # Strip $ and commas before numeric conversion (sheet stores amounts as "$12.50")
            cleaned_amounts = (
                self.existing_df[ExportColumns.AMOUNT]
                .astype(str)
                .str.replace("$", "", regex=False)
                .str.replace(",", "", regex=False)
                .str.strip()
            )
            existing_amounts = pd.to_numeric(cleaned_amounts, errors='coerce').fillna(0).abs()
            target_amount_abs = abs(float(amount))
            
            # Use np.isclose for floating point comparison
            amount_matches = self.existing_df[np.isclose(existing_amounts, target_amount_abs, rtol=1e-5)]
            
            if not amount_matches.empty:
                target_date = pd.to_datetime(date).date()
                for _, ex_row in amount_matches.iterrows():
                    ex_date_val = ex_row.get(ExportColumns.DATE)
                    if not ex_date_val:
                        continue
                    
                    ex_date = pd.to_datetime(ex_date_val).date()
                    date_diff = abs((ex_date - target_date).days)
                    
                    # Window check (±5 days)
                    if date_diff <= 5:
                        ex_desc = clean_merchant_name(ex_row.get(ExportColumns.DESCRIPTION, ""))
                        
                        # Name check (substring or similarity)
                        if desc_clean.lower() in ex_desc.lower() or ex_desc.lower() in desc_clean.lower():
                            LOG.info(f"Fuzzy Match Found: {desc_clean} vs {ex_desc} on {ex_date} (Diff: {date_diff}d)")
                            return {
                                "match_type": "FUZZY", 
                                "reason": f"Amount match + Date window ({date_diff}d) + Name similarity",
                                "matched_row": ex_row.to_dict()
                            }
                        else:
                            # Try word-overlap check
                            words_a = set(desc_clean.lower().split())
                            words_b = set(ex_desc.lower().split())
                            shared = words_a & words_b
                            # Match if any shared word is >= 5 chars (significant word, not "the", "and")
                            if any(len(w) >= 5 for w in shared):
                                LOG.info(f"Word-overlap Fuzzy Match: {desc_clean} vs {ex_desc} on {ex_date} (Diff: {date_diff}d, shared: {shared})")
                                return {
                                    "match_type": "FUZZY",
                                    "reason": f"Amount match + Date window ({date_diff}d) + Word overlap ({shared})",
                                    "matched_row": ex_row.to_dict()
                                }
                            else:
                                LOG.debug(f"Amount/Date match but name mismatch: {desc_clean} vs {ex_desc}")
            
        except Exception as e:
            LOG.error(f"Deduplication fuzzy check failed: {e}")
            
        return None
