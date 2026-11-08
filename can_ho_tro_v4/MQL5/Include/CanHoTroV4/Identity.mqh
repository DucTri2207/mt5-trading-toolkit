#ifndef CHT_V4_IDENTITY
#define CHT_V4_IDENTITY
// These timestamps describe observations, not simulated order fills.
datetime g_v4Now=0, g_v4LastEvaluated=0;
bool g_v4IoFailed=false;
double g_v4Point=0.0;
const double V4_RR_EPSILON=1e-9;
// Diagnostics only: never used to choose signals or orders.
long g_v4DiagTicks=0,g_v4DiagObservations=0,g_v4DiagZoneRates=0,g_v4DiagZoneAtr=0,
     g_v4DiagLtfRates=0,g_v4DiagLtfAtr=0,g_v4DiagSpreadBlocked=0,g_v4DiagSpreadN=0;
long g_v4DiagEligible=0,g_v4DiagPoi=0,g_v4DiagSweep=0,g_v4DiagConfirm=0,g_v4DiagRisk=0,g_v4DiagRR=0;
int g_v4DiagRejectFile=INVALID_HANDLE;
long g_v4DiagTickSpreadN=0,g_v4DiagTickSpreadBlocked=0;
double g_v4DiagTickSpreadMin=DBL_MAX,g_v4DiagTickSpreadMax=0,g_v4DiagTickSpreadSum=0;
void V4DiagReject(string reason,datetime known,double risk,double maxRisk,double rr1=0,double rr2=0)
{
   if(g_v4DiagRejectFile!=INVALID_HANDLE) FileWrite(g_v4DiagRejectFile,reason,(long)known,risk,maxRisk,rr1,rr2);
}
double g_v4DiagSpreadMin=DBL_MAX,g_v4DiagSpreadMax=0,g_v4DiagSpreadSum=0;


long V4Hash(const string value)
{
   ulong h=14695981039346656037;
   for(int i=0;i<StringLen(value);i++)
   {
      h^=(ulong)StringGetCharacter(value,i);
      h*=1099511628211;
   }
   return (long)(h & 0x7FFFFFFFFFFFFFFF);
}

double V4Point()
{
   return g_v4Point>0.0 ? g_v4Point : _Point;
}

string V4ZoneKey(datetime start,bool supply,double distal,double proximal)
{
   return IntegerToString((long)start)+"|"+IntegerToString((int)supply)+"|"+
          IntegerToString((long)MathRound(distal/V4Point()))+"|"+
          IntegerToString((long)MathRound(proximal/V4Point()));
}

long V4ZoneId(datetime start,bool supply,double distal,double proximal)
{
   return V4Hash(V4ZoneKey(start,supply,distal,proximal));
}

string V4SignalId(const SConfirmSignal &s)
{
   return IntegerToString((long)s.time)+"_"+IntegerToString((int)s.isBuy)+"_"+
          IntegerToString(s.source_zone_id);
}

bool V4ZoneAvailable(const SZone &z,datetime t)
{
   return z.timeKnown<=t && (z.timeInvalid==0 || t<z.timeInvalid);
}

bool V4SweepAvailable(const SZone &z,datetime sweepOpen)
{
   return sweepOpen>=z.timeKnown;
}

bool V4RrAllowed(double rr1,double rr2)
{
   // TP mode defines the targets. MinRR remains an eligibility floor in every mode.
   return rr1+V4_RR_EPSILON>=MinRR && rr2+V4_RR_EPSILON>=rr1;
}

string V4Preset()
{
   string key=StringFormat("V4_M1|%s|%d|%d|%d|%d|%.12g|%.12g|%.12g|%d|%d|%d|%d|%d|%d|%d|%.12g|%.12g|%.12g|%.12g|%.12g|%.12g|%d|%d|%d|%d|%.12g|%d|%.12g|%.12g|%.12g|%d|%d|%.12g|%.12g|%.12g|%.12g|%.12g|%d|%.12g|%.12g|%.12g|%d",
      _Symbol,(int)(HtfPeriod==PERIOD_CURRENT?PERIOD_H1:HtfPeriod),(int)(LtfPeriod==PERIOD_CURRENT?PERIOD_M5:LtfPeriod),AtrLen,BaseMaxBars,BaseBarATR,BaseTotalATR,
      DepartATR,DepartBars,LegInBars,MaxHistory,MaxTests,MaxAgeBars,FlipLifeBars,
      (int)UseFlip,WDepart,WBase,WFresh,WReversal,WMtf,V4Point(),MinScoreShow,
      LtfBarsScan,(int)FilterKillzones,(int)UseReferenceLevels,MaxSpreadPrice,
      (int)InpSlMode,SlBufferATR,MinSlPips,MaxSlPips,(int)InpEntryMode,(int)InpTpMode,
      InpTp1RR,InpTp2RR,InpTp1Pips,InpTp2Pips,MinRR,(int)InpUseAutoBE,
      InpBeTriggerPips,InpBeTriggerATR,InpBeOffsetPips,(int)InpCompatV301);
   if(InpPriceScaleMode!=0) key+="|PRICE_SCALE_D1_2000="+(string)InpPriceScaleMode;
   key+="|CONFIRM="+(string)UseLtfConfirm;
   if(InpHistoryDays!=90)key+="|HISTORY_DAYS="+(string)InpHistoryDays;
   return IntegerToString(V4Hash(key+"|"+DoubleToString(WickRatioMin,12)));
}
string V4FileKey(){return _Symbol+"_"+V4Preset();}
#endif
