import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

DIR = Path('reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2')
branches = ['B0', 'B1', 'H1', 'H2', 'H1_H2']
trades = {b: pd.read_csv(DIR / f'TRADES_{b}.csv') for b in branches}

def get_month_str(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime('%Y-%m')

for b in branches:
    trades[b]['month'] = [get_month_str(t) for t in trades[b]['entry_time']]

all_months = sorted(list(set().union(*[trades[b]['month'].unique() for b in branches])))
print('Total months:', len(all_months), 'First:', all_months[0], 'Last:', all_months[-1])

for b in branches:
    df = trades[b]
    n_fill = len(df)
    net_r = df['net_r'].sum()
    exp = df['net_r'].mean()
    tp_pct = (df['exit_reason'] == 'TP').mean() * 100.0
    win_pct = (df['net_pnl_usd'] > 0).mean() * 100.0
    print(f"{b:6}: N_fill={n_fill:4d}, Net R={net_r:8.2f}, Exp={exp:7.4f}, TP%={tp_pct:5.2f}%, Win%={win_pct:5.2f}%")
