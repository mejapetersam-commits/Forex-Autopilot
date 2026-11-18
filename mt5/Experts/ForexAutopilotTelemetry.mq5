// FOREX AUTOPILOT - read-only MT5 telemetry bridge
// This Expert Advisor sends connection, account, quote and OHLC candle telemetry only.
// It contains NO trade execution, order, position modification or close functions.

#property strict
#property version   "1.04"
#property description "FOREX AUTOPILOT read-only telemetry bridge"

input string InpApiBaseUrl = "https://YOUR-API-HOST";
input string InpBridgeToken = ""; // Set locally in MT5; never commit a real token.
input string InpSymbols = "EURUSD,GBPUSD";
input int    InpHeartbeatSeconds = 15;
input int    InpHttpTimeoutMs = 5000;
input int    InpCandleBootstrapBars = 80;
input int    InpCandleRefreshSeconds = 60;

string g_symbols[];
ulong  g_last_quote_time_msc[];
ulong  g_last_snapshot_ms = 0;

ENUM_TIMEFRAMES g_candle_timeframes[4] = {PERIOD_M5, PERIOD_M15, PERIOD_H1, PERIOD_H4};
int g_candle_next_index = 0;
bool g_candle_bootstrap_complete = false;
int g_candle_attempts[];
bool g_candle_bootstrap_done[];
#define CANDLE_MAX_ATTEMPTS 3
ulong g_candle_last_request_ms = 0;
ulong g_candle_cycle_wait_until_ms = 0;

string Trimmed(string value)
{
   StringTrimLeft(value);
   StringTrimRight(value);
   return value;
}

string IsoUtcNow()
{
   string value = TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS);
   StringReplace(value, ".", "-");
   StringReplace(value, " ", "T");
   return value + "Z";
}

string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   return value;
}

bool PostJson(string route, string body)
{
   string url = InpApiBaseUrl + route;
   string headers = "Content-Type: application/json\r\nX-Bridge-Token: " + InpBridgeToken + "\r\n";
   char data[];
   char result[];
   string response_headers;

   int copied = StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(copied <= 1)
   {
      Print("FOREX AUTOPILOT: JSON encoding failed for ", route);
      return false;
   }
   ArrayResize(data, copied - 1);

   ResetLastError();
   int status = WebRequest("POST", url, headers, InpHttpTimeoutMs, data, result, response_headers);
   int request_error = GetLastError();
   string response = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);

   if(status == -1 || status < 100 || status > 599)
   {
      Print("FOREX AUTOPILOT: MT5 WebRequest transport failure for ", route,
            "; return_code=", status,
            "; terminal_error=", request_error,
            "; response_headers=", response_headers,
            "; response=", response);
      return false;
   }

   if(status < 200 || status >= 300)
   {
      Print("FOREX AUTOPILOT: API returned HTTP ", status, " for ", route,
            "; response_headers=", response_headers,
            "; response=", response);
      return false;
   }
   Print("FOREX AUTOPILOT: telemetry accepted at ", route);
   return true;
}

