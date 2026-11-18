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
