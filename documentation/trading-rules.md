# TrendPullback_v1 — research hypothesis

Initial research universe: EURUSD, H1.

Hypothesis:
- Directional filter: EMA(50) relative to EMA(200).
- Pullback: price approaches the EMA(50) in the direction of the prevailing trend.
- Confirmation: RSI(14) and a completed-candle confirmation rule.
- Stop distance: ATR(14)-based, with broker minimum-stop constraints.
- Initial target: 2R.

Exact thresholds and candle definitions must be specified before coding the signal and must be frozen for each backtest run. Use closed candles only. No claim of profitability is made. Test out-of-sample and across multiple regimes; account for spread, commission, swaps and slippage.
