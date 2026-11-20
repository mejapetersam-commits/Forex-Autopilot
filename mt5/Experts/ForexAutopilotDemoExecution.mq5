// FOREX AUTOPILOT - demo-only MT5 execution adapter.
// Separate from ForexAutopilotTelemetry.mq5, which remains read-only.
// This EA refuses to run unless explicitly enabled AND the logged-in account is DEMO.

#property strict
#property version   "1.101"
#property description "FOREX AUTOPILOT demo-only execution adapter"

#include <Trade/Trade.mqh>

input string InpApiBaseUrl = "https://YOUR-API-HOST";
input string InpBridgeToken = "";          // Set locally; never commit credentials.
input string InpTerminalId = "mt5-terminal-1"; // Match the telemetry EA terminal ID.
input string InpAllowedSymbols = "EURUSDm,GBPUSDm";
input bool   InpEnableDemoExecution = false; // Explicit opt-in; default OFF.
input double InpMaxLotsPerTrade = 0.01;     // Hard local ceiling for initial demo tests.
input int    InpMaxOpenPositions = 1;       // Conservative account-wide position cap.
input int    InpMaxDeviationPoints = 10;
input int    InpPollSeconds = 2;
input int    InpHttpTimeoutMs = 10000;
input ulong  InpMagicNumber = 61119001;

CTrade g_trade;
string g_allowed_symbols[];

string TrimValue(string value)
{
   StringTrimLeft(value);
   StringTrimRight(value);
   return value;
}

bool IsDemoAccount()
{
   return AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO;
}

bool IsTradingPermitted()
{
   return IsDemoAccount()
      && (bool)AccountInfoInteger(ACCOUNT_TRADE_ALLOWED)
      && (bool)TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)
      && (bool)MQLInfoInteger(MQL_TRADE_ALLOWED)
      && (bool)TerminalInfoInteger(TERMINAL_CONNECTED);
}

bool IsAllowedSymbol(string symbol)
{
   string normalized = symbol;
   StringToUpper(normalized);
   for(int i = 0; i < ArraySize(g_allowed_symbols); i++)
   {
      string allowed = g_allowed_symbols[i];
      StringToUpper(allowed);
      if(normalized == allowed)
         return true;
   }
   return false;
}

string JsonString(string json, string key)
{
   string needle = "\"" + key + "\":";
   int position = StringFind(json, needle);
   if(position < 0)
      return "";
   position += StringLen(needle);
   while(position < StringLen(json) && StringGetCharacter(json, position) == ' ')
      position++;
   if(position >= StringLen(json) || StringGetCharacter(json, position) != '"')
      return "";
   int start = position + 1;
   int finish = StringFind(json, "\"", start);
   if(finish < 0)
      return "";
   return StringSubstr(json, start, finish - start);
}

double JsonNumber(string json, string key, bool &found)
{
   string needle = "\"" + key + "\":";
   int position = StringFind(json, needle);
   found = false;
   if(position < 0)
      return 0.0;
   position += StringLen(needle);
   while(position < StringLen(json) && StringGetCharacter(json, position) == ' ')
      position++;
   int finish = position;
   while(finish < StringLen(json))
   {
      ushort ch = StringGetCharacter(json, finish);
      if(ch == ',' || ch == '}' || ch == ' ' || ch == '\r' || ch == '\n')
         break;
      finish++;
   }
   if(finish <= position)
      return 0.0;
   found = true;
   return StringToDouble(StringSubstr(json, position, finish - position));
}

bool HttpGet(string route, string &response)
{
   string url = InpApiBaseUrl + route;
   string headers = "X-Bridge-Token: " + InpBridgeToken + "\r\n";
   char data[];
   char result[];
   string response_headers;
   ResetLastError();
   int status = WebRequest("GET", url, headers, InpHttpTimeoutMs,
                           data, result, response_headers);
   int terminal_error = GetLastError();
   response = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   if(status < 200 || status >= 300)
   {
      if(status == -1)
         Print("FOREX AUTOPILOT EXECUTION: command poll transport error ", terminal_error);
      else
         Print("FOREX AUTOPILOT EXECUTION: command poll HTTP ", status,
               "; response=", response);
      return false;
   }
   return true;
}

