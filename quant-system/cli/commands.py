import typer

app = typer.Typer(help="Quant Trading System — Non-Speculative Derivatives Income")


@app.command()
def morning_review():
    """Run daily review before market open at 9:00 AM."""
    typer.echo("Morning review — not yet implemented")


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
