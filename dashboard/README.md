# Forex Autopilot dashboard

React + TypeScript + Vite read-only monitoring and research interface.

## Run locally

1. Start the backend API from the repository root (Docker Compose or the documented local Uvicorn command).
2. In a second terminal:

   ```bash
   cd dashboard
   npm install
   npm run dev
   ```

3. Open the local Vite URL (normally http://127.0.0.1:5173).

Vite proxies `/api/*` requests to `http://127.0.0.1:8000`. The dashboard uses only local, unauthenticated, read-only dashboard endpoints:
- `GET /api/v1/dashboard/overview`
- `GET /api/v1/dashboard/research`
- `GET /api/v1/dashboard/broker-specifications` (sanitized symbol contract constraints, freshness and broker trade-allowed metadata)
- `GET /api/v1/dashboard/notification-health` (aggregate outbox delivery counts, active health alerts and sanitized recent event metadata; read-only, no dispatch or leasing)
- `GET /api/v1/dashboard/data-readiness` (per-symbol/timeframe candle coverage, valid OHLC percentage, integrity issues, diagnostic gaps and research-readiness status; read-only)
- `GET /api/v1/dashboard/candle-ingestion` (durable receipts and aggregate counts for accepted MT5 bulk candle uploads; read-only)
- `GET /api/v1/dashboard/cost-sensitivity` (four historical replay scenarios with progressively higher spread, slippage and commission; read-only)
- Additional read-only portfolio, operations, recovery, execution-reconciliation, strategy-analysis and release-readiness endpoints used by dashboard panels.

No bridge or admin token is embedded in browser code. No trading controls or order submission are exposed. Trading remains disabled by the backend.

## Dashboard navigation\n\nThe interface groups overview, connectivity, research, portfolio, market data, strategy performance and operations into a responsive sticky section navigation. The strategy workspace includes a transaction-cost stress laboratory comparing base, moderate, high and severe cost assumptions on identical stored candles.\n\n## Build

```bash
npm run build
```

This scaffold is intentionally read-only. Authenticated administrative controls, user/session management, configuration editing and remote deployment are separate future work and must not be added as unauthenticated browser features.
