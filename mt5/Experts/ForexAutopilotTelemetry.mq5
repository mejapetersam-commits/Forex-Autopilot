// FOREX AUTOPILOT - read-only MT5 telemetry bridge
// This Expert Advisor sends connection, account, quote and OHLC candle telemetry only.
// It contains NO trade execution, order, position modification or close functions.

#property strict
#property version   "1.10"
#property description "FOREX AUTOPILOT read-only telemetry bridge"

input string InpApiBaseUrl = "https://YOUR-API-HOST";
input string InpBridgeToken = ""; // Set locally in MT5; never commit a real token.
input string InpSymbols = "EURUSDm,GBPUSDm";
input int    InpHeartbeatSeconds = 15;
input int    InpHttpTimeoutMs = 15000;
input int    InpCandleBootstrapBars = 500;
input int    InpCandleRefreshSeconds = 60;

string g_symbols[];
ulong  g_last_quote_time_msc[];
ulong  g_last_snapshot_ms = 0;
ulong  g_last_specification_ms = 0;

ENUM_TIMEFRAMES g_candle_timeframes[4] = {PERIOD_M5, PERIOD_M15, PERIOD_H1, PERIOD_H4};
int g_candle_next_index = 0;
bool g_candle_bootstrap_complete = false;
ulong g_candle_next_upload_ms = 0;

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
   StringReplace(value, "\", "\\\");
   StringReplace(value, "\"", "\\"");
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

// Send broker-provided symbol contract values. These are read-only metadata;
// tick value is reported by MT5 in the account deposit currency.
void SendSymbolSpecifications()
{
   string account_currency = JsonEscape(AccountInfoString(ACCOUNT_CURRENCY));
   for(int i = 0; i < ArraySize(g_symbols); i++)
   {
      string symbol = g_symbols[i];
      if(symbol == "" || !SymbolSelect(symbol, true))
         continue;

      long digits = SymbolInfoInteger(symbol, SYMBOL_DIGITS);
      long stops_level = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
      long freeze_level = SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);
      long trade_mode = SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE);
      string base_currency = JsonEscape(SymbolInfoString(symbol, SYMBOL_CURRENCY_BASE));
      string profit_currency = JsonEscape(SymbolInfoString(symbol, SYMBOL_CURRENCY_PROFIT));
      string margin_currency = JsonEscape(SymbolInfoString(symbol, SYMBOL_CURRENCY_MARGIN));
      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
      double tick_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
      double tick_value_profit = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_PROFIT);
      double tick_value_loss = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
      double contract_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_CONTRACT_SIZE);
      double volume_min = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      double volume_max = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
      double volume_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
      bool trade_allowed = (
         trade_mode == SYMBOL_TRADE_MODE_FULL ||
         trade_mode == SYMBOL_TRADE_MODE_LONGONLY ||
         trade_mode == SYMBOL_TRADE_MODE_SHORTONLY
      );
      if(point <= 0 || tick_size <= 0 || tick_value_loss <= 0 ||
         contract_size <= 0 || volume_min <= 0 || volume_max < volume_min ||
         volume_step <= 0)
      {
         Print("FOREX AUTOPILOT: broker specifications not ready for ", symbol,
               "; will retry on the next refresh.");
         continue;
      }

      string body = StringFormat(
         "{\\"symbol\\":\\"%s\\",\\"digits\\":%I64d,\\"point\\":%.10f,"
         "\\"tick_size\\":%.10f,\\"tick_value_profit\\":%.10f,"
         "\\"tick_value_loss\\":%.10f,\\"contract_size\\":%.4f,"
         "\\"volume_min\\":%.4f,\\"volume_max\\":%.4f,\\"volume_step\\":%.4f,"
         "\\"stops_level_points\\":%I64d,\\"freeze_level_points\\":%I64d,"
         "\\"trade_allowed\\":%s,\\"base_currency\\":\\"%s\\","
         "\\"profit_currency\\":\\"%s\\",\\"margin_currency\\":\\"%s\\","
         "\\"account_currency\\":\\"%s\\",\\"observed_at\\":\\"%s\\"}",
         JsonEscape(symbol), digits,
         point, tick_size, tick_value_profit, tick_value_loss,
         contract_size, volume_min, volume_max, volume_step,
         stops_level, freeze_level,
         trade_allowed ? "true" : "false",
         base_currency, profit_currency, margin_currency,
         account_currency, IsoUtcNow()
      );
      PostJson("/api/v1/mt5/specifications", body);
   }
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

