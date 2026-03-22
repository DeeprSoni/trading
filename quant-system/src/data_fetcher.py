"""
Data Fetcher — Primary data source is Kite Connect API.

NSE scraping is only used as a fallback for India VIX when Kite is unavailable.
Historical options data for backtesting is generated synthetically (see synthetic_data_generator.py).
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from config import settings
from src.exceptions import DataStalenessError

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/cache")
HISTORICAL_DIR = Path("data/historical")


class DataFetcher:
    """Fetches live market data via Kite Connect, with NSE fallback for VIX."""

    NSE_BASE_URL = "https://www.nseindia.com"
    NSE_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.nseindia.com/option-chain",
        "Connection": "keep-alive",
    }

    def __init__(self, kite=None):
        """
        Args:
            kite: Authenticated KiteConnect instance. If None, only cached/NSE
                  data is available (useful for testing).
        """
        self.kite = kite
        self._nse_session = None

    # --- Option Chain (Kite Connect primary) ---

    def get_option_chain(self, symbol: str = "NIFTY") -> dict:
        """
        Fetch current option chain via Kite Connect.

        Returns dict with keys:
          records: list of option rows
          timestamp: datetime string
          underlying_value: current index level
          expiry_dates: list of available expiry dates
        """
        cache_path = CACHE_DIR / f"{symbol}_chain.json"

        try:
            if self.kite is None:
                raise RuntimeError("KiteConnect not initialized")

            # Get underlying price
            ltp_key = f"NSE:{symbol} 50" if symbol == "NIFTY" else f"NSE:{symbol}"
            ltp_data = self.kite.ltp(ltp_key)
            underlying_value = ltp_data[ltp_key]["last_price"]

            # Get all NFO instruments for this symbol
            all_instruments = self.kite.instruments("NFO")
            option_instruments = [
                i for i in all_instruments
                if i["name"] == symbol and i["instrument_type"] in ("CE", "PE")
            ]

            if not option_instruments:
                raise RuntimeError(f"No option instruments found for {symbol}")

            # Collect unique expiry dates
            expiry_dates = sorted(set(
                str(i["expiry"]) for i in option_instruments
            ))

            # Get quotes in batches of 500
            records = []
            trading_symbols = [
                f"NFO:{i['tradingsymbol']}" for i in option_instruments
            ]

            for batch_start in range(0, len(trading_symbols), 500):
                batch = trading_symbols[batch_start:batch_start + 500]
                quotes = self.kite.quote(batch)

                for sym_key, quote in quotes.items():
                    # Find matching instrument
                    ts = sym_key.replace("NFO:", "")
                    inst = next(
                        (i for i in option_instruments if i["tradingsymbol"] == ts),
                        None,
                    )
                    if inst is None:
                        continue

                    depth = quote.get("depth", {})
                    buy_depth = depth.get("buy", [{}])
                    sell_depth = depth.get("sell", [{}])
                    bid = buy_depth[0].get("price", 0) if buy_depth else 0
                    ask = sell_depth[0].get("price", 0) if sell_depth else 0

                    records.append({
                        "strike": inst["strike"],
                        "option_type": inst["instrument_type"],
                        "expiry": str(inst["expiry"]),
                        "tradingsymbol": ts,
                        "bid": bid,
                        "ask": ask,
                        "ltp": quote.get("last_price", 0),
                        "iv": 0,  # Kite doesn't provide IV directly
                        "oi": quote.get("oi", 0),
                        "volume": quote.get("volume", 0),
                    })

            result = {
                "records": records,
                "timestamp": datetime.now().isoformat(),
                "underlying_value": underlying_value,
                "expiry_dates": expiry_dates,
            }

            # Save to cache
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w") as f:
                json.dump(result, f)

            return result

        except Exception as e:
            logger.warning("Kite option chain fetch failed: %s. Trying cache.", e)
            return self._load_cache_or_raise(cache_path, symbol)

    # --- India VIX ---

    def get_india_vix(self) -> float:
        """
        Get India VIX. Primary: Kite. Fallback: NSE scraping.
        """
        cache_path = CACHE_DIR / "india_vix.json"

        # Try Kite first
        if self.kite is not None:
            try:
                ltp_data = self.kite.ltp("NSE:INDIA VIX")
                vix = ltp_data["NSE:INDIA VIX"]["last_price"]
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                with open(cache_path, "w") as f:
                    json.dump({"vix": vix, "timestamp": datetime.now().isoformat()}, f)
                return float(vix)
            except Exception as e:
                logger.warning("Kite VIX fetch failed: %s. Trying NSE fallback.", e)

        # NSE fallback
        try:
            session = self._get_nse_session()
            resp = session.get(
                f"{self.NSE_BASE_URL}/api/allIndices",
                headers=self.NSE_HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            for index in data.get("data", []):
                if index.get("index") == "INDIA VIX":
                    vix = float(index["last"])
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    with open(cache_path, "w") as f:
                        json.dump({"vix": vix, "timestamp": datetime.now().isoformat()}, f)
                    return vix
            raise ValueError("INDIA VIX not found in NSE response")
        except Exception as e:
            logger.warning("NSE VIX fallback failed: %s. Using cache.", e)

        # Cache fallback
        if cache_path.exists():
            with open(cache_path) as f:
                cached = json.load(f)
            return float(cached["vix"])

        logger.error("No VIX data available from any source.")
        return 15.0  # Safe default

    # --- Nifty Price History ---

    def get_nifty_price_history(
        self, from_date: str, to_date: str
    ) -> pd.DataFrame:
        """
        Fetch Nifty 50 daily price history via Kite Connect.
        Uses instrument_token 256265 (NIFTY 50).

        Saves to CSV and returns from cache if file exists.
        """
        HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = HISTORICAL_DIR / f"nifty_price_{from_date}_{to_date}.csv"

        if cache_file.exists():
            return pd.read_csv(cache_file, parse_dates=["date"])

        if self.kite is None:
            logger.warning("KiteConnect not available. Cannot fetch history.")
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

        try:
            from_dt = datetime.strptime(from_date, "%Y-%m-%d")
            to_dt = datetime.strptime(to_date, "%Y-%m-%d")

            all_data = []
            # Kite allows max ~2000 days per request for daily candles
            chunk_start = from_dt
            while chunk_start < to_dt:
                chunk_end = min(chunk_start + timedelta(days=1900), to_dt)
                data = self.kite.historical_data(
                    settings.NIFTY_INSTRUMENT_TOKEN,
                    chunk_start,
                    chunk_end,
                    "day",
                )
                all_data.extend(data)
                chunk_start = chunk_end + timedelta(days=1)

            df = pd.DataFrame(all_data)
            if not df.empty:
                df = df.rename(columns={"date": "date"})
                df["date"] = pd.to_datetime(df["date"])
                df = df[["date", "open", "high", "low", "close", "volume"]]
                df.to_csv(cache_file, index=False)

            return df

        except Exception as e:
            logger.error("Failed to fetch Nifty history: %s", e)
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    # --- NSE Session (lazy init, VIX fallback only) ---

    def _get_nse_session(self) -> requests.Session:
        """Create or return NSE session with cookies."""
        if self._nse_session is None:
            self._nse_session = requests.Session()
            self._nse_session.headers.update(self.NSE_HEADERS)
            try:
                self._nse_session.get(self.NSE_BASE_URL, timeout=10)
            except Exception as e:
                logger.warning("NSE session init failed: %s", e)
        return self._nse_session

    # --- Cache helpers ---

    def _load_cache_or_raise(self, cache_path: Path, symbol: str) -> dict:
        """Load cached data or raise DataStalenessError if too old during market hours."""
        if not cache_path.exists():
            raise DataStalenessError(f"No cached data for {symbol} and API is unavailable")

        with open(cache_path) as f:
            cached = json.load(f)

        # Check staleness during market hours
        cached_time = datetime.fromisoformat(cached.get("timestamp", "2000-01-01"))
        age_minutes = (datetime.now() - cached_time).total_seconds() / 60

        if self._is_market_hours() and age_minutes > settings.DATA_REFRESH_INTERVAL_MIN:
            raise DataStalenessError(
                f"Cached {symbol} data is {age_minutes:.0f} minutes old "
                f"(max {settings.DATA_REFRESH_INTERVAL_MIN} during market hours)"
            )

        logger.info("Using cached data for %s (%.0f minutes old)", symbol, age_minutes)
        return cached

    @staticmethod
    def _is_market_hours() -> bool:
        """Check if current time is during Indian market hours (09:15 - 15:30 IST)."""
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo(settings.TIMEZONE))
        except ImportError:
            import pytz
            now = datetime.now(pytz.timezone(settings.TIMEZONE))

        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)

        # Skip weekends
        if now.weekday() >= 5:
            return False

        return market_open <= now <= market_close
