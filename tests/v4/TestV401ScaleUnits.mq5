#property strict
#define CHT_V4_NATIVE_FIXTURE
#define _Symbol "XAUUSD_FIXTURE"
#include <CanHoTroV4/Types.mqh>
#include <CanHoTroV4/Inputs.mqh>
#include "FixtureData.mqh"
#include <CanHoTroV4/Identity.mqh>
#include <CanHoTroV4/Time.mqh>
int unitChecks=0,bad=0;
void Check(bool x){unitChecks++;if(!x)bad++;}
void OnStart()
{
   datetime d=D'2024.01.01';ArrayResize(fixtureH,6);fixtureVisibleH=6;fixtureHL=5;
   for(int i=0;i<6;i++){ZeroMemory(fixtureH[i]);fixtureH[i].time=d+(i/2)*86400+(i%2)*23*3600;fixtureH[i].open=fixtureH[i].low=fixtureH[i].high=fixtureH[i].close=(i/2+1)*2000;}
   double k;InpPriceScaleMode=0;Check(V4PriceFactor(d+3600,k)&&k==1);
   InpPriceScaleMode=1;Check(!V4PriceFactor(d+3600,k));
   Check(V4PriceFactor(d+86400+3600,k)&&k==1);
   fixtureH[3].close=999999;Check(V4PriceFactor(d+86400+3600,k)&&k==1);fixtureH[3].close=4000;
   Check(V4PriceFactor(d+2*86400,k)&&k==2);
   Check(V4SetDecisionScale(d+2*86400));
   Check(V4Distance(MaxSlPips)*.1==20);Check(V4Distance(MinSlPips)*.1==5);
   Check(V4Distance(InpTp1Pips)*.1==12);Check(V4Distance(InpTp2Pips)*.1==24);
   Check(V4Distance(InpBeTriggerPips)*.1==12);Check(V4Distance(InpBeOffsetPips)*.1==.2);
   Check(V4Distance(MaxSpreadPrice)==.9);Check(V4Distance(InpHistSpreadPrice)==.6);Check(V4Distance(InpSlippagePoints)==2);
   InpPriceScaleMode=0;Check(V4SetDecisionScale(d));Check(V4Distance(MaxSlPips)==MaxSlPips);
   int f=FileOpen("v4_fixture\\scale_units.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{\"checks\":%d,\"failures\":%d}",unitChecks,bad));FileClose(f);PrintFormat("V401_SCALE_UNITS %d/%d",unitChecks-bad,unitChecks);
}
