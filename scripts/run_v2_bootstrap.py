import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
import time

DIR = Path('reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2')
BRANCHES = ['B0', 'B1', 'H1', 'H2', 'H1_H2']
trades_dict = {b: pd.read_csv(DIR / f'TRADES_{b}.csv') for b in BRANCHES}

n_boot = 10000
seed = 20261101
np.random.seed(seed)

def get_month_str(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime('%Y-%m')

trades_by_branch_month = {}
all_months_set = set()

for b in BRANCHES:
    df = trades_dict[b].copy()
    df['month'] = [get_month_str(t) for t in df['entry_time']]
    all_months_set.update(df['month'].unique())
    trades_by_branch_month[b] = {
        m: df[df['month'] == m]['net_r'].values
        for m in df['month'].unique()
    }

all_months = np.array(sorted(list(all_months_set)))
n_months = len(all_months)

boot_indices = np.random.randint(0, n_months, size=(n_boot, n_months))
exp_samples = {b: np.zeros(n_boot) for b in BRANCHES}

for i in range(n_boot):
    sampled_months = all_months[boot_indices[i]]
    for b in BRANCHES:
        month_dict = trades_by_branch_month[b]
        arrays = [month_dict[m] for m in sampled_months if m in month_dict and len(month_dict[m]) > 0]
        if arrays:
            concat_r = np.concatenate(arrays)
            exp_samples[b][i] = np.mean(concat_r)
        else:
            exp_samples[b][i] = 0.0

b0_exp = exp_samples['B0']

delta_samples = {
    'B1_vs_B0': exp_samples['B1'] - b0_exp,
    'H1_vs_B0': exp_samples['H1'] - b0_exp,
    'H2_vs_B0': exp_samples['H2'] - b0_exp,
    'H1_H2_vs_B0': exp_samples['H1_H2'] - b0_exp
}

print(f"=== 10,000-Iteration Monthly Block Bootstrap (Seed {seed}) ===")
for comp_name, deltas in delta_samples.items():
    ci_lower = float(np.percentile(deltas, 2.5))
    ci_upper = float(np.percentile(deltas, 97.5))
    mean_delta = float(np.mean(deltas))
    std_err = float(np.std(deltas, ddof=1))
    p_val_le_zero = float(np.mean(deltas <= 0.0))
    print(f"{comp_name:12}: Mean Delta={mean_delta:+.4f} R | SE={std_err:.4f} | 95% CI=[{ci_lower:+.4f}, {ci_upper:+.4f}] | p(<=0)={p_val_le_zero:.4f}")

print("\nIndividual branch 95% CIs:")
for b in BRANCHES:
    samples = exp_samples[b]
    ci_lower = float(np.percentile(samples, 2.5))
    ci_upper = float(np.percentile(samples, 97.5))
    mean_exp = float(np.mean(samples))
    print(f"{b:6}: Mean Exp={mean_exp:+.4f} R | 95% CI=[{ci_lower:+.4f}, {ci_upper:+.4f}]")