bool BuildCandleBatchJson(string symbol, ENUM_TIMEFRAMES timeframe,
                           int requested_bars, string &batch_json)
{
   int server_offset = (int)(TimeTradeServer() - TimeGMT());
   MqlRates rates[];
   ArraySetAsSeries(rates, false);

   ResetLastError();
   int copied = CopyRates(symbol, timeframe, 1, requested_bars, rates);
   if(copied != requested_bars)
   {
      Print("FOREX AUTOPILOT: bulk bootstrap waiting for ", symbol, " ",
            TimeframeName(timeframe), "; requested=", requested_bars,
            "; copied=", copied, "; terminal_error=", GetLastError());
      return false;
   }

   batch_json = StringFormat(
      "{\"symbol\":\"%s\",\"timeframe\":\"%s\",\"candles\":[",
      JsonEscape(symbol), TimeframeName(timeframe)
   );

   for(int i = 0; i < copied; i++)
   {
      if(i > 0)
         batch_json += ",";

      batch_json += StringFormat(
         "{\"opened_at\":\"%s\",\"open\":%.10f,\"high\":%.10f,"
         "\"low\":%.10f,\"close\":%.10f,\"tick_volume\":%I64d}",
         BrokerTimeIso(rates[i].time, server_offset),
         rates[i].open, rates[i].high, rates[i].low, rates[i].close,
         rates[i].tick_volume
      );
   }

   batch_json += "]}";
   return true;
}

// One request carries all configured symbol/timeframe groups. Initial upload
// contains 500 closed bars per group; later uploads refresh the latest 3 bars.
void SendBulkCandleBatches(ulong now_ms)
{
   if(now_ms < g_candle_next_upload_ms)
      return;

   int requested_bars = g_candle_bootstrap_complete ? 3 : InpCandleBootstrapBars;
   string body = "{\"batches\":[";
   int batch_count = 0;

   for(int symbol_index = 0; symbol_index < ArraySize(g_symbols); symbol_index++)
   {
      string symbol = g_symbols[symbol_index];
      if(!SymbolSelect(symbol, true))
      {
         Print("FOREX AUTOPILOT: bulk candle upload waiting for symbol ", symbol);
         g_candle_next_upload_ms = now_ms + 10000;
         return;
      }

      for(int timeframe_index = 0;
          timeframe_index < ArraySize(g_candle_timeframes);
          timeframe_index++)
      {
         string batch_json;
         if(!BuildCandleBatchJson(
               symbol, g_candle_timeframes[timeframe_index],
               requested_bars, batch_json))
         {
            // MT5 may still be downloading history. Retry the complete upload
            // shortly; never mark a partial bootstrap as complete.
            g_candle_next_upload_ms = now_ms + 10000;
            return;
         }

         if(batch_count > 0)
            body += ",";
         body += batch_json;
         batch_count++;
      }
   }

   body += "]}";
   Print("FOREX AUTOPILOT: submitting one bulk candle request; groups=",
         batch_count, "; bars_per_group=", requested_bars,
         "; total_candles=", batch_count * requested_bars);

   if(PostJson("/api/v1/mt5/candles/bulk", body))
   {
      if(!g_candle_bootstrap_complete)
      {
         g_candle_bootstrap_complete = true;
         Print("FOREX AUTOPILOT: initial bulk candle bootstrap accepted for ",
               batch_count, " groups and ", batch_count * requested_bars,
               " candles.");
      }
      g_candle_next_upload_ms = now_ms + (ulong)InpCandleRefreshSeconds * 1000;
   }
   else
   {
      Print("FOREX AUTOPILOT: bulk candle upload failed; retrying in 10 seconds.");
      g_candle_next_upload_ms = now_ms + 10000;
   }
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
      InpCandleBootstrapBars < 20 || InpCandleBootstrapBars > 500 ||
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
   SendSymbolSpecifications();
   SendQuotes();
   g_last_snapshot_ms = GetTickCount64();
   g_candle_next_upload_ms = GetTickCount64();
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
   SendBulkCandleBatches(now_ms);

   if(now_ms - g_last_specification_ms >= 300000)
   {
      SendSymbolSpecifications();
      g_last_specification_ms = now_ms;
   }

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