bool HttpPostJson(string route, string body)
{
   string url = InpApiBaseUrl + route;
   string headers = "Content-Type: application/json\r\nX-Bridge-Token: " + InpBridgeToken + "\r\n";
   char data[];
   char result[];
   string response_headers;
   int copied = StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(copied <= 1)
      return false;
   ArrayResize(data, copied - 1);
   ResetLastError();
   int status = WebRequest("POST", url, headers, InpHttpTimeoutMs,
                           data, result, response_headers);
   string response = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   if(status < 200 || status >= 300)
   {
      Print("FOREX AUTOPILOT EXECUTION: result callback failed; HTTP=", status,
            "; terminal_error=", GetLastError(), "; response=", response);
      return false;
   }
   return true;
}

bool WasAttempted(string command_id)
{
   // The complete deterministic command ID fits MT5's 63-character global
   // variable limit; do not rely on a collision-prone 32-bit hash.
   if(command_id == "" || StringLen(command_id) > 48)
      return true;
   return GlobalVariableCheck("FA.Attempt." + command_id);
}

bool MarkAttempted(string command_id)
{
   if(command_id == "" || StringLen(command_id) > 48)
      return false;

   string key = "FA.Attempt." + command_id;
   ResetLastError();
   datetime stored = GlobalVariableSet(key, (double)TimeLocal());
   if(stored == 0 || !GlobalVariableCheck(key))
   {
      Print("FOREX AUTOPILOT EXECUTION: cannot persist attempt marker; refusing order. command=",
            command_id, " error=", GetLastError());
      return false;
   }
   GlobalVariablesFlush();
   return true;
}

int CountOpenPositions()
{
   return PositionsTotal();
}

bool ValidVolume(string symbol, double volume)
{
   double minimum = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double maximum = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(minimum <= 0 || maximum < minimum || step <= 0)
      return false;
   if(volume < minimum || volume > maximum || volume > InpMaxLotsPerTrade)
      return false;
   double steps = (volume - minimum) / step;
   return MathAbs(steps - MathRound(steps)) < 0.000001;
}

