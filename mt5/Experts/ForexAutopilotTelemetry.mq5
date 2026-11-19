// FOREX AUTOPILOT - read-only MT5 telemetry bridge
// This Expert Advisor sends read-only connection, market, position and demo deal-history telemetry.
// It contains NO trade execution, order, position modification or close functions.

#property strict
#property version   "1.11"
#property description "FOREX AUTOPILOT read-only telemetry bridge"

input string InpApiBaseUrl = "https://YOUR-API-HOST";
input string InpBridgeToken = ""; // Set locally in MT5; never commit a real token.
input string InpSymbols = "EURUSDm,GBPUSDm";
input string InpTerminalId = "mt5-terminal-1";
input int    InpExecutionStateSeconds = 5;
input int    InpHeartbeatSeconds = 15;
input int    InpHttpTimeoutMs = 15000;
input int    InpCandleBootstrapBars = 500;
input int    InpCandleRefreshSeconds = 60;
input int    InpHistoryRefreshSeconds = 60;
input int    InpHistoryLookbackDays = 2;
input ulong  InpExecutionMagicNumber = 61119001;

string g_symbols[];
ulong  g_last_quote_time_msc[];
ulong  g_last_snapshot_ms = 0;
ulong  g_last_specification_ms = 0;
ulong  g_last_execution_state_ms = 0;
ulong  g_last_history_ms = 0;

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
         "{\"symbol\":\"%s\",\"digits\":%I64d,\"point\":%.10f,"
         "\"tick_size\":%.10f,\"tick_value_profit\":%.10f,"
         "\"tick_value_loss\":%.10f,\"contract_size\":%.4f,"
         "\"volume_min\":%.4f,\"volume_max\":%.4f,\"volume_step\":%.4f,"
         "\"stops_level_points\":%I64d,\"freeze_level_points\":%I64d,"
         "\"trade_allowed\":%s,\"base_currency\":\"%s\","
         "\"profit_currency\":\"%s\",\"margin_currency\":\"%s\","
         "\"account_currency\":\"%s\",\"observed_at\":\"%s\"}",
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



double CalculateDailyLossPct()
{
   datetime server_now = TimeTradeServer();
   MqlDateTime day_parts;
   TimeToStruct(server_now, day_parts);
   day_parts.hour = 0;
   day_parts.min = 0;
   day_parts.sec = 0;
   datetime day_start = StructToTime(day_parts);

   double realized_net = 0.0;
   if(!HistorySelect(day_start, server_now))
   {
      Print("FOREX AUTOPILOT: unable to read today's broker deal history; daily-loss gate will fail closed.");
      return 1000.0;
   }
   int deals = HistoryDealsTotal();
   for(int i = 0; i < deals; i++)
   {
      ulong deal_ticket = HistoryDealGetTicket(i);
      if(deal_ticket == 0)
         continue;
      long deal_type = HistoryDealGetInteger(deal_ticket, DEAL_TYPE);
      // Use deal types supported across MT5 terminal builds.
      if(deal_type == DEAL_TYPE_BALANCE || deal_type == DEAL_TYPE_CREDIT
         || deal_type == DEAL_TYPE_BONUS || deal_type == DEAL_TYPE_CORRECTION
         || deal_type == DEAL_TYPE_INTEREST)
      {
         Print("FOREX AUTOPILOT: non-trading balance operation detected today; daily-loss gate will fail closed.");
         return 1000.0;
      }
      bool trade_deal = (deal_type == DEAL_TYPE_BUY || deal_type == DEAL_TYPE_SELL);
      bool commission_deal = (
         deal_type == DEAL_TYPE_COMMISSION
         || deal_type == DEAL_TYPE_COMMISSION_DAILY
         || deal_type == DEAL_TYPE_COMMISSION_MONTHLY
         || deal_type == DEAL_TYPE_COMMISSION_AGENT_DAILY
         || deal_type == DEAL_TYPE_COMMISSION_AGENT_MONTHLY
         || deal_type == DEAL_TYPE_CHARGE
      );
      if(!trade_deal && !commission_deal)
         continue;
      realized_net += HistoryDealGetDouble(deal_ticket, DEAL_PROFIT);
      realized_net += HistoryDealGetDouble(deal_ticket, DEAL_COMMISSION);
      realized_net += HistoryDealGetDouble(deal_ticket, DEAL_SWAP);
      realized_net += HistoryDealGetDouble(deal_ticket, DEAL_FEE);
   }

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double floating_net = equity - AccountInfoDouble(ACCOUNT_BALANCE);
   double total_day_net = realized_net + floating_net;
   double estimated_start_equity = equity - total_day_net;
   if(estimated_start_equity <= 0.0)
      return 1000.0;
   return (total_day_net < 0.0)
      ? (-total_day_net / estimated_start_equity) * 100.0
      : 0.0;
}

