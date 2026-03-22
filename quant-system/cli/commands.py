import json
from datetime import datetime

import typer

app = typer.Typer(help="Quant Trading System — Non-Speculative Derivatives Income")


@app.command()
def morning_review():
    """Display current market state, entry signals, and open position status."""
    from rich.console import Console
    from rich.table import Table
    from config import settings

    console = Console()
    console.print("[bold]Morning Review[/bold]", style="cyan")
    console.print(f"Capital: Rs {settings.TOTAL_CAPITAL:,} | Active: Rs {settings.PHASE_1_ACTIVE_CAPITAL:,}")

    # Try to fetch live data, fall back to showing instructions
    try:
        from src.data_fetcher import DataFetcher
        fetcher = DataFetcher()
        vix = fetcher.get_india_vix()
        console.print(f"India VIX: {vix:.1f}")
    except Exception:
        console.print("[yellow]Live data unavailable — configure Kite Connect API keys[/yellow]")
        console.print("Set ZERODHA_API_KEY and ZERODHA_API_SECRET in .env")

    # Show entry gate status
    table = Table(title="IC Entry Gates")
    table.add_column("Gate", style="cyan")
    table.add_column("Threshold")
    table.add_column("Status")

    table.add_row("IV Rank", f">= {settings.IC_IVR_MIN}", "Check live data")
    table.add_row("VIX", f"<= {settings.IC_VIX_STANDARD_MAX} (std) / {settings.IC_VIX_ELEVATED_MAX} (elevated)", "Check live data")
    table.add_row("DTE", f"{settings.IC_MIN_DTE_ENTRY}-{settings.IC_MAX_DTE_ENTRY} days", "Check expiry calendar")
    table.add_row("Event Blackout", f"{settings.IC_EVENT_BLACKOUT_DAYS} days", "Check events_calendar.json")
    table.add_row("Drawdown", f"< {settings.ACCOUNT_DRAWDOWN_STOP:.0%}", "Check portfolio")

    console.print(table)
    console.print("\n[dim]Run with Kite Connect configured for live signals[/dim]")


@app.command()
def login():
    """Daily Zerodha token refresh. Run every morning before morning-review."""
    typer.echo("Login — not yet implemented")


@app.command()
def backtest(
    from_date: str = typer.Option("2021-01-01", help="Start date YYYY-MM-DD"),
    to_date: str = typer.Option("2023-12-31", help="End date YYYY-MM-DD"),
    strategy: str = typer.Option("IC", help="IC or CAL"),
    sweep: bool = typer.Option(False, help="Run parameter sweep"),
):
    """Run historical backtest and show GO/NO-GO verdict."""
    typer.echo("Backtest — not yet implemented")


@app.command()
def execute_trade(trade_type: str = typer.Argument(help="IC or CAL")):
    """Interactive trade entry with cost breakdown and confirmation."""
    typer.echo("Execute trade — not yet implemented")


@app.command()
def close_position(position_id: int = typer.Argument(help="Trade ID to close")):
    """Close a specific position by trade ID."""
    typer.echo("Close position — not yet implemented")


@app.command()
def portfolio():
    """Show full portfolio with live Greeks and current P&L."""
    typer.echo("Portfolio — not yet implemented")


@app.command()
def edge_report():
    """Display all edge tracking metrics and any active stop signals."""
    typer.echo("Edge report — not yet implemented")


@app.command()
def ask(question: str = typer.Argument(help="Question about your positions or strategy")):
    """Ask Claude a question about current positions or market conditions."""
    typer.echo("Ask — not yet implemented")