bool CheckBrokerOrder(string symbol, string side, double volume,
                      double stop_loss, double take_profit,
                      string broker_tag, string &reason)
{
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick) || tick.bid <= 0 || tick.ask < tick.bid)
   {
      reason = "order_check_no_valid_quote";
      return false;
   }

   if(!g_trade.SetTypeFillingBySymbol(symbol))
   {
      reason = "broker_filling_policy_unavailable";
      return false;
   }

   long filling_mode = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
   long execution_mode = SymbolInfoInteger(symbol, SYMBOL_TRADE_EXEMODE);
   ENUM_ORDER_TYPE_FILLING filling;
   if((filling_mode & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
      filling = ORDER_FILLING_FOK;
   else if((filling_mode & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
      filling = ORDER_FILLING_IOC;
   else if(execution_mode != SYMBOL_TRADE_EXECUTION_MARKET)
      filling = ORDER_FILLING_RETURN;
   else
   {
      reason = "broker_has_no_supported_market_filling_policy";
      return false;
   }

   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   MqlTradeRequest request = {};
   request.action = TRADE_ACTION_DEAL;
   request.symbol = symbol;
   request.volume = volume;
   request.type = (side == "buy") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   request.price = (side == "buy") ? tick.ask : tick.bid;
   request.sl = NormalizeDouble(stop_loss, digits);
   request.tp = NormalizeDouble(take_profit, digits);
   request.deviation = InpMaxDeviationPoints;
   request.magic = InpMagicNumber;
   request.type_filling = filling;
   request.type_time = ORDER_TIME_GTC;
   request.comment = "FA:" + broker_tag;

   MqlTradeCheckResult check = {};
   ResetLastError();
   bool checked = OrderCheck(request, check);
   if(!checked || (check.retcode != 0 && check.retcode != TRADE_RETCODE_DONE))
   {
      reason = "broker_order_check_failed_retcode_" + IntegerToString((int)check.retcode);
      Print("FOREX AUTOPILOT EXECUTION: OrderCheck failed; retcode=", check.retcode,
            " comment=", check.comment, " terminal_error=", GetLastError());
      return false;
   }
   return true;
}

bool ValidateOrder(string symbol, string side, double volume,
                   double stop_loss, double take_profit, string &reason)
{
   if(!IsTradingPermitted())
   {
      reason = "demo_account_or_terminal_trade_permission_check_failed";
      return false;
   }
   if(!IsAllowedSymbol(symbol))
   {
      reason = "symbol_not_in_local_allowlist";
      return false;
   }
   if(CountOpenPositions() >= InpMaxOpenPositions)
   {
      reason = "maximum_open_positions_reached";
      return false;
   }
   if(!SymbolSelect(symbol, true))
   {
      reason = "symbol_unavailable";
      return false;
   }
   long trade_mode = SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE);
   if(trade_mode != SYMBOL_TRADE_MODE_FULL
      && !(side == "buy" && trade_mode == SYMBOL_TRADE_MODE_LONGONLY)
      && !(side == "sell" && trade_mode == SYMBOL_TRADE_MODE_SHORTONLY))
   {
      reason = "broker_symbol_trade_mode_disallows_side";
      return false;
   }
   if(!ValidVolume(symbol, volume))
   {
      reason = "volume_outside_broker_or_local_limits";
      return false;
   }

   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick) || tick.bid <= 0 || tick.ask < tick.bid)
   {
      reason = "no_valid_current_quote";
      return false;
   }

   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   long stops_level = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double min_distance = MathMax((double)stops_level * point, 2.0 * point);
   stop_loss = NormalizeDouble(stop_loss, digits);
   take_profit = NormalizeDouble(take_profit, digits);

   if(side == "buy")
   {
      if(stop_loss >= tick.bid - min_distance || take_profit <= tick.ask + min_distance)
      {
         reason = "buy_stop_or_target_wrong_side_or_inside_broker_minimum";
         return false;
      }
   }
   else if(side == "sell")
   {
      if(stop_loss <= tick.ask + min_distance || take_profit >= tick.bid - min_distance)
      {
         reason = "sell_stop_or_target_wrong_side_or_inside_broker_minimum";
         return false;
      }
   }
   else
   {
      reason = "unsupported_order_side";
      return false;
   }

   double margin = 0.0;
   ENUM_ORDER_TYPE order_type = (side == "buy") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double requested_price = (side == "buy") ? tick.ask : tick.bid;
   if(!OrderCalcMargin(order_type, symbol, volume, requested_price, margin))
   {
      reason = "broker_margin_calculation_failed";
      return false;
   }
   if(margin <= 0 || AccountInfoDouble(ACCOUNT_MARGIN_FREE) < margin * 1.20)
   {
      reason = "insufficient_free_margin_buffer";
      return false;
   }
   return true;
}

void SendResult(string command_id, string outcome, string result_json)
{
   string route = "/api/v1/mt5/execution/commands/" + command_id + "/result";
   string body = "{\"terminal_id\":\"" + InpTerminalId
      + "\",\"outcome\":\"" + outcome + "\",\"result\":" + result_json + "}";
   if(!HttpPostJson(route, body))
      Print("FOREX AUTOPILOT EXECUTION: command result must be reconciled; command=", command_id);
}