string AccountEnvironment()
{
   long mode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(mode == ACCOUNT_TRADE_MODE_DEMO)
      return "demo";
   if(mode == ACCOUNT_TRADE_MODE_REAL)
      return "real";
   return "contest";
}

// Read-only snapshot of open positions. No trade or position-modification calls.
void SendExecutionState()
{
   string server = JsonEscape(AccountInfoString(ACCOUNT_SERVER));
   string body = StringFormat(
      "{\"terminal_id\":\"%s\",\"environment\":\"%s\","
      "\"server\":\"%s\",\"observed_at\":\"%s\",\"daily_loss_pct\":%.6f,\"positions\":[",
      JsonEscape(InpTerminalId), AccountEnvironment(), server, IsoUtcNow(), CalculateDailyLossPct()
   );
   int count = 0;
   for(int i = 0; i < PositionsTotal(); i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      string symbol = JsonEscape(PositionGetString(POSITION_SYMBOL));
      string side = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "buy" : "sell";
      string comment = JsonEscape(PositionGetString(POSITION_COMMENT));
      double volume = PositionGetDouble(POSITION_VOLUME);
      double open_price = PositionGetDouble(POSITION_PRICE_OPEN);
      double stop_loss = PositionGetDouble(POSITION_SL);
      double take_profit = PositionGetDouble(POSITION_TP);
      ulong magic = (ulong)PositionGetInteger(POSITION_MAGIC);
      if(count > 0)
         body += ",";
      body += StringFormat(
         "{\"ticket\":\"%I64u\",\"symbol\":\"%s\",\"side\":\"%s\","
         "\"volume_lots\":%.4f,\"open_price\":%.10f,\"stop_loss\":%.10f,"
         "\"take_profit\":%.10f,\"magic\":%I64u,\"comment\":\"%s\"}",
         ticket, symbol, side, volume, open_price, stop_loss, take_profit, magic, comment
      );
      count++;
   }
   body += "]}";
   PostJson("/api/v1/mt5/execution/state", body);
}

string BrokerTimeIso(datetime broker_time, int utc_offset_seconds); // forward declaration

// Read-only demo deal-history upload. This reports broker records only;
// it never submits, changes, or closes an order.
void SendExecutionHistory()
{
   if(AccountEnvironment() != "demo")
      return;

   datetime server_now = TimeTradeServer();
   datetime history_start = server_now - (datetime)(InpHistoryLookbackDays * 86400);
   if(!HistorySelect(history_start, server_now))
   {
      Print("FOREX AUTOPILOT: broker execution history unavailable; reconciliation remains pending.");
      return;
   }

   int total = HistoryDealsTotal();
   int server_offset = (int)(TimeTradeServer() - TimeGMT());
   string body = StringFormat(
      "{\"terminal_id\":\"%s\",\"environment\":\"demo\","
      "\"server\":\"%s\",\"history_from\":\"%s\","
      "\"history_to\":\"%s\",\"observed_at\":\"%s\",\"deals\":[",
      JsonEscape(InpTerminalId), JsonEscape(AccountInfoString(ACCOUNT_SERVER)),
      BrokerTimeIso(history_start, server_offset),
      BrokerTimeIso(server_now, server_offset), IsoUtcNow()
   );

   int included = 0;
   for(int i = 0; i < total; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0 || (ulong)HistoryDealGetInteger(ticket, DEAL_MAGIC) != InpExecutionMagicNumber)
         continue;

      long deal_type = HistoryDealGetInteger(ticket, DEAL_TYPE);
      if(deal_type != DEAL_TYPE_BUY && deal_type != DEAL_TYPE_SELL)
         continue;

      long entry_type = HistoryDealGetInteger(ticket, DEAL_ENTRY);
      string entry = "";
      if(entry_type == DEAL_ENTRY_IN) entry = "in";
      else if(entry_type == DEAL_ENTRY_OUT) entry = "out";
      else if(entry_type == DEAL_ENTRY_INOUT) entry = "inout";
      else if(entry_type == DEAL_ENTRY_OUT_BY) entry = "out_by";
      else continue;

      ulong order_ticket = (ulong)HistoryDealGetInteger(ticket, DEAL_ORDER);
      double volume = HistoryDealGetDouble(ticket, DEAL_VOLUME);
      double price = HistoryDealGetDouble(ticket, DEAL_PRICE);
      datetime deal_time = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
      string symbol = JsonEscape(HistoryDealGetString(ticket, DEAL_SYMBOL));
      string comment = JsonEscape(HistoryDealGetString(ticket, DEAL_COMMENT));
      string side = (deal_type == DEAL_TYPE_BUY) ? "buy" : "sell";
      if(order_ticket == 0 || volume <= 0 || price <= 0 || deal_time <= 0 || symbol == "")
         continue;
      if(included >= 1000)
      {
         Print("FOREX AUTOPILOT: managed execution history exceeds the 1000-deal safety batch; upload skipped.");
         return;
      }

      if(included > 0)
         body += ",";
      body += StringFormat(
         "{\"deal_ticket\":\"%I64u\",\"order_ticket\":\"%I64u\","
         "\"symbol\":\"%s\",\"side\":\"%s\",\"entry\":\"%s\","
         "\"volume_lots\":%.4f,\"price\":%.10f,\"magic\":%I64u,"
         "\"comment\":\"%s\",\"occurred_at\":\"%s\"}",
         ticket, order_ticket, symbol, side, entry, volume, price,
         InpExecutionMagicNumber, comment, BrokerTimeIso(deal_time, server_offset)
      );
      included++;
   }

   body += "]}";
   if(PostJson("/api/v1/mt5/execution/history", body))
      Print("FOREX AUTOPILOT: demo broker history accepted; matching deals=", included);
}

