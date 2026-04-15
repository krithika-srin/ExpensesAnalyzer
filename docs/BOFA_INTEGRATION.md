# BoFA Integration - Folder-Based Bank Detection

## Quick Summary

Bank type is now determined by **folder structure**, not auto-detection. Much cleaner and more predictable!

```
data/bank_statements/
├── amex/amex2026.csv     → Auto-detected as Amex
└── bofa/bofa_card1_2026.csv → Auto-detected as BoFA
```

## Usage

### BoFA Import (from bofa/ folder)
```bash
python src/import_statement/pipeline.py --statement data/bank_statements/bofa/bofa_card1_2026.csv
```

### Amex Import (from amex/ folder)
```bash
python src/import_statement/pipeline.py --statement data/bank_statements/amex/amex2026.csv
```

### With Date Range
```bash
python src/import_statement/pipeline.py \
  --statement data/bank_statements/bofa/bofa_card1_2026.csv \
  --start-date 2026-02-01 \
  --end-date 2026-02-28
```

**No `--bank` argument needed!** Bank is determined from folder path.

## Folder Structure

### Create folders if they don't exist:
```bash
mkdir -p data/raw/amex
mkdir -p data/bank_statements/bofa
```

### File naming (examples):
```
data/bank_statements/amex/amex2025.csv
data/bank_statements/amex/amex2026.csv
data/bank_statements/bofa/bofa_card1_2026.csv
data/bank_statements/bofa/bofa_card2_2026.csv
```

## How It Works

1. **Statement in `data/bank_statements/amex/`** → Parsed as Amex format (uses "Description", "Category" fields)
2. **Statement in `data/bank_statements/bofa/`** → Parsed as BoFA format (uses "Payee", "Reference Number" fields)
3. **Each bank uses its own category mapping** (amex_category_mapping.json, bofa_category_mapping.json)
4. **No need for auto-detection** - folder path determines everything

## Key Benefits

✅ **Predictable** - No guessing or auto-detection failures
✅ **Isolated** - Changes to one bank's logic won't affect others
✅ **Scalable** - Add new banks by just creating a folder
✅ **Organized** - Clear folder structure for multiple cards per bank
✅ **Streamlined** - No command-line bank parameter needed

## Multiple Cards per Bank

For 2 BoFA cards:
```bash
# Card 1
python src/import_statement/pipeline.py --statement data/raw/bofa/bofa_card1_2026.csv

# Card 2  
python src/import_statement/pipeline.py --statement data/raw/bofa/bofa_card2_2026.csv
```

Both automatically detected as BoFA from folder path!

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Cannot determine bank from file path" | Move file to correct folder: `data/raw/amex/` or `data/raw/bofa/` |
| Wrong categories | Update mapping in `config/bofa_category_mapping.json` or `config/amex_category_mapping.json` |
| File not found | Ensure file is in the correct bank folder |

## Testing

```bash
# Test BoFA parsing
python src/import_statement/pipeline.py --statement data/raw/bofa/bofa_card1_2026.csv --dry-run

# Test Amex parsing
python src/import_statement/pipeline.py --statement data/raw/amex/amex2025.csv --dry-run
```

## Files Modified

- ✅ `src/import_statement/bank_config.py` - Uses folder path for bank detection
- ✅ `src/import_statement/parse_statement.py` - Determines bank from path
- ✅ `src/import_statement/pipeline.py` - Removed `--bank` argument
- ✅ `src/common/utils.py` - Bank-specific categorization

## Complete Documentation

See [BoFA Integration Guide](docs/bofa_integration_guide.md) for full details.

