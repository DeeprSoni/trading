import json
import os
import sys
import warnings
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

# Suppress deprecation warning from synthetic_data_generator in test collection
warnings.filterwarnings("ignore", message="synthetic_data_generator is DEPRECATED", category=DeprecationWarning)
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import Base


@pytest.fixture
def db_session():
    """In-memory SQLite database session for testing."""
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def mock_kite():
    """Mocked KiteConnect instance for testing without live API."""
    kite = MagicMock()

    # Mock ltp for NIFTY 50 spot
    kite.ltp.return_value = {
        "NSE:NIFTY 50": {"last_price": 22500.0},
        "NSE:INDIA VIX": {"last_price": 14.5},
    }

    # Mock instruments for NFO
    instruments = []
    expiry_date = "2026-04-30"
    for strike in range(21000, 24000, 100):
        for opt_type in ["CE", "PE"]:
            instruments.append({
                "instrument_token": hash(f"NIFTY{strike}{opt_type}") % 10**8,
                "tradingsymbol": f"NIFTY26APR{strike}{opt_type}",
                "name": "NIFTY",
                "expiry": expiry_date,
                "strike": strike,
                "instrument_type": opt_type,
                "exchange": "NFO",
                "lot_size": 25,
            })
    kite.instruments.return_value = instruments

    # Mock quote with realistic prices
    def mock_quote(symbols):
        result = {}
        for sym in symbols:
            result[sym] = {
                "last_price": 150.0,
                "ohlc": {"open": 148, "high": 155, "low": 145, "close": 150},
                "depth": {
                    "buy": [{"price": 149.5, "quantity": 100}],
                    "sell": [{"price": 150.5, "quantity": 100}],
                },
                "oi": 50000,
                "volume": 10000,
            }
        return result

    kite.quote.side_effect = mock_quote

    # Mock historical_data
    kite.historical_data.return_value = [
        {"date": "2023-01-02", "open": 18100, "high": 18200, "low": 18000, "close": 18150, "volume": 100000},
        {"date": "2023-01-03", "open": 18150, "high": 18300, "low": 18100, "close": 18250, "volume": 110000},
    ]

    # Mock margins
    kite.margins.return_value = {
        "equity": {"available": {"live_balance": 500000.0}}
    }

    kite.order_margins.return_value = [{"total": 35000.0}]

    return kite


@pytest.fixture
def sample_option_chain():
    """Load sample option chain from fixture file."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_option_chain.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def sample_spot_history():
    """Load sample historical prices from fixture file."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_historical_prices.csv"
    return pd.read_csv(fixture_path, parse_dates=["date"])


@pytest.fixture
def sample_trades():
    """Load sample trade records from fixture file."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_trades.json"
    with open(fixture_path) as f:
        return json.load(f)