// Read-only broker order-history snapshot; this function never sends or edits orders.
string BrokerOrderType(long value)
{
   switch(value)
   {
      case ORDER_TYPE_BUY: return "buy";
      case ORDER_TYPE_SELL: return "sell";
      case ORDER_TYPE_BUY_LIMIT: return "buy_limit";
      case ORDER_TYPE_SELL_LIMIT: return "sell_limit";
      case ORDER_TYPE_BUY_STOP: return "buy_stop";
      case ORDER_TYPE_SELL_STOP: return "sell_stop";
      case ORDER_TYPE_BUY_STOP_LIMIT: return "buy_stop_limit";
      case ORDER_TYPE_SELL_STOP_LIMIT: return "sell_stop_limit";
   }
   return "";
}

string BrokerOrderState(long value)
{
   switch(value)
   {
      case ORDER_STATE_STARTED: return "started";
      case ORDER_STATE_PLACED: return "placed";
      case ORDER_STATE_CANCELED: return "canceled";
      case ORDER_STATE_PARTIAL: return "partial";
      case ORDER_STATE_FILLED: return "filled";
      case ORDER_STATE_REJECTED: return "rejected";
      case ORDER_STATE_EXPIRED: return "expired";
      case ORDER_STATE_REQUEST_ADD: return "request_add";
      case ORDER_STATE_REQUEST_MODIFY: return "request_modify";
      case ORDER_STATE_REQUEST_CANCEL: return "request_cancel";
   }
   return "";
}

