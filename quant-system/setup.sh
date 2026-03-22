#!/bin/bash
set -e
echo "Setting up Quant Trading System..."

python3 --version | grep -E "3\.(1[1-9]|[2-9][0-9])" || { echo "ERROR: Python 3.11+ required"; exit 1; }

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.template .env
  echo "IMPORTANT: Fill in your API keys in .env before running"
fi

python -m alembic upgrade head

mkdir -p data/historical data/cache logs

echo "Setup complete. Run: source venv/bin/activate && python cli.py --help"
