// FOREX AUTOPILOT - read-only MT5 telemetry bridge
// This Expert Advisor sends connection, account and quote telemetry only.
// It contains NO trade execution, order, position modification or close functions.

#property strict
#property version   "1.02"
#property description "FOREX AUTOPILOT read-only telemetry bridge"

input string InpApiBaseUrl = "https://YOUR-API-HOST";
input string InpBridgeToken = ""; // Set locally in MT5; never commit a real token.
input string InpSymbols = "EURUSD,GBPUSD";
input int    InpHeartbeatSeconds = 15;
input int    InpHttpTimeoutMs = 5000;

string g_symbols[];
ulong  g_last_quote_time_msc[];
ulong  g_last_snapshot_ms = 0;

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
   string headers = "Content-Type: application/json\\r\\nX-Bridge-Token: " + InpBridgeToken + "\\r\\n";
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
   if(InpHeartbeatSeconds < 5 || InpHttpTimeoutMs < 1000)
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
   SendQuotes();
   g_last_snapshot_ms = GetTickCount64();
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