void SendExecutionOrderHistory()
{
   if(AccountEnvironment() != "demo")
      return;
   datetime server_now = TimeTradeServer();
   datetime history_start = server_now - (datetime)(InpHistoryLookbackDays * 86400);
   if(!HistorySelect(history_start, server_now))
   {
      Print("FOREX AUTOPILOT: broker order history unavailable; order reconciliation remains pending.");
      return;
   }

   int total = HistoryOrdersTotal();
   int server_offset = (int)(TimeTradeServer() - TimeGMT());
   string body = StringFormat(
      "{\"terminal_id\":\"%s\",\"environment\":\"demo\","
      "\"server\":\"%s\",\"history_from\":\"%s\","
      "\"history_to\":\"%s\",\"observed_at\":\"%s\",\"orders\":[",
      JsonEscape(InpTerminalId), JsonEscape(AccountInfoString(ACCOUNT_SERVER)),
      BrokerTimeIso(history_start, server_offset),
      BrokerTimeIso(server_now, server_offset), IsoUtcNow()
   );
   int included = 0;
   for(int i = 0; i < total; i++)
   {
      ulong ticket = HistoryOrderGetTicket(i);
      if(ticket == 0 || (ulong)HistoryOrderGetInteger(ticket, ORDER_MAGIC) != InpExecutionMagicNumber)
         continue;
      string order_type = BrokerOrderType(HistoryOrderGetInteger(ticket, ORDER_TYPE));
      string state = BrokerOrderState(HistoryOrderGetInteger(ticket, ORDER_STATE));
      string symbol = JsonEscape(HistoryOrderGetString(ticket, ORDER_SYMBOL));
      string comment = JsonEscape(HistoryOrderGetString(ticket, ORDER_COMMENT));
      double initial_volume = HistoryOrderGetDouble(ticket, ORDER_VOLUME_INITIAL);
      double current_volume = HistoryOrderGetDouble(ticket, ORDER_VOLUME_CURRENT);
      double price = HistoryOrderGetDouble(ticket, ORDER_PRICE_OPEN);
      double stop_loss = HistoryOrderGetDouble(ticket, ORDER_SL);
      double take_profit = HistoryOrderGetDouble(ticket, ORDER_TP);
      datetime setup_at = (datetime)HistoryOrderGetInteger(ticket, ORDER_TIME_SETUP);
      datetime done_at = (datetime)HistoryOrderGetInteger(ticket, ORDER_TIME_DONE);
      if(order_type == "" || state == "" || symbol == "" || initial_volume <= 0 || setup_at <= 0)
         continue;
      if(included >= 1000)
      {
         Print("FOREX AUTOPILOT: managed order history exceeds the 1000-order safety batch; upload skipped.");
         return;
      }
      if(included > 0)
         body += ",";
      string done_stamp = (done_at > 0) ? BrokerTimeIso(done_at, server_offset) : "";
      body += StringFormat(
         "{\"order_ticket\":\"%I64u\",\"symbol\":\"%s\","
         "\"order_type\":\"%s\",\"state\":\"%s\","
         "\"initial_volume\":%.4f,\"current_volume\":%.4f,"
         "\"price\":%.10f,\"stop_loss\":%.10f,\"take_profit\":%.10f,"
         "\"magic\":%I64u,\"comment\":\"%s\","
         "\"setup_at\":\"%s\",\"done_at\":%s}",
         ticket, symbol, order_type, state, initial_volume, current_volume,
         price, stop_loss, take_profit, InpExecutionMagicNumber, comment,
         BrokerTimeIso(setup_at, server_offset),
         (done_at > 0) ? StringFormat("\"%s\"", done_stamp) : "null"
      );
      included++;
   }
   body += "]}";
   if(PostJson("/api/v1/mt5/execution/orders", body))
      Print("FOREX AUTOPILOT: demo broker order history accepted; matching orders=", included);
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

      ulong tick_time_msc = (ulong)tick.time_msc;
      if(tick_time_msc == (ulong)0 || tick_time_msc <= g_last_quote_time_msc[i])
         continue;

      string body = StringFormat(
         "{\"symbol\":\"%s\",\"bid\":%.10f,\"ask\":%.10f,\"timestamp\":\"%s\"}",
         JsonEscape(symbol), tick.bid, tick.ask, IsoUtcNow()
      );

      // Advance the per-symbol tick marker only after a successful delivery.
      // Failed requests are retried on the next timer cycle.
      if(PostJson("/api/v1/mt5/quote", body))
         g_last_quote_time_msc[i] = tick_time_msc;
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
      InpCandleRefreshSeconds < 30 || InpExecutionStateSeconds < 5 || InpExecutionStateSeconds > 60 || InpHistoryRefreshSeconds < 30 || InpHistoryRefreshSeconds > 3600 || InpHistoryLookbackDays < 1 || InpHistoryLookbackDays > 7 || StringLen(Trimmed(InpTerminalId)) < 3)
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
   SendExecutionState();
   SendExecutionHistory();
   SendExecutionOrderHistory();
   SendQuotes();
   g_last_history_ms = GetTickCount64();
   g_last_snapshot_ms = GetTickCount64();
   g_last_execution_state_ms = GetTickCount64();
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

   if(now_ms - g_last_history_ms >= (ulong)InpHistoryRefreshSeconds * 1000)
   {
      SendExecutionHistory();
      SendExecutionOrderHistory();
      g_last_history_ms = now_ms;
   }

   if(now_ms - g_last_execution_state_ms >= (ulong)InpExecutionStateSeconds * 1000)
   {
      SendExecutionState();
      g_last_execution_state_ms = now_ms;
   }

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
