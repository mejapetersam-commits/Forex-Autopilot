# Risk policy — initial proposed defaults

- Risk per trade: 0.25% of equity (research/demo default).
- Daily loss stop: 1% of start-of-day equity; block new entries after breach.
- Maximum equity drawdown: 5% from configured high-water mark; enter protective halt.
- Maximum concurrent positions: 2, subject to aggregate correlated exposure checks.
- Stop-loss required for every position.
- Martingale and grid behaviour prohibited.
- Position sizing must use symbol tick value, tick size, contract size, account currency conversion and volume step; never use a hard-coded pip-value assumption.
- On uncertain account state, disconnect, stale data, rejected protection order or invalid configuration: fail closed and alert.

These are conservative design defaults, not guarantees or financial advice. Validate broker-specific calculations on demo before any live use.

- Correlation threshold: absolute Pearson correlation of 0.80 or higher is treated as strongly correlated.
- Correlated group risk budget: 0.50% of current equity across the proposed trade and directly correlated open positions.
- Correlation checking remains disabled by default until a market-data adapter supplies fresh, timestamp-aligned return series. When enabled, missing pair data or a missing proposed symbol blocks the new trade.
- Positive and negative correlation are both considered through the absolute coefficient. Correlation estimates must be calculated from aligned observations; stale or mismatched series must not be treated as valid.

Correlation controls are an additional safeguard, not a substitute for total portfolio, currency, daily-loss or drawdown limits.
