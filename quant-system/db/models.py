from datetime import datetime, date

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Date, Text, Boolean,
    ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from db import Base


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_code = Column(String, unique=True, nullable=False)  # T001, T002...
    strategy = Column(String, nullable=False)  # "IC" or "CAL"
    underlying = Column(String, nullable=False)  # "NIFTY"
    status = Column(String, nullable=False, default="OPEN")  # "OPEN" or "CLOSED"
    entry_date = Column(DateTime, nullable=False)
    expiry_date = Column(DateTime, nullable=False)

    # Strikes
    short_strike_1 = Column(Integer)  # IC: short call / CAL: front month strike
    short_strike_2 = Column(Integer)  # IC: short put
    long_strike_1 = Column(Integer)   # IC: long call wing
    long_strike_2 = Column(Integer)   # IC: long put wing

    # Entry conditions
    iv_rank_at_entry = Column(Float)
    india_vix_at_entry = Column(Float)
    entry_premium_per_unit = Column(Float)  # Gross premium
    net_premium_per_unit = Column(Float)    # After estimated costs
    lots = Column(Integer, default=1)
    market_regime = Column(String)  # SIDEWAYS/TRENDING/HIGH_VOL/NORMAL

    # Exit fields (nullable — filled when position is closed)
    exit_date = Column(DateTime, nullable=True)
    exit_reason = Column(String, nullable=True)  # PROFIT_TARGET/TIME_STOP/STOP_LOSS/ADJUSTED
    exit_price_per_unit = Column(Float, nullable=True)
    gross_pnl = Column(Float, nullable=True)
    net_pnl = Column(Float, nullable=True)
    days_in_trade = Column(Integer, nullable=True)

    # Cost tracking
    brokerage_paid = Column(Float, nullable=True)
    stt_paid = Column(Float, nullable=True)
    slippage_estimate = Column(Float, nullable=True)
    total_costs = Column(Float, nullable=True)

    notes = Column(Text, nullable=True)

    # Relationships
    calendar_cycles = relationship("CalendarCycle", back_populates="trade")
    order_logs = relationship("OrderLog", back_populates="trade")
    alerts = relationship("AlertLog", back_populates="trade")


class CalendarCycle(Base):
    __tablename__ = "calendar_cycles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=False)
    cycle_number = Column(Integer, nullable=False)  # 1 for first front month, 2 for second, etc
    front_month_expiry = Column(DateTime, nullable=False)
    premium_collected = Column(Float, nullable=False)
    exit_date = Column(DateTime, nullable=True)
    exit_price = Column(Float, nullable=True)
    cycle_pnl = Column(Float, nullable=True)

    trade = relationship("Trade", back_populates="calendar_cycles")


class EdgeMetric(Base):
    __tablename__ = "edge_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    rolling_win_rate_20 = Column(Float)
    rolling_profit_factor_20 = Column(Float)
    total_trades_all_time = Column(Integer)
    ytd_net_pnl = Column(Float)
    regime_sideways_win_rate = Column(Float, nullable=True)
    regime_trending_win_rate = Column(Float, nullable=True)
    regime_highvol_win_rate = Column(Float, nullable=True)


class OrderLog(Base):
    __tablename__ = "order_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=True)
    zerodha_order_id = Column(String, nullable=True)
    symbol = Column(String, nullable=False)
    transaction_type = Column(String, nullable=False)  # BUY or SELL
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    order_type = Column(String, nullable=False)  # LIMIT or MARKET
    status = Column(String, nullable=False)  # PLACED/FILLED/REJECTED/CANCELLED
    fill_price = Column(Float, nullable=True)
    slippage_actual = Column(Float, nullable=True)  # fill_price - price
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    error_message = Column(String, nullable=True)

    trade = relationship("Trade", back_populates="order_logs")


class ZerodhaSession(Base):
    __tablename__ = "zerodha_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, unique=True, nullable=False)
    access_token = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AlertLog(Base):
    __tablename__ = "alert_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_type = Column(String, nullable=False)  # EXIT_SIGNAL/ADJUSTMENT/STOP_SIGNAL/INFO
    urgency = Column(String, nullable=False)  # IMMEDIATE/TODAY/MONITOR
    message = Column(Text, nullable=False)
    position_id = Column(Integer, ForeignKey("trades.id"), nullable=True)
    acknowledged = Column(Boolean, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    trade = relationship("Trade", back_populates="alerts")


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False)
    symbol = Column(String(20), default="NIFTY")
    action = Column(String(20), nullable=False)  # "entry", "exit", "adjust"
    strategy = Column(String(20), nullable=False)  # "IC", "CAL", "BWB", "STRANGLE"
    legs_json = Column(Text)  # JSON: list of {strike, type, side, premium}
    credit_collected = Column(Float, default=0.0)
    debit_paid = Column(Float, default=0.0)
    exit_date = Column(DateTime, nullable=True)
    exit_credit = Column(Float, nullable=True)
    realised_pnl = Column(Float, nullable=True)
    slippage_actual = Column(Float, nullable=True)  # actual fill vs mid
    status = Column(String(20), default="open")  # "open", "closed", "adjusted"
    trigger = Column(String(50), nullable=True)  # which gate/signal caused entry
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
