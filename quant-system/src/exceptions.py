"""Custom exceptions for the quant trading system."""


class DataStalenessError(Exception):
    """Raised when cached data is older than 15 minutes during market hours."""


class InvalidTradeStructureError(Exception):
    """Raised when a generated trade structure fails validation."""


class ExpiryNotFoundError(Exception):
    """Raised when no expiry is found in the target DTE window."""
