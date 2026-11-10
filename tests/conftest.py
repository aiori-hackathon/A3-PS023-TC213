import os
import pytest
from pathlib import Path

TEST_DB_PATH = "test_cluster.db"

@pytest.fixture(autouse=True)
def isolate_test_db(monkeypatch):
    """
    Automatically isolates the SQLite database for every test.
    Ensures tests run against test_cluster.db, preserving controller.db.
    """
    # 1. Override environment variable for all processes/subprocesses
    monkeypatch.setenv("CH_DB_PATH", TEST_DB_PATH)
    
    # 2. Clean up any existing stale test database before the test runs
    if Path(TEST_DB_PATH).exists():
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass

    yield

    # 3. Clean up the test database file after the test finishes
    if Path(TEST_DB_PATH).exists():
        try:
            os.remove(TEST_DB_PATH)
        except OSError:
            pass
