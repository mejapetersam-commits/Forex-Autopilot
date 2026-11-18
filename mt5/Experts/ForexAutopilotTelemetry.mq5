// FOREX AUTOPILOT - read-only MT5 telemetry bridge
// This Expert Advisor sends connection, account and quote telemetry only.
// It contains NO trade execution, order, position modification or close functions.

#property strict
#property version   "1.01"
#property description "FOREX AUTOPILOT read-only telemetry bridge"

input string InpApiBaseUrl = "https://YOUR-API-HOST";
input string InpBridgeToken = ""; // Set locally in MT5; never commit a real token.
input string InpSymbols = "EURUSD,GBPUSD";
input int    InpHeartbeatSeconds = 15;
input int    InpHttpTimeoutMs = 5000;

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

// Called on incoming chart-symbol ticks so quote updates are not held
// behind the slower heartbeat timer.
void SendQuotes()
{
   string symbols[];
   int count = StringSplit(InpSymbols, ',', symbols);
   for(int i = 0; i < count; i++)
   {
      string symbol = Trimmed(symbols[i]);
      if(symbol == "")
         continue;

      if(!SymbolSelect(symbol, true))
      {
         Print("FOREX AUTOPILOT: symbol unavailable in Market Watch: ", symbol);
         continue;
      }

      MqlTick tick;
      if(!SymbolInfoTick(symbol, tick) || tick.bid <= 0 || tick.ask < tick.bid)
      {
         Print("FOREX AUTOPILOT: no valid current tick for ", symbol);
         continue;
      }

      string body = StringFormat(
         "{\"symbol\":\"%s\",\"bid\":%.10f,\"ask\":%.10f,\"timestamp\":\"%s\"}",
         JsonEscape(symbol), tick.bid, tick.ask, IsoUtcNow()
      );
      PostJson("/api/v1/mt5/quote", body);
   }
}

void SendTelemetry()
{
   if(!TerminalInfoInteger(TERMINAL_CONNECTED))
   {
      Print("FOREX AUTOPILOT: MT5 terminal is not connected; telemetry skipped.");
      SendHeartbeat();
      return;
   }
   SendHeartbeat();
   SendAccountSnapshot();
   SendQuotes();
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

   EventSetTimer(InpHeartbeatSeconds);
   Print("FOREX AUTOPILOT: read-only MT5 telemetry bridge started. Quotes update on incoming chart ticks; heartbeat/account use the timer.");
   SendTelemetry();
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("FOREX AUTOPILOT: telemetry bridge stopped.");
}

void OnTimer()
{
   if(!TerminalInfoInteger(TERMINAL_CONNECTED))
   {
      SendHeartbeat();
      return;
   }
   SendHeartbeat();
   SendAccountSnapshot();
}

void OnTick()
{
   if(TerminalInfoInteger(TERMINAL_CONNECTED))
      SendQuotes();
}
