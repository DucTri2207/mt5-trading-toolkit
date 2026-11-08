@echo off
set R=%~dp0
set ME=%R%reports\can_ho_tro_v4\20261102_m3a_v1\portable_terminal\MetaEditor64.exe
set B=%R%claude_build_v404\MQL5
"%ME%" /portable /compile:"%B%\Indicators\duc_tri_can_ho_tro_v4.mq5" /inc:"%B%" /log:"%R%claude_build_v404\compile.log"
echo done > "%R%claude_build_v404\COMPILE_DONE.txt"
