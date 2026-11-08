#define CHT_M2_UNITS_ONLY
#include "TestV4M2.mq5"
#include <CanHoTroV4/M2Panel.mqh>
void OnStart()
{
   FileDelete("v4_fixture\\unit_checks.csv");
   M2Units(); RecoveredFixture();
   ShowDash=true; ObjectsDeleteAll(0,g_prefix+"M2_"); V4M2Panel();
   ChartRedraw();
   int witness=FileOpen("v4_fixture\\panel_witness.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   FileWrite(witness,"object","text","error","chart_width","chart_height","y");
   FileWrite(witness,g_prefix+"M2_0",ObjectGetString(0,g_prefix+"M2_0",OBJPROP_TEXT),GetLastError(),
      ChartGetInteger(0,CHART_WIDTH_IN_PIXELS),ChartGetInteger(0,CHART_HEIGHT_IN_PIXELS),ObjectGetInteger(0,g_prefix+"M2_0",OBJPROP_YDISTANCE));
   FileClose(witness);
   Check(ObjectGetString(0,g_prefix+"M2_0",OBJPROP_TEXT)+" "+ObjectGetString(0,g_prefix+"M2_1",OBJPROP_TEXT)==
      "Thống kê theo quy tắc cố định, không phải kết quả giao dịch của bạn","panel_fixed_disclaimer");
   Check(ObjectFind(0,g_prefix+"M2_EXPORT")>=0,"panel_export_button");
   Check(ObjectGetInteger(0,g_prefix+"M2_EXPORT",OBJPROP_YDISTANCE)+24<ChartGetInteger(0,CHART_HEIGHT_IN_PIXELS),"panel_inside_chart_height");
   ChartScreenShot(0,"v4_fixture\\m2_panel.png",1306,322);
   int f=FileOpen("v4_fixture\\m2_final_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{\"checks\":%d,\"failures\":%d,\"scope\":\"final risk/tick/persistence/journal/panel regressions\"}",checks,failures)); FileClose(f);
   PrintFormat("V4_M2_FINAL_DONE checks=%d failures=%d",checks,failures);
}
