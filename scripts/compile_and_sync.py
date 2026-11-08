import shutil
import os
import subprocess
import sys

def main():
    ws_dir = r'd:\trading thử lần cuối cuối'
    mt5_base = r'C:\Users\ductr\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5'
    metaeditor = r'C:\Program Files\MetaTrader 5\metaeditor64.exe'

    # 1. Copy source files to MT5 directory
    ind_src = os.path.join(ws_dir, 'duc_tri_can_ho_tro.mq5')
    ind_dst = os.path.join(mt5_base, 'Indicators', 'duc_tri_can_ho_tro.mq5')
    shutil.copy2(ind_src, ind_dst)

    ea_src = os.path.join(ws_dir, 'duc_tri_telegram_bridge.mq5')
    ea_dst = os.path.join(mt5_base, 'Experts', 'duc_tri_telegram_bridge.mq5')
    shutil.copy2(ea_src, ea_dst)

    sys.stdout.buffer.write(b'Copied mq5 to MT5 directory.\n')

    # 2. Compile EA
    ea_log = os.path.join(mt5_base, 'Experts', 'bridge_compile.log')
    if os.path.exists(ea_log): os.remove(ea_log)
    cmd_ea = f'"{metaeditor}" /compile:"{ea_dst}" /log:"{ea_log}"'
    subprocess.run(cmd_ea, shell=True)

    # 3. Compile Indicator
    ind_log = os.path.join(mt5_base, 'Indicators', 'ind_compile.log')
    if os.path.exists(ind_log): os.remove(ind_log)
    cmd_ind = f'"{metaeditor}" /compile:"{ind_dst}" /log:"{ind_log}"'
    subprocess.run(cmd_ind, shell=True)

    # 4. Read logs
    def read_log(p):
        if not os.path.exists(p): return 'Log not found: ' + p
        with open(p, 'r', encoding='utf-16le', errors='ignore') as f:
            return f.read()

    sys.stdout.buffer.write(b'--- EA COMPILE LOG ---\n')
    ea_log_txt = read_log(ea_log)
    lines = [l.strip() for l in ea_log_txt.splitlines() if l.strip()]
    for l in lines[-5:]:
        sys.stdout.buffer.write(f'{l}\n'.encode('utf-8'))

    sys.stdout.buffer.write(b'--- INDICATOR COMPILE LOG ---\n')
    ind_log_txt = read_log(ind_log)
    lines = [l.strip() for l in ind_log_txt.splitlines() if l.strip()]
    for l in lines[-5:]:
        sys.stdout.buffer.write(f'{l}\n'.encode('utf-8'))

    # 5. Copy compiled .ex5 back to workspace
    ea_ex5_dst = os.path.join(mt5_base, 'Experts', 'duc_tri_telegram_bridge.ex5')
    ea_ex5_ws = os.path.join(ws_dir, 'duc_tri_telegram_bridge.ex5')
    if os.path.exists(ea_ex5_dst):
        shutil.copy2(ea_ex5_dst, ea_ex5_ws)
        sys.stdout.buffer.write(f'EA ex5 size: {os.path.getsize(ea_ex5_ws)} bytes\n'.encode('utf-8'))

    ind_ex5_dst = os.path.join(mt5_base, 'Indicators', 'duc_tri_can_ho_tro.ex5')
    ind_ex5_ws = os.path.join(ws_dir, 'duc_tri_can_ho_tro.ex5')
    if os.path.exists(ind_ex5_dst):
        shutil.copy2(ind_ex5_dst, ind_ex5_ws)
        sys.stdout.buffer.write(f'Indicator ex5 size: {os.path.getsize(ind_ex5_ws)} bytes\n'.encode('utf-8'))

if __name__ == '__main__':
    main()
