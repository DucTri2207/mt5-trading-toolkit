@echo off
cd /d "%~dp0reports\can_ho_tro_v4\20261102_m3a_v1\portable_terminal"
echo Dang chay backtest tick that M3b... cua so nay tu dong khi xong.
start "" /wait terminal64.exe /portable /config:"%cd%\m3b_tp1r.ini"
echo Xong. > "%~dp0reports\can_ho_tro_v4\20261102_m3b_v1\RUN1_DONE.txt"
