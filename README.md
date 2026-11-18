# FOREX AUTOPILOT

A demo-first, configurable MT5 trading research and execution platform.

## Safety status
- Initial mode: research/demo only.
- No broker credentials or live-trading capability are included.
- Strategy parameters are hypotheses, not validated profitable settings.
- Live execution must remain disabled until backtesting, forward-demo testing, risk controls, and operational checks pass.

## Architecture
- `trading-engine/`: MQL5 Expert Advisor and modular strategy/risk components.
- `research/`: historical data, backtesting and strategy evaluation.
- `backend/`: FastAPI service for configuration, monitoring and records.
- `dashboard/`: React/TypeScript web dashboard (scaffold stage).
- `config/`: versioned, non-secret application defaults.
- `documentation/`: architecture, trading rules and risk policy.

## Local setup (macOS Apple Silicon)
1. Install Xcode Command Line Tools: `xcode-select --install`
2. Install Homebrew using https://brew.sh
3. Install tools: `brew install python node git`
4. Create a Python environment: `cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
5. Run API: `uvicorn app.main:app --reload`

The MT5 terminal and MQL5 compilation/testing are performed in MetaTrader 5. For repeatable automated testing and eventual 24/5 operation, use a Windows environment/VPS after the demo prototype is validated.

## Development order
1. Verify local toolchain and create a private GitHub repository.
2. Implement and test deterministic risk calculations.
3. Implement strategy signals using closed candles only.
4. Implement the MT5 EA in demo-only mode.
5. Backtest with realistic spread, commission and slippage assumptions.
6. Add database/API and dashboard.
7. Run forward demo tests and operational failure tests.

## Never commit
Broker passwords, investor passwords, API keys, `.env` files, account numbers, or private keys.
