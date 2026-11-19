# Backtesting and walk-forward optimisation

## Available endpoints

All machine-facing research endpoints require the configured bridge token in the `X-Bridge-Token` header.

- `GET /api/v1/backtests/run/{symbol}/{timeframe}?pip_value_per_lot=10`
- `GET /api/v1/backtests/walk-forward/{symbol}/{timeframe}?pip_value_per_lot=10`
- `GET /api/v1/market-data/quality/{symbol}/{timeframe}`
- `GET /api/v1/strategy/signal/{symbol}/{timeframe}`

The local dashboard research feed is `GET /api/v1/dashboard/research`.

## Backtest assumptions

- Signals are calculated using candles completed before the entry candle.
- Entries occur at the next candle open.
- Spread and slippage are charged on entry and exit.
- Commission is charged on both sides.
- Position volume is rounded down to the configured lot step.
- Positions are not opened if the protective stop/target are already crossed at entry.
- If stop and target are both reached in one OHLC candle, stop-loss is assumed first.
- Stop fills account for adverse gaps through the stop.
- Only one position is simulated at a time.
- Daily loss and maximum drawdown halts stop new entries.
- No tick-level order-book or broker execution simulation is implied.

The MT5 bridge now publishes broker tick size and loss tick value in account currency. Backtest endpoints derive pip size/value from stored specifications where possible. If no specification is available, provide both `pip_size` and `pip_value_per_lot`; the API refuses to guess. Never assume that all symbols or account currencies have the same pip value.

## Walk-forward process

The optimizer tests a bounded 16-combination parameter grid on two expanding chronological training windows. Each selected parameter set is then evaluated on a later, untouched validation segment. The warm-up candles overlap the preceding training period only to initialise indicators; scored entries begin in the validation segment.

Parameter screening is not proof of an edge. Use multiple market regimes, additional years of data, realistic broker-specific costs, and a separate forward-demo period. Do not select a strategy solely by win rate. Review net expectancy, profit factor, maximum drawdown, number of trades, stability across folds and sensitivity to costs.

## Data limitations

OHLC candles cannot reveal the exact intrabar path. Stop-first handling is intentionally conservative when both levels are touched. Weekend, holiday and broker-session gaps must be reviewed before treating them as missing data. Backtest results are not a promise or forecast of future returns.

All endpoints are research-only. They do not submit, modify or close broker orders.