void ProcessCommand(string response)
{
   if(StringFind(response, "\"command\":null") >= 0)
      return;

   string command_id = JsonString(response, "command_id");
   string intent_id = JsonString(response, "intent_id");
   string broker_tag = JsonString(response, "broker_tag");
   string symbol = JsonString(response, "symbol");
   string side = JsonString(response, "side");
   bool volume_found = false, sl_found = false, tp_found = false;
   double volume = JsonNumber(response, "volume_lots", volume_found);
   double stop_loss = JsonNumber(response, "stop_loss", sl_found);
   double take_profit = JsonNumber(response, "take_profit", tp_found);

   if(command_id == "" || intent_id == "" || broker_tag == "" || symbol == "" || side == ""
      || !volume_found || !sl_found || !tp_found)
   {
      Print("FOREX AUTOPILOT EXECUTION: malformed command; no order attempted.");
      return;
   }
   if(WasAttempted(command_id))
   {
      Print("FOREX AUTOPILOT EXECUTION: duplicate command suppressed locally: ", command_id);
      return;
   }

   string reason = "";
   if(!ValidateOrder(symbol, side, volume, stop_loss, take_profit, reason))
   {
      if(!MarkAttempted(command_id))
         return;
      string result = "{\"reason\":\"" + reason + "\",\"intent_id\":\"" + intent_id + "\"}";
      SendResult(command_id, "rejected", result);
      Print("FOREX AUTOPILOT EXECUTION: order rejected by local safety validation: ", reason);
      return;
   }

   int symbol_digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   stop_loss = NormalizeDouble(stop_loss, symbol_digits);
   take_profit = NormalizeDouble(take_profit, symbol_digits);

   if(!CheckBrokerOrder(symbol, side, volume, stop_loss, take_profit, broker_tag, reason))
   {
      if(!MarkAttempted(command_id))
         return;
      string result = "{\"reason\":\"" + reason + "\",\"intent_id\":\"" + intent_id + "\"}";
      SendResult(command_id, "rejected", result);
      Print("FOREX AUTOPILOT EXECUTION: broker pre-trade check rejected order: ", reason);
      return;
   }

   // Persist the attempt marker BEFORE calling the broker. A crash or uncertain
   // network result must be reconciled, never blindly retried.
   if(!MarkAttempted(command_id))
      return;
   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(InpMaxDeviationPoints);
   g_trade.SetAsyncMode(false);

   bool sent = false;
   if(side == "buy")
      sent = g_trade.Buy(volume, symbol, 0.0, stop_loss, take_profit, "FA:" + broker_tag);
   else
      sent = g_trade.Sell(volume, symbol, 0.0, stop_loss, take_profit, "FA:" + broker_tag);

   uint retcode = g_trade.ResultRetcode();
   ulong order_ticket = g_trade.ResultOrder();
   ulong deal_ticket = g_trade.ResultDeal();
   double filled_volume = g_trade.ResultVolume();
   double fill_price = g_trade.ResultPrice();
   string broker_comment = g_trade.ResultComment();
   string outcome = "unknown";

   if(sent && (retcode == TRADE_RETCODE_DONE
      || retcode == TRADE_RETCODE_PLACED
      || retcode == TRADE_RETCODE_DONE_PARTIAL))
      outcome = "acknowledged";
   else if(retcode == TRADE_RETCODE_REJECT
      || retcode == TRADE_RETCODE_INVALID
      || retcode == TRADE_RETCODE_INVALID_VOLUME
      || retcode == TRADE_RETCODE_INVALID_PRICE
      || retcode == TRADE_RETCODE_INVALID_STOPS
      || retcode == TRADE_RETCODE_TRADE_DISABLED
      || retcode == TRADE_RETCODE_MARKET_CLOSED
      || retcode == TRADE_RETCODE_NO_MONEY)
      outcome = "rejected";

   string safe_comment = broker_comment;
   // Broker comments are external text. Escape JSON delimiters and replace
   // control characters so a valid trade result cannot become invalid JSON.
   StringReplace(safe_comment, "\\", "\\\\");
   StringReplace(safe_comment, "\"", "\\\"");
   StringReplace(safe_comment, ShortToString(13), " ");
   StringReplace(safe_comment, ShortToString(10), " ");
   StringReplace(safe_comment, ShortToString(9), " ");
   string execution_state = "unknown";
   if(retcode == TRADE_RETCODE_DONE)
      execution_state = "filled";
   else if(retcode == TRADE_RETCODE_DONE_PARTIAL)
      execution_state = "partially_filled";
   else if(retcode == TRADE_RETCODE_PLACED)
      execution_state = "accepted_pending";

   string result = StringFormat(
      "{\"intent_id\":\"%s\",\"broker_order_id\":\"%I64u\","
      "\"broker_deal_id\":\"%I64u\",\"retcode\":%u,"
      "\"execution_state\":\"%s\",\"filled_volume\":%.4f,"
      "\"fill_price\":%.10f,\"comment\":\"%s\"}",
      intent_id, order_ticket, deal_ticket, retcode,
      execution_state, filled_volume, fill_price, safe_comment
   );
   SendResult(command_id, outcome, result);
   Print("FOREX AUTOPILOT EXECUTION: command ", command_id,
         " outcome=", outcome, " retcode=", retcode,
         " order=", order_ticket, " deal=", deal_ticket);
}

