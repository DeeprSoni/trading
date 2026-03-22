from datetime import date, datetime

from sqlalchemy.orm import Session

from db.models import (
    Trade, CalendarCycle, EdgeMetric, OrderLog, ZerodhaSession, AlertLog,
)


# --- Trades ---

def create_trade(db: Session, **kwargs) -> Trade:
    trade = Trade(**kwargs)
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


def get_trade(db: Session, trade_id: int) -> Trade | None:
    return db.query(Trade).filter(Trade.id == trade_id).first()


def get_trade_by_code(db: Session, trade_code: str) -> Trade | None:
    return db.query(Trade).filter(Trade.trade_code == trade_code).first()


def get_open_trades(db: Session, strategy: str | None = None) -> list[Trade]:
    query = db.query(Trade).filter(Trade.status == "OPEN")
    if strategy:
        query = query.filter(Trade.strategy == strategy)
    return query.all()


def get_all_trades(
    db: Session,
    strategy: str | None = None,
    outcome: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[Trade]:
    query = db.query(Trade)
    if strategy:
        query = query.filter(Trade.strategy == strategy)
    if outcome == "win":
        query = query.filter(Trade.net_pnl > 0)
    elif outcome == "loss":
        query = query.filter(Trade.net_pnl <= 0)
    elif outcome == "open":
        query = query.filter(Trade.status == "OPEN")
    if from_date:
        query = query.filter(Trade.entry_date >= from_date)
    if to_date:
        query = query.filter(Trade.entry_date <= to_date)
    return query.order_by(Trade.entry_date.desc()).all()


def update_trade(db: Session, trade_id: int, **kwargs) -> Trade | None:
    trade = get_trade(db, trade_id)
    if not trade:
        return None
    for key, value in kwargs.items():
        setattr(trade, key, value)
    db.commit()
    db.refresh(trade)
    return trade


def close_trade(
    db: Session,
    trade_id: int,
    exit_date: datetime,
    exit_reason: str,
    exit_price_per_unit: float,
    gross_pnl: float,
    net_pnl: float,
    days_in_trade: int,
    total_costs: float,
    brokerage_paid: float | None = None,
    stt_paid: float | None = None,
    slippage_estimate: float | None = None,
) -> Trade | None:
    return update_trade(
        db, trade_id,
        status="CLOSED",
        exit_date=exit_date,
        exit_reason=exit_reason,
        exit_price_per_unit=exit_price_per_unit,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        days_in_trade=days_in_trade,
        total_costs=total_costs,
        brokerage_paid=brokerage_paid,
        stt_paid=stt_paid,
        slippage_estimate=slippage_estimate,
    )


def get_next_trade_code(db: Session) -> str:
    last = db.query(Trade).order_by(Trade.id.desc()).first()
    next_num = (last.id + 1) if last else 1
    return f"T{next_num:03d}"


def get_closed_trades(db: Session, last_n: int | None = None) -> list[Trade]:
    query = db.query(Trade).filter(Trade.status == "CLOSED").order_by(Trade.exit_date.desc())
    if last_n:
        query = query.limit(last_n)
    return query.all()


# --- Calendar Cycles ---

def create_calendar_cycle(db: Session, **kwargs) -> CalendarCycle:
    cycle = CalendarCycle(**kwargs)
    db.add(cycle)
    db.commit()
    db.refresh(cycle)
    return cycle


def get_cycles_for_trade(db: Session, trade_id: int) -> list[CalendarCycle]:
    return (
        db.query(CalendarCycle)
        .filter(CalendarCycle.trade_id == trade_id)
        .order_by(CalendarCycle.cycle_number)
        .all()
    )


# --- Edge Metrics ---

def save_edge_metric(db: Session, **kwargs) -> EdgeMetric:
    metric = EdgeMetric(**kwargs)
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return metric


def get_latest_edge_metrics(db: Session) -> EdgeMetric | None:
    return db.query(EdgeMetric).order_by(EdgeMetric.snapshot_date.desc()).first()


def get_edge_history(db: Session, limit: int = 50) -> list[EdgeMetric]:
    return (
        db.query(EdgeMetric)
        .order_by(EdgeMetric.snapshot_date.desc())
        .limit(limit)
        .all()
    )


# --- Order Log ---

def create_order_log(db: Session, **kwargs) -> OrderLog:
    order = OrderLog(**kwargs)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def get_orders_for_trade(db: Session, trade_id: int) -> list[OrderLog]:
    return (
        db.query(OrderLog)
        .filter(OrderLog.trade_id == trade_id)
        .order_by(OrderLog.timestamp)
        .all()
    )


# --- Zerodha Sessions ---

def save_zerodha_session(db: Session, session_date: date, access_token: str) -> ZerodhaSession:
    existing = db.query(ZerodhaSession).filter(ZerodhaSession.date == session_date).first()
    if existing:
        existing.access_token = access_token
        existing.created_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing
    session = ZerodhaSession(date=session_date, access_token=access_token)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_today_session(db: Session) -> ZerodhaSession | None:
    return db.query(ZerodhaSession).filter(ZerodhaSession.date == date.today()).first()


# --- Alert Log ---

def create_alert(db: Session, **kwargs) -> AlertLog:
    alert = AlertLog(**kwargs)
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def get_unacknowledged_alerts(db: Session) -> list[AlertLog]:
    return (
        db.query(AlertLog)
        .filter(AlertLog.acknowledged == False)
        .order_by(AlertLog.created_at.desc())
        .all()
    )


def acknowledge_alert(db: Session, alert_id: int) -> AlertLog | None:
    alert = db.query(AlertLog).filter(AlertLog.id == alert_id).first()
    if alert:
        alert.acknowledged = True
        db.commit()
        db.refresh(alert)
    return alert


def get_recent_alerts(db: Session, limit: int = 10) -> list[AlertLog]:
    return (
        db.query(AlertLog)
        .order_by(AlertLog.created_at.desc())
        .limit(limit)
        .all()
    )
