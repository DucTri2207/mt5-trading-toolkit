#ifndef CHT_V4_OBSERVATION
#define CHT_V4_OBSERVATION
// Signal publication and display-plan state are independent of actual tester positions.
bool V4ObserveClosedBar(datetime observation,datetime published,bool quiet)
{
   if(observation<=0 || published<observation) return false;
   g_v4ReplayTime=observation; g_v4Now=observation; g_v4PublishTime=published;
   g_v4DiagObservations++;
   if(!V4SetDecisionScale(observation)) return false;
   ScanHtfMacroZones();
   if(!g_v4ZonesReady) return false;
   DetectLtfConfirmation(quiet);
   MqlTick opening;
   if(V4DataTick(opening)) ManageActiveSignal(g_lastSignal.isBuy?opening.bid:opening.ask);
   return !g_v4IoFailed;
}
#endif