void PollCommands()
{
   if(!InpEnableDemoExecution || !IsTradingPermitted())
      return;

   string route = "/api/v1/mt5/execution/commands/next?terminal_id=" + InpTerminalId;
   string response = "";
   if(!HttpGet(route, response))
      return;
   ProcessCommand(response);
}

int OnInit()
{
   if(!InpEnableDemoExecution)
   {
      Print("FOREX AUTOPILOT EXECUTION: adapter attached in SAFE DISABLED mode. No command polling or orders. Enable only on a DEMO terminal after backend configuration.");
      return INIT_SUCCEEDED;
   }
   string terminal_id_check = TrimValue(InpTerminalId);
   bool terminal_id_safe = (StringLen(terminal_id_check) >= 3);
   for(int id_char = 0; id_char < StringLen(terminal_id_check); id_char++)
   {
      ushort ch = StringGetCharacter(terminal_id_check, id_char);
      if(!((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z')
         || (ch >= '0' && ch <= '9') || ch == '-' || ch == '_'))
         terminal_id_safe = false;
   }
   if(StringFind(InpApiBaseUrl, "https://") != 0
      || StringLen(TrimValue(InpBridgeToken)) < 32
      || !terminal_id_safe
      || InpMaxLotsPerTrade <= 0 || InpMaxLotsPerTrade > 0.01
      || InpMaxOpenPositions < 1 || InpMaxOpenPositions > 1
      || InpPollSeconds < 1 || InpPollSeconds > 10
      || InpHttpTimeoutMs < 1000)
   {
      Print("FOREX AUTOPILOT EXECUTION: invalid configuration; refusing to start.");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(!IsDemoAccount())
   {
      Print("FOREX AUTOPILOT EXECUTION: REFUSING NON-DEMO ACCOUNT. No orders can be sent.");
      return INIT_FAILED;
   }

   string configured[];
   int count = StringSplit(InpAllowedSymbols, ',', configured);
   if(count < 1)
      return INIT_PARAMETERS_INCORRECT;
   ArrayResize(g_allowed_symbols, count);
   for(int i = 0; i < count; i++)
   {
      g_allowed_symbols[i] = TrimValue(configured[i]);
      if(g_allowed_symbols[i] == "")
         return INIT_PARAMETERS_INCORRECT;
   }

   if(!EventSetTimer(InpPollSeconds))
      return INIT_FAILED;
   Print("FOREX AUTOPILOT EXECUTION: DEMO adapter started. Hard local cap=0.01 lots; max positions=1; live accounts are rejected.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("FOREX AUTOPILOT EXECUTION: adapter stopped.");
}

void OnTimer()
{
   PollCommands();
}

void OnTick()
{
   // All command handling is timer-driven; no chart tick can bypass the gates.
}