@app.command()
def paper_entry(
    symbol: str = typer.Option("NIFTY", help="Underlying symbol"),
    strategy: str = typer.Option(..., help="Strategy: IC, CAL, BWB, STRANGLE"),
    legs: str = typer.Option(..., help='Legs JSON: [{"strike":24000,"type":"CE","side":"sell","premium":50}]'),
    credit: float = typer.Option(0.0, help="Total credit collected"),
    debit: float = typer.Option(0.0, help="Total debit paid"),
    trigger: str = typer.Option(None, help="Entry trigger/signal name"),
    notes: str = typer.Option(None, help="Trade notes"),
):
    """Record a paper trade entry."""
    from rich.console import Console
    from db import SessionLocal
    from db.models import PaperTrade

    console = Console()

    # Validate legs JSON
    try:
        legs_parsed = json.loads(legs)
        if not isinstance(legs_parsed, list):
            raise ValueError("legs must be a JSON array")
    except (json.JSONDecodeError, ValueError) as e:
        console.print(f"[red]Invalid legs JSON: {e}[/red]")
        raise typer.Exit(code=1)

    # Validate strategy
    valid_strategies = ("IC", "CAL", "BWB", "STRANGLE")
    if strategy.upper() not in valid_strategies:
        console.print(f"[red]Strategy must be one of {valid_strategies}[/red]")
        raise typer.Exit(code=1)

    trade = PaperTrade(
        date=datetime.now(),
        symbol=symbol.upper(),
        action="entry",
        strategy=strategy.upper(),
        legs_json=json.dumps(legs_parsed),
        credit_collected=credit,
        debit_paid=debit,
        status="open",
        trigger=trigger,
        notes=notes,
    )

    session = SessionLocal()
    try:
        session.add(trade)
        session.commit()
        console.print(f"[green]Paper trade #{trade.id} recorded[/green]")
        console.print(f"  Strategy: {trade.strategy} | Symbol: {trade.symbol}")
        console.print(f"  Credit: {trade.credit_collected} | Debit: {trade.debit_paid}")
        console.print(f"  Legs: {trade.legs_json}")
    finally:
        session.close()


@app.command()
def paper_exit(
    trade_id: int = typer.Argument(help="Paper trade ID to close"),
    exit_credit: float = typer.Option(0.0, help="Credit received on exit"),
    slippage: float = typer.Option(None, help="Actual slippage observed"),
    notes: str = typer.Option(None, help="Exit notes"),
):
    """Record exit for a paper trade with actual fill price."""
    from rich.console import Console
    from db import SessionLocal
    from db.models import PaperTrade

    console = Console()
    session = SessionLocal()
    try:
        trade = session.query(PaperTrade).filter(PaperTrade.id == trade_id).first()
        if not trade:
            console.print(f"[red]Paper trade #{trade_id} not found[/red]")
            raise typer.Exit(code=1)
        if trade.status != "open":
            console.print(f"[red]Paper trade #{trade_id} is already {trade.status}[/red]")
            raise typer.Exit(code=1)

        trade.exit_date = datetime.now()
        trade.exit_credit = exit_credit
        trade.slippage_actual = slippage
        trade.realised_pnl = trade.credit_collected - trade.debit_paid + exit_credit
        trade.status = "closed"
        trade.action = "exit"
        if notes:
            existing = trade.notes or ""
            trade.notes = f"{existing}\nExit: {notes}".strip()

        session.commit()
        console.print(f"[green]Paper trade #{trade.id} closed[/green]")
        console.print(f"  Realised P&L: {trade.realised_pnl:.2f}")
        if trade.slippage_actual is not None:
            console.print(f"  Slippage: {trade.slippage_actual:.2f}")
    finally:
        session.close()


@app.command()
def paper_summary():
    """Show all paper trades with P&L."""
    from rich.console import Console
    from rich.table import Table
    from db import SessionLocal
    from db.models import PaperTrade

    console = Console()
    session = SessionLocal()
    try:
        trades = session.query(PaperTrade).order_by(PaperTrade.date.desc()).all()
        if not trades:
            console.print("[yellow]No paper trades recorded yet[/yellow]")
            return

        table = Table(title="Paper Trades")
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("Date")
        table.add_column("Symbol")
        table.add_column("Strategy")
        table.add_column("Status")
        table.add_column("Credit", justify="right")
        table.add_column("Debit", justify="right")
        table.add_column("P&L", justify="right")
        table.add_column("Trigger")

        total_pnl = 0.0
        open_count = 0
        closed_count = 0

        for t in trades:
            pnl_str = ""
            if t.realised_pnl is not None:
                pnl_str = f"{t.realised_pnl:.2f}"
                total_pnl += t.realised_pnl
                closed_count += 1
            else:
                open_count += 1

            status_style = "green" if t.status == "open" else "dim"
            table.add_row(
                str(t.id),
                t.date.strftime("%Y-%m-%d"),
                t.symbol,
                t.strategy,
                f"[{status_style}]{t.status}[/{status_style}]",
                f"{t.credit_collected:.2f}",
                f"{t.debit_paid:.2f}",
                pnl_str,
                t.trigger or "",
            )

        console.print(table)
        console.print(f"\nOpen: {open_count} | Closed: {closed_count} | Total Realised P&L: {total_pnl:.2f}")
    finally:
        session.close()
