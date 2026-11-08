//+------------------------------------------------------------------+
//|                                     duc_tri_telegram_bridge.mq5  |
//|                                Copyright 2026, Đức Trí Trading   |
//|               Companion EA - Telegram Notification Gateway       |
//|                     100% Pure MQL5 - Hoàn toàn KHÔNG dùng DLL    |
//+------------------------------------------------------------------+
#property copyright   "Đức Trí"
#property link        "https://t.me/botfather6868"
#property version     "3.10"
#property description "Đức Trí Telegram Bridge EA v3.1 - Cổng chuyển tiếp tín hiệu SMC sang Telegram (Pure MQL5 WebRequest)"

//+------------------------------------------------------------------+
//| Input Parameters                                                 |
//+------------------------------------------------------------------+
input group "=== 1. CẤU HÌNH TELEGRAM BOT ==="
input string          InpTgToken         = "";          // Telegram Bot Token (từ @BotFather)
input string          InpTgChatID        = "";          // Telegram Chat ID (từ @userinfobot)
input bool            InpSendTestOnStart = false;       // Tự động gửi tin test khi khởi động EA

input group "=== 2. THIẾT LẬP CỔNG CẢNH BÁO ==="
input bool            InpPlaySound       = true;        // Phát âm thanh khi gửi tin thành công
input string          InpSoundFile       = "ok.wav";    // File âm thanh
input bool            InpShowButton      = true;        // Hiển thị nút bấm Test trên Chart

input group "=== 3. THÔNG SỐ HỆ THỐNG ==="
input int             InpTimerSeconds    = 1;           // Tần suất quét hàng đợi liên chart (giây)
input int             InpHttpTimeout     = 5000;        // Timeout WebRequest (mili-giây)

//+------------------------------------------------------------------+
//| Biến toàn cục                                                    |
//+------------------------------------------------------------------+
const string g_btnTestName   = "DucTri_Bridge_BtnTest";
const string g_lblStatusName = "DucTri_Bridge_LblStatus";
const int    CUSTOM_EVENT_TG = 7777;

string   g_token   = "";
string   g_chatId  = "";

int      g_statSuccessCount = 0;
int      g_statFailCount    = 0;
datetime g_lastSentTime     = 0;
string   g_lastSentSummary  = "Chưa có tín hiệu nào";

string   g_sentIds[128];
int      g_sentIdx = 0;

//+------------------------------------------------------------------+
//| Đồng bộ Cấu hình Telegram dùng chung (FILE_COMMON UTF-8)         |
//+------------------------------------------------------------------+
void SaveTelegramConfig(string token, string chatId)
{
   if(token == "" && chatId == "") return;
   int handle = FileOpen("duc_tri_tg_config.txt", FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE, 0, CP_UTF8);
   if(handle != INVALID_HANDLE)
   {
      FileWriteString(handle, token + "\r\n" + chatId + "\r\n");
      FileClose(handle);
   }
}

void LoadTelegramConfig(string &token, string &chatId)
{
   if(token != "" && chatId != "") return;
   if(!FileIsExist("duc_tri_tg_config.txt", FILE_COMMON)) return;
   int handle = FileOpen("duc_tri_tg_config.txt", FILE_READ|FILE_TXT|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE, 0, CP_UTF8);
   if(handle != INVALID_HANDLE)
   {
      string t = FileReadString(handle);
      string c = FileReadString(handle);
      StringTrimRight(t); StringTrimLeft(t);
      StringTrimRight(c); StringTrimLeft(c);
      if(token == "" && t != "") token = t;
      if(chatId == "" && c != "") chatId = c;
      FileClose(handle);
   }
}

