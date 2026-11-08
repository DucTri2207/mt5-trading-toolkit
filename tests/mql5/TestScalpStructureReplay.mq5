#property strict
#include "../../Include/ScalpStructureSetup.mqh"
#include "../../Include/ScalpStructurePlan.mqh"
string folder="scalp_structure_lab_v1\\";
SSBar m1[],m5[],h1[],d1[];
SSCandidate candidates[];
SSTrail updates[];
int failures=0,checks=0;
struct SSApplied {datetime time,known,anchor;double oldStop,newStop;};
void Check(const bool ok,const string label)
{checks++;if(!ok){failures++;Print("FAIL ",label);}}
bool ReadBars(const string name,SSBar &out[])
{
   int f=FileOpen(folder+name+".csv",FILE_READ|FILE_CSV|FILE_ANSI|FILE_COMMON,',');
   if(f==INVALID_HANDLE)return false;
   int n=0;
   while(!FileIsEnding(f))
   {
      string t=FileReadString(f);if(t=="")break;
      ArrayResize(out,n+1,65536);out[n].time=(datetime)StringToInteger(t);
      out[n].open=FileReadNumber(f);out[n].high=FileReadNumber(f);
      out[n].low=FileReadNumber(f);out[n].close=FileReadNumber(f);n++;
   }
   FileClose(f);return n>0;
}
void AddTrail(const SSTrail &t,const int f)
{
   if(t.time==0)return;
   int n=ArraySize(updates);ArrayResize(updates,n+1,1024);updates[n]=t;
   FileWrite(f,(long)t.time,(int)t.isBuy,(long)t.anchorTime,DoubleToString(t.stop,10));
}
void Detect()
{
   SSDetector fast,slow;slow.Reset(3600);
   int hi=0,di=0;
   int cf=FileOpen(folder+"candidates_mql.csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',');
   int tf=FileOpen(folder+"trails_mql.csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',');
   for(int i=0;i<ArraySize(m5);i++)
   {
      datetime at=m5[i].time+300;SSCandidate c,x;SSTrail tb,ts,a,b;
      while(hi<ArraySize(h1) && h1[hi].time+3600<=at){slow.Step(h1[hi],x,a,b);hi++;}
      while(di<ArraySize(d1) && d1[di].time+86400<=at)di++;
      fast.Step(m5[i],c,tb,ts);
      if(at<D'2021.10.25 00:00')continue;
      AddTrail(tb,tf);AddTrail(ts,tf);
      if(!c.valid)continue;
      fast.AddLevels(c.isBuy,c.trigger,at,c.opposing);slow.AddLevels(c.isBuy,c.trigger,at,c.opposing);
      if(di>0)fast.Consider(c.isBuy ? d1[di-1].high : d1[di-1].low,c.isBuy,c.trigger,c.opposing);
      int n=ArraySize(candidates);ArrayResize(candidates,n+1,1024);candidates[n]=c;
      FileWrite(cf,(long)c.time,(int)c.isBuy,(long)c.anchorTime,DoubleToString(c.anchor,10),DoubleToString(c.atr,10),DoubleToString(c.trigger,10),DoubleToString(c.opposing,10));
   }
   FileClose(cf);FileClose(tf);
}
int LowerBar(const datetime at)
{
   int l=0,r=ArraySize(m1);
   while(l<r){int mid=(l+r)/2;if(m1[mid].time<at)l=mid+1;else r=mid;}
   return l;
}
int LowerUpdate(const datetime at)
{
   int l=0,r=ArraySize(updates);
   while(l<r){int mid=(l+r)/2;if(updates[mid].time<at)l=mid+1;else r=mid;}
   return l;
}
void Replay(const SSExitPolicy policy,const double spread)
{
   string name=(policy==SS_FIXED_15 ? "E0_FIXED_1_5R" : "E1_STRUCTURE_TRAIL");
   int f=FileOpen(folder+"trades_mql_"+name+"_"+DoubleToString(spread,1)+".csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',');
   int ef=FileOpen(folder+"events_mql_"+name+"_"+DoubleToString(spread,1)+".csv",FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',');
   datetime busy=0;
   for(int i=0;i<ArraySize(candidates);i++)
   {
      SSCandidate c=candidates[i];if(c.time<=busy)continue;
      int entry=LowerBar(c.time);if(entry>=ArraySize(m1))continue;
      SSPlan p;
      if(!SSFillPlan(p,c,m1[entry].time,m1[entry].open,m1[entry].open+spread,.01,policy))continue;
      SSApplied applied[];
      int u=LowerUpdate(p.entryTime);
      for(int j=entry;j<ArraySize(m1);j++)
      {
         SSOnQuote(p,m1[j].time,m1[j].open,m1[j].open+spread);
         if(!p.active)break;
         if(policy==SS_STRUCTURE_TRAIL)
            while(u<ArraySize(updates) && updates[u].time<=m1[j].time)
            {
               double old=p.stop;
               SSApplyTrail(p,updates[u],m1[j].time,m1[j].open,m1[j].open+spread,.01);
               if(old!=p.stop)
               {
                  int n=ArraySize(applied);ArrayResize(applied,n+1);
                  applied[n].time=m1[j].time;applied[n].known=updates[u].time;applied[n].anchor=updates[u].anchorTime;
                  applied[n].oldStop=old;applied[n].newStop=p.stop;
               }
               u++;
            }
         SSOnMinuteRange(p,m1[j],spread);if(!p.active)break;
      }
      if(p.active){busy=m1[ArraySize(m1)-1].time+60;continue;}
      busy=p.exitTime;
      for(int j=0;j<ArraySize(applied);j++)
         FileWrite(ef,(long)c.time,(long)applied[j].time,DoubleToString(applied[j].oldStop,10),DoubleToString(applied[j].newStop,10),(long)applied[j].known,(long)applied[j].anchor);
      FileWrite(f,(long)c.time,(int)c.isBuy,(long)p.entryTime,DoubleToString(p.entry,10),DoubleToString(p.initialStop,10),DoubleToString(p.risk,10),(long)p.exitTime,DoubleToString(p.exitPrice,10),(int)p.result,DoubleToString(p.resultR,10),DoubleToString(p.stop,10),DoubleToString(p.roomR,10));
   }
   FileClose(f);FileClose(ef);
}
SSCandidate FixtureCandidate(const bool buy=true)
{
   SSCandidate c;ZeroMemory(c);c.valid=true;c.isBuy=buy;c.time=1000;c.anchorTime=700;
   c.anchor=buy?99.25:100.75;c.atr=1;c.trigger=100;c.opposing=buy?110:90;return c;
}
SSBar FixtureBar(const datetime t,const double o,const double h,const double l,const double c)
{SSBar b;b.time=t;b.open=o;b.high=h;b.low=l;b.close=c;return b;}
void Fixtures()
{
   SSPlan p;SSCandidate c=FixtureCandidate();
   Check(SSFillPlan(p,c,1000,100,100,.01,SS_FIXED_15),"fill");
   SSOnMinuteRange(p,FixtureBar(1000,100,100.1,98.9,99.5),0);
   Check(p.result==SS_STOP && MathAbs(p.resultR+1)<1e-8,"entry minute stop");
   SSFillPlan(p,c,1000,100,100,.01,SS_FIXED_15);
   SSOnMinuteRange(p,FixtureBar(1000,100,102,99.9,101.5),0);
   Check(p.result==SS_TARGET && MathAbs(p.resultR-1.5)<1e-8,"entry minute target");
   c=FixtureCandidate(false);SSFillPlan(p,c,1000,100,100.2,.01,SS_FIXED_15);
   SSOnMinuteRange(p,FixtureBar(1000,100,100.9,99.9,100.1),.2);
   Check(p.result==SS_STOP,"sell Ask stop");
   c=FixtureCandidate();SSFillPlan(p,c,1000,100,100,.01,SS_FIXED_15);
   SSOnMinuteRange(p,FixtureBar(1000,100,102,98,100),0);
   Check(p.result==SS_STOP,"ambiguous adverse first");
   SSFillPlan(p,c,1000,100,100,.01,SS_FIXED_15);SSOnQuote(p,1060,98,98);
   Check(p.result==SS_GAP && MathAbs(p.resultR+2)<1e-8,"gap worse than minus one");
   SSTrail t;t.time=1060;t.anchorTime=1001;t.isBuy=true;t.stop=100.5;
   SSFillPlan(p,c,1000,100,100,.01,SS_STRUCTURE_TRAIL);
   SSApplyTrail(p,t,1060,101,101,.01);
   SSOnMinuteRange(p,FixtureBar(1060,101,101.2,100.4,100.6),0);
   Check(MathAbs(p.resultR-.5)<1e-8 && MathAbs(p.initialStop-99)<1e-8,"R0 invariant");
   SSFillPlan(p,c,1000,100,100,.01,SS_STRUCTURE_TRAIL);SSOnQuote(p,1060,98,98);
   SSApplyTrail(p,t,1060,101,101,.01);
   Check(p.result==SS_GAP && p.stop==99,"old stop first no resurrection");
   SSFillPlan(p,c,1000,100,100,.01,SS_STRUCTURE_TRAIL);SSApplyTrail(p,t,1060,101,101,.01);
   t.time=1120;t.stop=99.5;SSApplyTrail(p,t,1120,101,101,.01);
   Check(p.stop==100.5,"never loosen");
   Check(!SSFillPlan(p,c,1120,100,100,.01,SS_FIXED_15),"late quote rejected");
   c.opposing=101.5;Check(!SSFillPlan(p,c,1000,100.2,100.2,.01,SS_FIXED_15),"room actual fill");
   c=FixtureCandidate();c.anchor=100.35;
   Check(!SSFillPlan(p,c,1000,100,100.2,.01,SS_FIXED_15),"stop placeable");
   SSDetector detector;detector.atr=1;ArrayResize(detector.bars,14);
   for(int j=0;j<14;j++)detector.bars[j]=FixtureBar(j*300,100,103,99,102);
   ArrayResize(detector.highs,2);ArrayResize(detector.lows,2);
   detector.highs[0].index=1;detector.highs[0].time=300;detector.highs[0].price=105;
   detector.highs[1].index=8;detector.highs[1].time=2400;detector.highs[1].price=110;
   detector.lows[0].index=3;detector.lows[0].time=900;detector.lows[0].price=95;
   detector.lows[1].index=11;detector.lows[1].time=3300;detector.lows[1].price=98;
   SSTrail a,b;detector.Step(FixtureBar(4200,100,106,97,105),c,a,b);
   Check(!c.valid,"broken anchor invalidated");
}
void OnStart()
{
   Fixtures();
   bool loaded=ReadBars("m1",m1)&&ReadBars("m5",m5)&&ReadBars("h1",h1)&&ReadBars("d1",d1);
   Check(loaded,"input bars");
   if(loaded)
   {
      Detect();double spreads[3]={.2,.5,1.0};
      for(int i=0;i<3;i++){Replay(SS_FIXED_15,spreads[i]);Replay(SS_STRUCTURE_TRAIL,spreads[i]);}
   }
   int f=FileOpen(folder+"mql_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   FileWriteString(f,StringFormat("{\"spec_version\":\"%s\",\"checks\":%d,\"failures\":%d,\"candidates\":%d,\"trails\":%d,\"m1\":%d}",SS_VERSION,checks,failures,ArraySize(candidates),ArraySize(updates),ArraySize(m1)));FileClose(f);
   Print("STRUCTURE LAB DONE checks=",checks," failures=",failures);
}
