#!/usr/bin/env python3
"""
Show sample merchants from the review file to preview what needs reviewing.
"""

import argparse

import pandas as pd
from pathlib import Path

from src.common.utils import PROJECT_ROOT

REVIEW_FILE = (
    Path(PROJECT_ROOT) / "data" / "processed" / "merchant_names_for_review.csv"
)


def show_samples(n=10):
    """Show sample merchants from review file."""
    if not REVIEW_FILE.exists():
        print(f"ERROR: Review file not found: {REVIEW_FILE}")
        print("Run the pipeline first to generate review data:")
        print("  python src/pipeline.py --statement data/bank_statements/your_statement.csv")
        return

    df = pd.read_csv(REVIEW_FILE)

    # Get unique merchants
    df_unique = df.drop_duplicates(subset=["expected_merchant"])

    total = len(df)
    unique = len(df_unique)

    print(f"\n{'='*80}")
    print(f"MERCHANT REVIEW FILE PREVIEW")
    print(f"{'='*80}")
    print(f"\nTotal transactions: {total}")
    print(f"Unique merchants: {unique}")
    print(f"\n{'─'*80}")
    print(f"Sample of {min(n, unique)} merchants to review:")
    print(f"{'─'*80}\n")

    for idx, row in df_unique.head(n).iterrows():
        print(f"#{idx+1}: {row['expected_merchant']}")
        print(f"   Amount: ${row['amount']:.2f} | Date: {row['date']}")
        print(f"   Category: {row['category_name']} / {row['subcategory_name']}")

        # Show truncated raw description
        raw_desc = row["description_raw"][:100]
        if len(row["description_raw"]) > 100:
            raw_desc += "..."
        print(f"   Raw: {raw_desc}")
        print()

    print(f"{'─'*80}")
    print(f"To start reviewing, run:")
    print(f"  ./review.sh start --batch 20")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preview merchants in review file")
    parser.add_argument(
        "-n",
        "--number",
        type=int,
        default=10,
        help="Number of samples to show (default: 10)",
    )
    args = parser.parse_args()

    show_samples(args.number)