void SendHeartbeat()
{
   string server = JsonEscape(AccountInfoString(ACCOUNT_SERVER));
   bool connected = (bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   string body = StringFormat(
      "{\"server\":\"%s\",\"terminal_connected\":%s,\"observed_at\":\"%s\"}",
      server, connected ? "true" : "false", IsoUtcNow()
   );
   PostJson("/api/v1/mt5/heartbeat", body);
}

void SendAccountSnapshot()
{
   string server = JsonEscape(AccountInfoString(ACCOUNT_SERVER));
   string currency = JsonEscape(AccountInfoString(ACCOUNT_CURRENCY));
   long leverage = AccountInfoInteger(ACCOUNT_LEVERAGE);

   string body = StringFormat(
      "{\"server\":\"%s\",\"account_currency\":\"%s\",\"balance\":%.8f,"
      "\"equity\":%.8f,\"margin\":%.8f,\"free_margin\":%.8f,"
      "\"leverage\":%I64d,\"observed_at\":\"%s\"}",
      server, currency,
      AccountInfoDouble(ACCOUNT_BALANCE),
      AccountInfoDouble(ACCOUNT_EQUITY),
      AccountInfoDouble(ACCOUNT_MARGIN),
      AccountInfoDouble(ACCOUNT_MARGIN_FREE),
      leverage, IsoUtcNow()
   );
   PostJson("/api/v1/mt5/account", body);
}

// Sample each configured symbol independently on the one-second timer.
// A quote is posted only when MT5 reports a genuinely newer market tick.
void SendQuotes()
{
   for(int i = 0; i < ArraySize(g_symbols); i++)
   {
      string symbol = g_symbols[i];
      if(symbol == "")
         continue;

      if(!SymbolSelect(symbol, true))
      {
         Print("FOREX AUTOPILOT: symbol unavailable in Market Watch: ", symbol);
         continue;
      }

      MqlTick tick;
      if(!SymbolInfoTick(symbol, tick) || tick.bid <= 0 || tick.ask < tick.bid)
         continue;

      if(tick.time_msc == 0 || tick.time_msc <= g_last_quote_time_msc[i])
         continue;

      string body = StringFormat(
         "{\"symbol\":\"%s\",\"bid\":%.10f,\"ask\":%.10f,\"timestamp\":\"%s\"}",
         JsonEscape(symbol), tick.bid, tick.ask, IsoUtcNow()
      );

      // Advance the per-symbol tick marker only after a successful delivery.
      // Failed requests are retried on the next timer cycle.
      if(PostJson("/api/v1/mt5/quote", body))
         g_last_quote_time_msc[i] = tick.time_msc;
   }
}


string TimeframeName(ENUM_TIMEFRAMES timeframe)
{
   switch(timeframe)
   {
      case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15";
      case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";
   }
   return "";
}

// MT5 candle times are broker-server times. Attach the current broker UTC
// offset explicitly so the API can normalize the instant without guessing.
string BrokerTimeIso(datetime broker_time, int utc_offset_seconds)
{
   string stamp = TimeToString(broker_time, TIME_DATE | TIME_SECONDS);
   StringReplace(stamp, ".", "-");
   StringReplace(stamp, " ", "T");

   int absolute_offset = (int)MathAbs(utc_offset_seconds);
   string sign = (utc_offset_seconds >= 0) ? "+" : "-";
   int hours = absolute_offset / 3600;
   int minutes = (absolute_offset % 3600) / 60;
   return StringFormat("%s%s%02d:%02d", stamp, sign, hours, minutes);
}

bool SendCandleBatch(string symbol, ENUM_TIMEFRAMES timeframe, int requested_bars)
{
   int server_offset = (int)(TimeTradeServer() - TimeGMT());
   MqlRates rates[];
   ArraySetAsSeries(rates, false);

   ResetLastError();
   int copied = CopyRates(symbol, timeframe, 1, requested_bars, rates);
   if(copied < 1)
   {
      Print("FOREX AUTOPILOT: candle history not ready for ", symbol,
            " ", TimeframeName(timeframe), "; copied=", copied,
            "; terminal_error=", GetLastError());
      return false;
   }

   if(requested_bars > 3 && copied < requested_bars)
   {
      Print("FOREX AUTOPILOT: waiting for ", requested_bars,
            " historical candles for ", symbol, " ", TimeframeName(timeframe),
            "; currently available=", copied);
      return false;
   }

   string body = StringFormat(
      "{\"symbol\":\"%s\",\"timeframe\":\"%s\",\"candles\":[",
      JsonEscape(symbol), TimeframeName(timeframe)
   );

   for(int i = 0; i < copied; i++)
   {
      if(i > 0)
         body += ",";

      body += StringFormat(
         "{\"opened_at\":\"%s\",\"open\":%.10f,\"high\":%.10f,"
         "\"low\":%.10f,\"close\":%.10f,\"tick_volume\":%I64d}",
         BrokerTimeIso(rates[i].time, server_offset),
         rates[i].open, rates[i].high, rates[i].low, rates[i].close,
         rates[i].tick_volume
      );
   }

   body += "]}";
   return PostJson("/api/v1/mt5/candles", body);
}

// Bootstrap each symbol/timeframe once, then refresh the most recent three
// closed bars. One request is sent every two seconds to avoid network bursts.
void AdvanceCandleCombination(int combinations, ulong now_ms)
{
   g_candle_next_index++;
   if(g_candle_next_index < combinations)
      return;

   g_candle_next_index = 0;
   bool all_bootstrapped = true;
   for(int i = 0; i < combinations; i++)
   {
      if(!g_candle_bootstrap_done[i])
      {
         all_bootstrapped = false;
         break;
      }
   }

   if(all_bootstrapped && !g_candle_bootstrap_complete)
   {
      g_candle_bootstrap_complete = true;
      Print("FOREX AUTOPILOT: initial candle history bootstrap complete for all ",
            combinations, " symbol/timeframe combinations.");
   }

   // Retry incomplete bootstrap combinations soon; normal refreshes use the
   // configured refresh interval after every combination has bootstrapped.
   ulong wait_ms = g_candle_bootstrap_complete
                   ? (ulong)InpCandleRefreshSeconds * 1000
                   : 5000;
   g_candle_cycle_wait_until_ms = now_ms + wait_ms;
}

void SendNextCandleBatch(ulong now_ms)
{
   if(now_ms - g_candle_last_request_ms < 2000)
      return;
   if(g_candle_cycle_wait_until_ms > 0 && now_ms < g_candle_cycle_wait_until_ms)
      return;

   int combinations = ArraySize(g_symbols) * ArraySize(g_candle_timeframes);
   if(combinations < 1)
      return;

   int index = g_candle_next_index;
   int symbol_index = index / ArraySize(g_candle_timeframes);
   int timeframe_index = index % ArraySize(g_candle_timeframes);
   string symbol = g_symbols[symbol_index];
   ENUM_TIMEFRAMES timeframe = g_candle_timeframes[timeframe_index];

   int bars_to_send = g_candle_bootstrap_done[index] ? 3 : InpCandleBootstrapBars;
   Print("FOREX AUTOPILOT: candle scheduler attempting ", symbol, " ",
         TimeframeName(timeframe), "; bars=", bars_to_send,
         "; attempt=", g_candle_attempts[index] + 1, "/", CANDLE_MAX_ATTEMPTS);

   bool accepted = false;
   if(SymbolSelect(symbol, true))
      accepted = SendCandleBatch(symbol, timeframe, bars_to_send);
   else
      Print("FOREX AUTOPILOT: cannot select candle symbol ", symbol,
            "; scheduler will retry.");

   if(accepted)
   {
      Print("FOREX AUTOPILOT: candles accepted for ", symbol, " ",
            TimeframeName(timeframe), "; bars=", bars_to_send);
      g_candle_attempts[index] = 0;
      g_candle_bootstrap_done[index] = true;
      AdvanceCandleCombination(combinations, now_ms);
   }
   else
   {
      g_candle_attempts[index]++;
      if(g_candle_attempts[index] >= CANDLE_MAX_ATTEMPTS)
      {
         Print("FOREX AUTOPILOT: moving past ", symbol, " ",
               TimeframeName(timeframe), " after ", CANDLE_MAX_ATTEMPTS,
               " failed attempts; it will be retried next cycle.");
         g_candle_attempts[index] = 0;
         AdvanceCandleCombination(combinations, now_ms);
      }
   }

   g_candle_last_request_ms = now_ms;
}

int OnInit()
{
   if(StringFind(InpApiBaseUrl, "https://") != 0)
   {
      Print("FOREX AUTOPILOT: configure an HTTPS API base URL before starting.");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(StringLen(Trimmed(InpBridgeToken)) < 32)
   {
      Print("FOREX AUTOPILOT: configure a unique bridge token of at least 32 characters locally.");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(InpHeartbeatSeconds < 5 || InpHttpTimeoutMs < 1000 ||
      InpCandleBootstrapBars < 20 || InpCandleBootstrapBars > 200 ||
      InpCandleRefreshSeconds < 30)
   {
      Print("FOREX AUTOPILOT: invalid timer or HTTP timeout setting.");
      return INIT_PARAMETERS_INCORRECT;
   }

   string configured_symbols[];
   int count = StringSplit(InpSymbols, ',', configured_symbols);
   if(count < 1)
   {
      Print("FOREX AUTOPILOT: configure at least one symbol.");
      return INIT_PARAMETERS_INCORRECT;
   }

   ArrayResize(g_symbols, count);
   ArrayResize(g_last_quote_time_msc, count);
   int candle_combinations = count * ArraySize(g_candle_timeframes);
   ArrayResize(g_candle_attempts, candle_combinations);
   ArrayResize(g_candle_bootstrap_done, candle_combinations);
   ArrayInitialize(g_candle_attempts, 0);
   ArrayInitialize(g_candle_bootstrap_done, false);
   for(int i = 0; i < count; i++)
   {
      g_symbols[i] = Trimmed(configured_symbols[i]);
      g_last_quote_time_msc[i] = 0;
      if(g_symbols[i] == "")
      {
         Print("FOREX AUTOPILOT: empty symbol in InpSymbols.");
         return INIT_PARAMETERS_INCORRECT;
      }
      SymbolSelect(g_symbols[i], true);
   }

   if(!EventSetTimer(1))
   {
      Print("FOREX AUTOPILOT: unable to start the one-second telemetry timer.");
      return INIT_FAILED;
   }

   Print("FOREX AUTOPILOT: read-only telemetry bridge started. Quotes are sampled independently every second when a new tick is available; heartbeat/account updates every ", InpHeartbeatSeconds, " seconds.");

   SendHeartbeat();
   SendAccountSnapshot();
   SendQuotes();
   g_last_snapshot_ms = GetTickCount64();
   g_candle_last_request_ms = GetTickCount64() - 2000;
   Print("FOREX AUTOPILOT: candle collection enabled for M5, M15, H1 and H4. Initial history target: ", InpCandleBootstrapBars, " closed bars per combination.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("FOREX AUTOPILOT: telemetry bridge stopped.");
}

void OnTimer()
{
   ulong now_ms = GetTickCount64();
   ulong snapshot_interval_ms = (ulong)InpHeartbeatSeconds * 1000;

   if(!TerminalInfoInteger(TERMINAL_CONNECTED))
   {
      if(now_ms - g_last_snapshot_ms >= snapshot_interval_ms)
      {
         SendHeartbeat();
         g_last_snapshot_ms = now_ms;
      }
      return;
   }

   SendQuotes();
   SendNextCandleBatch(now_ms);

   if(now_ms - g_last_snapshot_ms >= snapshot_interval_ms)
   {
      SendHeartbeat();
      SendAccountSnapshot();
      g_last_snapshot_ms = now_ms;
   }
}

// Quotes are intentionally timer-driven so both configured symbols are
// sampled independently, regardless of which chart hosts this EA.
void OnTick()
{
   // No action required here.
}
