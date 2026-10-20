"""
SQLite Connection Adapter.
Configures WAL mode, busy timeout, memory temp store, and row factory.
"""
import os
import sqlite3
from typing import Optional

# Base directory for 1_Linkedin_Platforms codebase
CODEBASE_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../..")
)
DEFAULT_DB_PATH = os.path.join(CODEBASE_ROOT, "data", "database", "leads.db")

def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Returns a SQLite connection configured with WAL mode, optimized cache, and busy timeout."""
    target_path = db_path or os.environ.get("DB_PATH", DEFAULT_DB_PATH)
    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    
    conn = sqlite3.connect(target_path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA cache_size = -2048;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA mmap_size = 16777216;")
    return conn
