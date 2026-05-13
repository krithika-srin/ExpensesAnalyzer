import pandas as pd
import os

def parse_statement(path):
    """Parse Chase credit card statement CSV."""
    if not os.path.exists(path):
        return None
    
    try:
        # Chase format usually has: Transaction Date, Post Date, Description, Category, Type, Amount, Memo
        df = pd.read_csv(path)
        
        # Normalize columns
        # Expected output: date, description, amount, cc_reference_id
        
        # Map Chase columns
        col_map = {
            'Transaction Date': 'date',
            'Description': 'description',
            'Amount': 'amount'
        }
        
        # Find matching columns
        existing_cols = {c: c for c in df.columns}
        final_map = {v: existing_cols[k] for k, v in col_map.items() if k in existing_cols}
        
        if not final_map:
            # Try lowercase or other variations
            col_map_lower = {k.lower(): v for k, v in col_map.items()}
            existing_cols_lower = {c.lower(): c for c in df.columns}
            final_map = {v: existing_cols_lower[k] for k, v in col_map_lower.items() if k in existing_cols_lower}

        if 'Type' in df.columns:
            final_map['type'] = 'Type'
        elif 'type' in existing_cols_lower:
            final_map['type'] = existing_cols_lower['type']

        if 'date' not in final_map:
            raise ValueError(f"Could not find Date column in {df.columns}")

        # Rename and select
        df = df.rename(columns={v: k for k, v in final_map.items()})
        
        # Convert date
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        
        # Ensure amount is numeric
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
        
        cols_to_return = ['date', 'description', 'amount']
        if 'type' in df.columns:
            cols_to_return.append('type')
        
        return df[cols_to_return]
    except Exception as e:
        print(f"Error parsing {path}: {e}")
        return None
