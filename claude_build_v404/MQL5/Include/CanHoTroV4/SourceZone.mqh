#ifndef CHT_V4_SOURCE_ZONE
#define CHT_V4_SOURCE_ZONE
bool g_v4RenderSource=true;
string V4SourceObject(const SConfirmSignal &s)
{
   return "DucTri_V4_SOURCE_"+s.signal_id;
}
bool V4DrawSourceZone(const SConfirmSignal &s)
{
   if(!g_v4RenderSource) return true;
   string name=V4SourceObject(s);
   datetime start=s.zone_known_time;
   datetime end=s.signal_known_time;
#ifdef CHT_V4_CHART_DISPLAY
   end=iTime(_Symbol,PERIOD_H1,0)+3600*ExtendBars;
   for(int i=0;i<ArraySize(g_v4ZoneHistory);i++)if(g_v4ZoneHistory[i].id==s.source_zone_id)
      {start=g_v4ZoneHistory[i].timeStart;if(g_v4ZoneHistory[i].timeInvalid>0)end=g_v4ZoneHistory[i].timeInvalid;break;}
#endif
   if(start>=end) end=start+1;
   if(ObjectFind(0,name)<0 && !ObjectCreate(0,name,OBJ_RECTANGLE,0,start,s.source_distal,end,s.source_proximal)) return false;
   ObjectSetInteger(0,name,OBJPROP_TIME,0,start);
   ObjectSetInteger(0,name,OBJPROP_TIME,1,end);
   ObjectSetDouble(0,name,OBJPROP_PRICE,0,s.source_distal);
   ObjectSetDouble(0,name,OBJPROP_PRICE,1,s.source_proximal);
   ObjectSetInteger(0,name,OBJPROP_FILL,false);
   ObjectSetInteger(0,name,OBJPROP_COLOR,s.isBuy?clrSeaGreen:clrTomato);
   ObjectSetString(0,name,OBJPROP_TOOLTIP,"Source zone #"+IntegerToString(s.source_zone_id));
   return true;
}
#endif
