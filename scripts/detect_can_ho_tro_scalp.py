"""Export source-based candidates and context for the locked five-year run."""
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime

import numpy as np

from prepare_can_ho_tro_scalp import RUN, write_json, sha
from can_ho_tro_scalp_core import (bars_matrix, metaquotes_atr, ema50,
                                   detect_all, CANDIDATE_COLUMNS, GATE_NAMES)


def main():
    cfg = json.loads((RUN/'EXPERIMENT_LOCK.json').read_text(encoding='utf-8'))
    data = np.load(RUN/'rates.npz')
    bars = {key: bars_matrix(data[key]) for key in data.files}
    start = int(datetime.fromisoformat(cfg['period_start']).timestamp())
    stop = int(datetime.fromisoformat(cfg['period_end_exclusive']).timestamp())
    atr1, atr5, ma1 = metaquotes_atr(bars['h1']), metaquotes_atr(bars['m5']), ema50(bars['h1'])
    print('DETECT source H1/sweep/CHoCH; compiling numerical kernels...', flush=True)
    begin = time.monotonic()
    raw, snapshots = detect_all(bars['h1'], bars['m5'], bars['d1'], atr1, atr5, ma1, start, stop)
    corrected, _ = detect_all(bars['h1'], bars['m5'], bars['d1'], atr1, atr5, ma1, start, stop, True)
    np.savez_compressed(RUN/'detector_python.npz', raw=raw, c0_raw=corrected, snapshots=snapshots,
                        atr1=atr1, atr5=atr5, ma1=ma1)
    np.savetxt(RUN/'candidates_python.csv', raw, delimiter=',', fmt='%.10f')
    np.savetxt(RUN/'candidates_c0_python.csv', corrected, delimiter=',', fmt='%.10f')
    np.savetxt(RUN/'snapshots_python.csv', snapshots, delimiter=',', fmt='%.10f')
    metadata = {
        'candidate_columns': CANDIDATE_COLUMNS,
        'snapshot_columns': ['known_at', 'closed_h1_count', 'zone_count', 'score_sum', 'tests_sum'],
        'raw_actionable_zone_candidates': len(raw),
        'c0_raw_actionable_zone_candidates': len(corrected),
        'source_gate_counts': dict(Counter(GATE_NAMES[int(r[27])] for r in raw)),
        'c0_gate_counts_after_source_pass': dict(Counter(GATE_NAMES[int(r[28])] for r in raw if r[27] == 0)),
        'elapsed_seconds': time.monotonic()-begin,
        'source_atr': 'MetaQuotes rolling TR mean, seed index14; native buffer comparison required',
        'detector_file_sha256': sha(RUN/'detector_python.npz'),
        'data_sha256': sha(RUN/'rates.npz'),
        'results_are_not_yet_mql_parity': True,
    }
    write_json(RUN/'detector_manifest.json', metadata)
    print(json.dumps(metadata, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
