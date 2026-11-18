// FOREX AUTOPILOT - initial EA scaffold
// This version intentionally does not place orders.
// Implement and validate risk controls before adding execution.
#property strict
#property version   "0.1.0"
#property description "FOREX AUTOPILOT demo-first EA scaffold"

input bool   InpTradingEnabled = false;
input double InpRiskPerTradePct = 0.25;
input double InpMaxDailyLossPct = 1.0;
input double InpMaxDrawdownPct = 5.0;
input int    InpMaxConcurrentPositions = 2;
input int    InpFastEMA = 50;
input int    InpSlowEMA = 200;
input int    InpRSIPeriod = 14;
input int    InpATRPeriod = 14;
input double InpRewardToRisk = 2.0;

int OnInit()
{
   Print("FOREX AUTOPILOT scaffold loaded. Trading enabled: ", InpTradingEnabled);
   Print("Order execution is not implemented in this development build.");
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   Print("FOREX AUTOPILOT stopped. Reason: ", reason);
}

void OnTick()
{
   // TODO: closed-candle signal evaluation.
   // TODO: independent risk checks and fail-closed behaviour.
   // TODO: demo-only order execution after validation.
   // No trading actions are performed by this scaffold.
}