//+------------------------------------------------------------------+
//| Mã hóa URL an toàn chuẩn RFC 3986 (Hỗ trợ UTF-8, Emoji, HTML)     |
//+------------------------------------------------------------------+
string UrlEncode(string text)
{
   uchar src[];
   StringToCharArray(text, src, 0, WHOLE_ARRAY, CP_UTF8);
   int sz = ArraySize(src);
   if(sz > 0 && src[sz - 1] == 0) sz--;

   string result = "";
   StringInit(result, sz * 3, 0);
   result = "";
   for(int i = 0; i < sz; i++)
   {
      uchar c = src[i];
      if((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
         c == '-' || c == '_' || c == '.' || c == '~')
      {
         StringAdd(result, CharToString((char)c));
      }
      else
      {
         StringAdd(result, StringFormat("%%%02X", c));
      }
   }
   return result;
}

//+------------------------------------------------------------------+
//| Kiểm tra ID tin nhắn đã gửi chưa (Chống gửi trùng lặp)           |
//+------------------------------------------------------------------+
bool IsMessageAlreadySent(string id)
{
   if(id == "") return false;
   for(int i = 0; i < 128; i++)
   {
      if(g_sentIds[i] == id) return true;
   }
   return false;
}

void RecordMessageSent(string id)
{
   if(id == "") return;
   g_sentIds[g_sentIdx] = id;
   g_sentIdx = (g_sentIdx + 1) % 128;
}

//+------------------------------------------------------------------+
//| Cập nhật giao diện Trạng thái Bridge trên Chart                  |
//+------------------------------------------------------------------+
void UpdateChartStatus()
{
   string effToken  = (InpTgToken != "")  ? InpTgToken  : g_token;
   string effChatId = (InpTgChatID != "") ? InpTgChatID : g_chatId;

   string tokStatus = (effToken != "") ? "Đã kết nối (*" + StringSubstr(effToken, MathMax(0, StringLen(effToken) - 6)) + ")" : "Chờ nhập Token";
   string cidStatus = (effChatId != "") ? effChatId : "Chờ nhập Chat ID";
   string lastTimeStr = (g_lastSentTime > 0) ? TimeToString(g_lastSentTime, TIME_DATE|TIME_SECONDS) : "Chưa có";

   // Cập nhật nhãn trạng thái góc trên bên phải chart (không bao giờ bị che khuất)
   if(ObjectFind(0, g_lblStatusName) >= 0)
   {
      string statusTxt = StringFormat("🟢 TG Bridge: ONLINE | Gửi: %d | Lỗi: %d", g_statSuccessCount, g_statFailCount);
      ObjectSetString(0, g_lblStatusName, OBJPROP_TEXT, statusTxt);
   }

   // Chỉ hiện Comment nếu trên chart KHÔNG có Dashboard Canvas của Chỉ Báo
   if(ObjectFind(0, "DucTri_CV") < 0)
   {
      string hud = StringFormat(
         "╔════════════════════════════════════════════════════════════════════╗\n" +
         "  ĐỨC TRÍ TELEGRAM BRIDGE EA v3.1 [SMC INSTITUTIONAL GATEWAY]\n" +
         "╠════════════════════════════════════════════════════════════════════╣\n" +
         "  ● Trạng thái:        🟢 HOẠT ĐỘNG (Đang lắng nghe M5 CHoCH & Cản H1)\n" +
         "  ● Bot Token:         %s\n" +
         "  ● Chat ID:           %s\n" +
         "  ● Kèo gửi thành công: %d  |  Thất bại: %d\n" +
         "  ● Lần gửi gần nhất:  %s (%s)\n" +
         "  ● Cổng liên cặp:     Tự động quét hàng đợi liên chart (FILE_COMMON UTF-8)\n" +
         "╠════════════════════════════════════════════════════════════════════╣\n" +
         "  [⚡ Nút 'GỬI TEST TELEGRAM' ở góc trên bên phải màn hình]\n" +
         "╚════════════════════════════════════════════════════════════════════╝",
         tokStatus, cidStatus,
         g_statSuccessCount, g_statFailCount,
         lastTimeStr, g_lastSentSummary
      );
      Comment(hud);
   }
   else
   {
      Comment(""); // Giữ chart sạch khi có Dashboard Canvas của Indicator
   }
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| Gửi HTTP POST tới Telegram Bot API qua native WebRequest         |
//+------------------------------------------------------------------+
bool SendTelegramHttp(string token, string chatId, string message)
{
   string actualToken  = (token != "")  ? token  : (InpTgToken != "" ? InpTgToken : g_token);
   string actualChatId = (chatId != "") ? chatId : (InpTgChatID != "" ? InpTgChatID : g_chatId);

   if(actualToken == "" || actualChatId == "")
   {
      Print("❌ [Đức Trí Bridge EA] Lỗi: Chưa có Telegram Bot Token hoặc Chat ID! Hãy nhập vào cài đặt EA hoặc Chỉ báo.");
      return false;
   }

   // Lưu cấu hình hợp lệ để các chỉ báo/chart khác cùng dùng
   if(actualToken != "" && actualChatId != "")
   {
      g_token = actualToken;
      g_chatId = actualChatId;
      SaveTelegramConfig(actualToken, actualChatId);
   }

   string url = StringFormat("https://api.telegram.org/bot%s/sendMessage", actualToken);
   string headers = "Content-Type: application/x-www-form-urlencoded\r\n";
   string body = StringFormat("chat_id=%s&text=%s&parse_mode=HTML&disable_web_page_preview=true",
                              UrlEncode(actualChatId),
                              UrlEncode(message));

   char postData[];
   StringToCharArray(body, postData, 0, WHOLE_ARRAY, CP_UTF8);
   int dataLen = ArraySize(postData);
   if(dataLen > 0 && postData[dataLen - 1] == 0)
      ArrayResize(postData, dataLen - 1);

   char resultData[];
   string resultHeaders;

   ResetLastError();
   int res = WebRequest("POST", url, headers, InpHttpTimeout, postData, resultData, resultHeaders);

   if(res == 200)
   {
      PrintFormat("✅ [Đức Trí Bridge EA] Gửi Telegram thành công! (Chat ID: %s)", actualChatId);
      if(InpPlaySound && InpSoundFile != "") PlaySound(InpSoundFile);
      g_statSuccessCount++;
      g_lastSentTime = TimeLocal();
      
      // Trích xuất tóm tắt dòng đầu
      int firstNl = StringFind(message, "\n");
      if(firstNl > 0)
         g_lastSentSummary = StringSubstr(message, 0, firstNl);
      else
         g_lastSentSummary = message;

      UpdateChartStatus();
      return true;
   }
   else
   {
      int err = GetLastError();
      g_statFailCount++;

      if(res == -1)
      {
         PrintFormat("❌ [Đức Trí Bridge EA] LỖI WebRequest (Error=%d). QUAN TRỌNG: Bạn chưa cấp quyền WebRequest cho MT5! Hãy vào Tools -> Options -> Expert Advisors -> tích chọn 'Allow WebRequest for listed URL' và thêm chính xác 'https://api.telegram.org'!", err);
      }
      else if(res == 401 || res == 404)
      {
         PrintFormat("❌ [Đức Trí Bridge EA] HTTP %d: Bot Token không hợp lệ. Vui lòng kiểm tra lại Token được cấp từ @BotFather!", res);
      }
      else if(res == 400)
      {
         string resp = CharArrayToString(resultData, 0, WHOLE_ARRAY, CP_UTF8);
         PrintFormat("❌ [Đức Trí Bridge EA] HTTP 400: Telegram từ chối gửi (%s). Vui lòng kiểm tra Chat ID và đảm bảo bạn đã bấm /start với bot!", resp);
      }
      else
      {
         PrintFormat("❌ [Đức Trí Bridge EA] Gửi thất bại HTTP %d (LastError=%d).", res, err);
      }

      UpdateChartStatus();
      return false;
   }
}

//+------------------------------------------------------------------+
//| Phân giải gói tin Payload an toàn (Key-Value)                    |
//+------------------------------------------------------------------+
void ParsePayload(const string payload, string &id, string &token, string &chatId, string &text)
{
   id = ""; token = ""; chatId = ""; text = "";

   int posId  = StringFind(payload, "ID=");
   int posTok = StringFind(payload, "TOKEN=");
   int posCid = StringFind(payload, "CHATID=");
   int posTxt = StringFind(payload, "TEXT=");

   if(posId >= 0 && posTok > posId)
   {
      int start = posId + 3;
      int len = posTok - start;
      id = StringSubstr(payload, start, len);
      StringTrimRight(id);
      StringTrimLeft(id);
   }

   if(posTok >= 0 && posCid > posTok)
   {
      int start = posTok + 6;
      int len = posCid - start;
      token = StringSubstr(payload, start, len);
      StringTrimRight(token);
      StringTrimLeft(token);
   }

   if(posCid >= 0 && posTxt > posCid)
   {
      int start = posCid + 7;
      int len = posTxt - start;
      chatId = StringSubstr(payload, start, len);
      StringTrimRight(chatId);
      StringTrimLeft(chatId);
   }

   if(posTxt >= 0)
   {
      text = StringSubstr(payload, posTxt + 5);
      StringTrimLeft(text);
   }
}

//+------------------------------------------------------------------+
//| Quét hàng đợi tín hiệu từ file dùng chung FILE_COMMON (UTF-8)    |
//+------------------------------------------------------------------+
void ProcessQueueFile()
{
   if(!FileIsExist("duc_tri_tg_queue.txt", FILE_COMMON)) return;

   int handle = FileOpen("duc_tri_tg_queue.txt", FILE_READ|FILE_TXT|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE, 0, CP_UTF8);
   if(handle == INVALID_HANDLE) return;

   string allContent = "";
   while(!FileIsEnding(handle))
   {
      string line = FileReadString(handle);
      allContent += line + "\n";
   }
   FileClose(handle);

   if(StringLen(allContent) == 0)
   {
      FileDelete("duc_tri_tg_queue.txt", FILE_COMMON);
      return;
   }

   // Xóa file hàng đợi sau khi đã đọc nội dung vào bộ nhớ
   FileDelete("duc_tri_tg_queue.txt", FILE_COMMON);

   int startPos = 0;
   while(true)
   {
      int blockStart = StringFind(allContent, "===MSG_START===", startPos);
      if(blockStart < 0) break;

      int contentStart = blockStart + 15;
      while(contentStart < StringLen(allContent) && 
            (StringGetCharacter(allContent, contentStart) == '\r' || StringGetCharacter(allContent, contentStart) == '\n'))
      {
         contentStart++;
      }

      int blockEnd = StringFind(allContent, "===MSG_END===", contentStart);
      if(blockEnd < 0) break;

      int contentEnd = blockEnd;
      while(contentEnd > contentStart && 
            (StringGetCharacter(allContent, contentEnd - 1) == '\r' || StringGetCharacter(allContent, contentEnd - 1) == '\n'))
      {
         contentEnd--;
      }

      string block = StringSubstr(allContent, contentStart, contentEnd - contentStart);
      startPos = blockEnd + 13;

      string id, token, chatId, text;
      ParsePayload(block, id, token, chatId, text);

      if(id != "" && text != "")
      {
         if(!IsMessageAlreadySent(id))
         {
            RecordMessageSent(id);
            SendTelegramHttp(token, chatId, text);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Tạo Nút Bấm Gửi Thử Nghiệm trên Biểu Đồ (Góc Phải Không Bị Che)   |
//+------------------------------------------------------------------+
void CreateTestButton()
{
   if(!InpShowButton) return;

   if(ObjectFind(0, g_btnTestName) < 0)
   {
      if(ObjectCreate(0, g_btnTestName, OBJ_BUTTON, 0, 0, 0))
      {
         ObjectSetInteger(0, g_btnTestName, OBJPROP_CORNER, CORNER_RIGHT_UPPER);
         ObjectSetInteger(0, g_btnTestName, OBJPROP_XDISTANCE, 220);
         ObjectSetInteger(0, g_btnTestName, OBJPROP_YDISTANCE, 25);
         ObjectSetInteger(0, g_btnTestName, OBJPROP_XSIZE, 200);
         ObjectSetInteger(0, g_btnTestName, OBJPROP_YSIZE, 30);
         ObjectSetString(0, g_btnTestName, OBJPROP_TEXT, "⚡ GỬI TEST TELEGRAM");
         ObjectSetString(0, g_btnTestName, OBJPROP_FONT, "Segoe UI Semibold");
         ObjectSetInteger(0, g_btnTestName, OBJPROP_FONTSIZE, 9);
         ObjectSetInteger(0, g_btnTestName, OBJPROP_COLOR, C'255,255,255');
         ObjectSetInteger(0, g_btnTestName, OBJPROP_BGCOLOR, C'37,99,235');
         ObjectSetInteger(0, g_btnTestName, OBJPROP_BORDER_COLOR, C'96,165,250');
         ObjectSetInteger(0, g_btnTestName, OBJPROP_STATE, false);
      }
   }

   if(ObjectFind(0, g_lblStatusName) < 0)
   {
      if(ObjectCreate(0, g_lblStatusName, OBJ_LABEL, 0, 0, 0))
      {
         ObjectSetInteger(0, g_lblStatusName, OBJPROP_CORNER, CORNER_RIGHT_UPPER);
         ObjectSetInteger(0, g_lblStatusName, OBJPROP_XDISTANCE, 220);
         ObjectSetInteger(0, g_lblStatusName, OBJPROP_YDISTANCE, 62);
         ObjectSetString(0, g_lblStatusName, OBJPROP_FONT, "Segoe UI Semibold");
         ObjectSetInteger(0, g_lblStatusName, OBJPROP_FONTSIZE, 8);
         ObjectSetInteger(0, g_lblStatusName, OBJPROP_COLOR, C'52,211,153');
         ObjectSetString(0, g_lblStatusName, OBJPROP_TEXT, "🟢 TG Bridge: ONLINE");
      }
   }

   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| Gửi Tin Nhắn Test Kiểm Tra Kết Nối                               |
//+------------------------------------------------------------------+
void SendTestSignal()
{
   string effToken  = (InpTgToken != "")  ? InpTgToken  : g_token;
   string effChatId = (InpTgChatID != "") ? InpTgChatID : g_chatId;

   string testMsg = StringFormat(
      "🎉 <b>KẾT NỐI TELEGRAM BOT THÀNH CÔNG!</b>\n" +
      "━━━━━━━━━━━━━━━━━━━\n" +
      "🤖 <b>Cổng kết nối:</b> Đức Trí Telegram Bridge EA v3.1\n" +
      "💎 <b>Chart đang gắn:</b> <code>%s</code> (%s)\n" +
      "⏱ <b>Thời gian:</b> <code>%s</code>\n" +
      "━━━━━━━━━━━━━━━━━━━\n" +
      "✅ <i>Hệ thống báo kèo M5 CHoCH sau khi quét cản H1 đã sẵn sàng hoạt động 100%%!</i>",
      _Symbol, EnumToString((ENUM_TIMEFRAMES)_Period),
      TimeToString(TimeLocal(), TIME_DATE|TIME_SECONDS)
   );

   SendTelegramHttp(effToken, effChatId, testMsg);
}

//+------------------------------------------------------------------+
//| Khởi tạo EA                                                      |
//+------------------------------------------------------------------+
int OnInit()
{
   for(int i = 0; i < 128; i++) g_sentIds[i] = "";
   g_sentIdx = 0;

   // Nạp hoặc lưu cấu hình Token/Chat ID
   if(InpTgToken != "" && InpTgChatID != "")
   {
      g_token = InpTgToken;
      g_chatId = InpTgChatID;
      SaveTelegramConfig(InpTgToken, InpTgChatID);
   }
   else
   {
      LoadTelegramConfig(g_token, g_chatId);
   }

   // Đánh dấu EA Bridge đang online cho Chỉ báo nhận biết (Dùng TimeLocal chống đứng giá cuối tuần)
   GlobalVariableSet("DucTri_TgBridge_Heartbeat", (double)TimeLocal());
   string effTok = (InpTgToken != "") ? InpTgToken : g_token;
   string effCid = (InpTgChatID != "") ? InpTgChatID : g_chatId;
   GlobalVariableSet("DucTri_TgBridge_Configured", (effTok != "" && effCid != "") ? 1.0 : 0.0);

   CreateTestButton();
   UpdateChartStatus();

   EventSetTimer(MathMax(1, InpTimerSeconds));

   Print("🚀 [Đức Trí Bridge EA] Đã khởi động thành công. Sẵn sàng chuyển tiếp tín hiệu Telegram!");

   if(InpSendTestOnStart)
   {
      SendTestSignal();
   }

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Hủy EA                                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   GlobalVariableDel("DucTri_TgBridge_Heartbeat");
   GlobalVariableDel("DucTri_TgBridge_Configured");
   ObjectDelete(0, g_btnTestName);
   ObjectDelete(0, g_lblStatusName);
   Comment("");
   Print("🛑 [Đức Trí Bridge EA] Đã dừng hoạt động.");
}

//+------------------------------------------------------------------+
//| Xử lý sự kiện Timer (Quét hàng đợi từ các chart khác)           |
//+------------------------------------------------------------------+
void OnTimer()
{
   // Cập nhật nhịp tim định kỳ bằng TimeLocal()
   GlobalVariableSet("DucTri_TgBridge_Heartbeat", (double)TimeLocal());
   string effTok = (InpTgToken != "") ? InpTgToken : g_token;
   string effCid = (InpTgChatID != "") ? InpTgChatID : g_chatId;
   GlobalVariableSet("DucTri_TgBridge_Configured", (effTok != "" && effCid != "") ? 1.0 : 0.0);

   // Nếu chưa có token, thử kiểm tra file config
   if(g_token == "" || g_chatId == "")
   {
      LoadTelegramConfig(g_token, g_chatId);
   }

   ProcessQueueFile();
   UpdateChartStatus();
}

//+------------------------------------------------------------------+
//| Xử lý sự kiện Chart (Sự kiện tức thì cùng chart & nút bấm)       |
//+------------------------------------------------------------------+
void OnChartEvent(const int id,
                  const long &lparam,
                  const double &dparam,
                  const string &sparam)
{
   // 1. Nhận tín hiệu thời gian thực từ Chỉ báo trên cùng Chart
   if(id == CHARTEVENT_CUSTOM + CUSTOM_EVENT_TG)
   {
      string msgId, token, chatId, text;
      ParsePayload(sparam, msgId, token, chatId, text);

      if(msgId != "" && text != "")
      {
         if(!IsMessageAlreadySent(msgId))
         {
            RecordMessageSent(msgId);
            SendTelegramHttp(token, chatId, text);
         }
      }
      return;
   }

   // 2. Click nút bấm Gửi Test Telegram
   if(id == CHARTEVENT_OBJECT_CLICK && sparam == g_btnTestName)
   {
      ObjectSetInteger(0, g_btnTestName, OBJPROP_STATE, false);
      ChartRedraw(0);
      SendTestSignal();
      return;
   }
}
//+------------------------------------------------------------------+
