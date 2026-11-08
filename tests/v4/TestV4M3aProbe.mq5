#property strict
void OnStart()
{
   FolderCreate("v4_m3a_part1");
   int f=FileOpen("v4_m3a_part1\\probe.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(f!=INVALID_HANDLE) { FileWriteString(f,"NATIVE_PORTABLE_PROBE PASS\r\n"); FileClose(f); }
   TerminalClose(0);
}
