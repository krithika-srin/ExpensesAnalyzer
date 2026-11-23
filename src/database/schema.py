"""Database schema definitions."""

TRANSACTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS transactions (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Core transaction fields
    date TEXT NOT NULL,                    -- ISO date (YYYY-MM-DD)
    merchant TEXT NOT NULL,                -- Normalized merchant name
    description TEXT,                      -- Original description from source
    amount REAL NOT NULL,                  -- Signed amount (+ for spend, - for refund)
    
    -- Categorization
    category TEXT,                         -- Top-level category (e.g., "Food and drink")
    subcategory TEXT,                      -- Subcategory (e.g., "Dining out")
    category_id INTEGER,                   -- Splitwise category ID
    subcategory_id INTEGER,                -- Splitwise subcategory ID
    
    -- Source tracking
    source TEXT NOT NULL,                  -- amex, visa, chase, splitwise, manual
    source_file TEXT,                      -- Original CSV filename if applicable
    
    -- Transaction characteristics
    is_refund BOOLEAN DEFAULT 0,           -- True if this is a refund/credit
    is_shared BOOLEAN DEFAULT 0,           -- True if expense was shared on Splitwise
    split_type TEXT,                       -- Split type: 'self', 'split', 'partner'
    currency TEXT DEFAULT 'USD',           -- Currency code
    
    -- Splitwise integration
    splitwise_id INTEGER UNIQUE,           -- Splitwise expense ID (null if not in Splitwise)
    splitwise_deleted_at TEXT,             -- Timestamp if deleted in Splitwise
    
    -- Sync tracking
    written_to_sheet BOOLEAN DEFAULT 0,    -- True if written to Google Sheets
    sheet_year INTEGER,                    -- Which year tab it was written to
    sheet_row_id INTEGER,                  -- Row number in sheet (if needed for updates)
    
    -- Metadata
    imported_at TEXT NOT NULL,             -- When transaction was first imported to DB
    updated_at TEXT,                       -- Last update timestamp
    notes TEXT,                            -- Free-form notes
    
    -- Deduplication fields
    raw_description TEXT,                  -- Original unmodified description
    statement_date TEXT,                   -- Date as it appeared on statement
    raw_amount REAL,                       -- Original amount before sign normalization
    cc_reference_id TEXT,                  -- Credit card reference/transaction ID for linking
    
    -- Refund tracking (simplified - refunds are standalone)
    refund_created_at TEXT,                -- When refund was created in Splitwise
    
    -- Indexes for common queries
    CHECK (amount IS NOT NULL),
    CHECK (date IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_merchant ON transactions(merchant);
CREATE INDEX IF NOT EXISTS idx_category ON transactions(category);
CREATE INDEX IF NOT EXISTS idx_source ON transactions(source);
CREATE INDEX IF NOT EXISTS idx_splitwise_id ON transactions(splitwise_id);
CREATE INDEX IF NOT EXISTS idx_written_to_sheet ON transactions(written_to_sheet);
CREATE INDEX IF NOT EXISTS idx_date_merchant ON transactions(date, merchant);
CREATE INDEX IF NOT EXISTS idx_cc_reference ON transactions(cc_reference_id);
CREATE INDEX IF NOT EXISTS idx_is_refund ON transactions(is_refund);
"""

DUPLICATES_TABLE = """
CREATE TABLE IF NOT EXISTS duplicate_checks (
    -- Track potential duplicates for manual review
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id_1 INTEGER NOT NULL,
    txn_id_2 INTEGER NOT NULL,
    similarity_score REAL,
    checked_at TEXT NOT NULL,
    is_duplicate BOOLEAN,                  -- null = pending, 1 = confirmed dupe, 0 = not dupe
    resolved_by TEXT,                      -- 'auto' or 'manual'
    
    FOREIGN KEY (txn_id_1) REFERENCES transactions(id),
    FOREIGN KEY (txn_id_2) REFERENCES transactions(id),
    UNIQUE(txn_id_1, txn_id_2)
);
"""

IMPORT_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS import_log (
    -- Audit trail for imports
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    source_type TEXT NOT NULL,             -- csv, splitwise_api, sheets, manual
    source_identifier TEXT,                -- filename, API endpoint, etc.
    records_attempted INTEGER,
    records_imported INTEGER,
    records_skipped INTEGER,
    records_failed INTEGER,
    error_message TEXT,
    metadata TEXT                          -- JSON blob for additional context
);
"""

MONTHLY_SUMMARIES_TABLE = """
CREATE TABLE IF NOT EXISTS monthly_summaries (
    -- Cached monthly summary data for comparison
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year_month TEXT NOT NULL UNIQUE,       -- YYYY-MM format
    total_spent_net REAL NOT NULL,         -- Net spending for the month
    avg_transaction REAL NOT NULL,         -- Average transaction amount
    transaction_count INTEGER NOT NULL,    -- Number of transactions
    total_paid REAL NOT NULL,              -- Total amount paid
    total_owed REAL NOT NULL,              -- Total amount owed
    cumulative_spending REAL NOT NULL,     -- Cumulative spending YTD
    mom_change REAL NOT NULL,              -- Month-over-month % change
    
    -- Sync tracking
    written_to_sheet BOOLEAN DEFAULT 0,    -- True if written to Google Sheets
    calculated_at TEXT NOT NULL,           -- When this summary was calculated
    updated_at TEXT                        -- Last update timestamp
);

CREATE INDEX IF NOT EXISTS idx_year_month ON monthly_summaries(year_month);
CREATE INDEX IF NOT EXISTS idx_written ON monthly_summaries(written_to_sheet);
"""

HOLDINGS_TABLE = """
CREATE TABLE IF NOT EXISTS holdings (
    -- Monthly account balance snapshots (source: Money sheet "Holdings YYYY" tabs)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year_month TEXT NOT NULL,              -- YYYY-MM
    account_key TEXT NOT NULL,             -- "Account | Sub-Type", stable per account
    account TEXT NOT NULL,                 -- Institution (e.g. "Fidelity")
    account_type TEXT NOT NULL,            -- Investment, Savings, Retirement, Health Savings
    sub_type TEXT,                         -- e.g. "401K [AMZN]", "Joint Savings"
    beginning_balance REAL,
    ending_balance REAL,
    source TEXT NOT NULL,                  -- money_sheet, manual, ...
    synced_at TEXT NOT NULL,

    UNIQUE(year_month, account_key)
);

CREATE INDEX IF NOT EXISTS idx_holdings_year_month ON holdings(year_month);
CREATE INDEX IF NOT EXISTS idx_holdings_account_type ON holdings(account_type);
"""


def init_database(conn):
    """Initialize database schema.

    Args:
        conn: SQLite database connection
    """
    cursor = conn.cursor()

    # Create tables
    cursor.executescript(TRANSACTIONS_TABLE)
    cursor.executescript(DUPLICATES_TABLE)
    cursor.executescript(IMPORT_LOG_TABLE)
    cursor.executescript(MONTHLY_SUMMARIES_TABLE)
    cursor.executescript(HOLDINGS_TABLE)

    conn.commit()
