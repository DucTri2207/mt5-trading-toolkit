"""Inventory and compile the untouched v3.01 in a new, offline portable workspace."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / 'thông tin nghiên cứu/ban_giao_codex_v4_2026-11-01/KE_HOACH_V4.md'
PLAN_HASH = 'a6f49be86ca213acd91076a62cb81498cfec65d1db7e7a29af4bc6fbb78fe1c8'
SOURCE_HASH = '5a244553a7e659fb50c78481294531e38b9e60d1d1c0b11adbc26db7c7226405'
SEED = ROOT / 'reports/scalp_structure_lab/20261025_pilot_v1/fixture_terminal'
PLATFORM = Path('C:/Program Files/MetaTrader 5')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def processes():
    result = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         "@(Get-CimInstance Win32_Process -Filter \"name='terminal64.exe' OR name='metaeditor64.exe'\" | "
         'Select-Object ProcessId,ExecutablePath) | ConvertTo-Json -Compress'],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else []


def inventory(source):
    rows = []
    group = ''
    groups = []
    for line_number, line in enumerate(source.splitlines(), 1):
        match = re.match(r'input group "(.*)"', line)
        if match:
            group = match[1]
            groups.append({'line': line_number, 'group': group})
        match = re.match(r'input\s+(\w+)\s+(\w+)\s*=\s*([^;]+);(?:\s*//\s*(.*))?', line)
        if not match:
            continue
        kind, name, default, description = match.groups()
        rows.append(dict(line=line_number, group=group, type=kind, v301_name=name,
                         default=default.strip(), v4_name=name,
                         v4_default=default.strip(), action='KEEP',
                         description=description or ''))
    assert len(rows) == len({row['v301_name'] for row in rows})
    return rows, groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='New report directory relative to workspace')
    args = parser.parse_args()
    run = (ROOT / args.run).resolve()
    report_root = (ROOT / 'reports/can_ho_tro_v4').resolve()
    if report_root not in run.parents:
        raise ValueError('Run must be below reports/can_ho_tro_v4')
    if (run / 'M0_MANIFEST.json').exists() or (run / 'portable_terminal').exists():
        raise FileExistsError('M0 output already exists; choose a new run')
    run.mkdir(parents=True, exist_ok=True)
    assert sha(PLAN) == PLAN_HASH, 'Plan hash changed'
    original = ROOT / 'duc_tri_can_ho_tro.mq5'
    assert sha(original) == SOURCE_HASH, 'Protected baseline source changed'
    source = original.read_text(encoding='utf-8-sig')
    rows, groups = inventory(source)
    with (run / 'INPUT_MAP.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    mapping = ['# Ánh xạ input v3.01 → v4', '',
               f'{len(rows)} tham số có giá trị, {len(groups)} dòng input group; '
               f'tổng {len(rows) + len(groups)} dòng khai báo. Giữ toàn bộ tên và mặc định gốc.', '',
               '| Dòng | Nhóm | Kiểu | Tên v3.01 → v4 | Mặc định giữ nguyên |',
               '|---:|---|---|---|---|']
    mapping.extend(f"| {r['line']} | {r['group']} | {r['type']} | `{r['v301_name']}` | `{r['default']}` |"
                   for r in rows)
    (run / 'INPUT_MAP.md').write_text('\n'.join(mapping) + '\n', encoding='utf-8')
    write_json(run / 'INPUT_GROUPS.json', groups)

    references = [PLAN, original, ROOT / 'duc_tri_can_ho_tro.ex5',
                  ROOT / 'duc_tri_can_ho_tro_agy_lab/duc_tri_can_ho_tro_agy_lab.mq5',
                  ROOT / 'reports/claude_signal_edge_probe/20261101/BAO_CAO.md',
                  ROOT / 'reports/can_ho_tro_scalp/20261101_round_v11/RESEARCH_CHECKPOINT.md',
                  ROOT / 'reports/can_ho_tro_agy_review/20261101_v2/BAO_CAO_KIEM_TRA.md',
                  ROOT / 'reports/gold_v301_causal/20261101/REPORT.md',
                  ROOT / 'reports/gold_live_review/20261101/USER_PLAYBOOK.md',
                  ROOT / 'reports/gold_v301_audit/20261101/REPORT.md',
                  ROOT / 'reports/gold_v301_audit/20261101/PREFIX_AUDIT.json',
                  ROOT / 'reports/gold_v301_audit/20261101/legacy_signals.json',
                  ROOT / 'reports/gold_v301_causal/20261101/signals_MQ5_PREFIX.csv',
                  ROOT / 'reports/scalp_structure_lab/20261025_pilot_v1/rates.npz']
    references.extend(sorted((ROOT / 'reports/claude_signal_edge_probe/20261101').glob('*.py')))
    baseline_hashes = {str(p.relative_to(ROOT)): sha(p) for p in references}
    before = processes()
    write_json(run / 'PROTECTED_INPUTS.json', baseline_hashes)
    write_json(run / 'PROCESSES_BEFORE.json', before)

    terminal = run / 'portable_terminal'
    terminal.mkdir()
    for name in ['terminal64.exe', 'MetaEditor64.exe']:
        src = (SEED / name) if (SEED / name).exists() else (PLATFORM / name)
        shutil.copy2(src, terminal / name)
    shutil.copytree(SEED / 'MQL5/Include', terminal / 'MQL5/Include')
    target = terminal / 'MQL5/Indicators/BaselineV301/duc_tri_can_ho_tro.mq5'
    target.parent.mkdir(parents=True)
    shutil.copy2(original, target)
    assert sha(target) == SOURCE_HASH
    # No terminal or account is opened by this compile command.
    log = run / 'COMPILE_V301.log'
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    command = f'"{terminal / "MetaEditor64.exe"}" /portable /compile:"{target}" /log:"{log}"'
    started = time.time()
    process = subprocess.run(command, cwd=terminal, startupinfo=startup, timeout=90)
    raw = log.read_bytes()
    diagnostics = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    match = re.search(r'Result:\s*(\d+) errors,\s*(\d+) warnings', diagnostics)
    binary = target.with_suffix('.ex5')
    if not match or not binary.exists() or binary.stat().st_mtime < started - 2:
        raise RuntimeError('Missing or stale compiler result: ' + diagnostics)
    errors, warnings = map(int, match.groups())
    assert errors == 0, diagnostics
    after = processes()
    write_json(run / 'PROCESSES_AFTER.json', after)
    for p in references:
        assert sha(p) == baseline_hashes[str(p.relative_to(ROOT))], f'Protected input changed: {p}'

    # Re-run the supplied probe; it only reads frozen data and writes this new run.
    probe = run / 'EDGE_PROBE_REPRODUCED.json'
    probe_script = ROOT / 'reports/claude_signal_edge_probe/20261101/edge_probe.py'
    with (run / 'EDGE_PROBE_STDOUT.log').open('w', encoding='utf-8') as output:
        subprocess.run([sys.executable, str(probe_script), str(ROOT), str(probe)],
                       stdout=output, stderr=subprocess.STDOUT, check=True)
    stats_script = probe_script.with_name('stats.py')
    with (run / 'EDGE_STATS_STDOUT.log').open('w', encoding='utf-8') as output:
        subprocess.run([sys.executable, str(stats_script), str(probe)],
                       stdout=output, stderr=subprocess.STDOUT, check=True)
    probe_rows = json.loads(probe.read_text())
    import numpy as np
    summary = {}
    for kind in ['SIG', 'OPP']:
        sample = [row for row in probe_rows if row['kind'] == kind]
        gross = np.array([row['tp1.0'] for row in sample])
        cost = np.array([0.39 / row['risk'] for row in sample])
        summary[kind] = dict(n=len(sample), gross_R=float(gross.mean()),
                             net_R=float((gross - cost).mean()),
                             win_fraction=float(np.mean(gross > 0)),
                             median_cost_R=float(np.median(cost)))
    assert summary['SIG']['n'] == 5164
    assert round(summary['SIG']['gross_R'], 3) == -0.029
    assert round(summary['SIG']['net_R'], 3) == -0.137
    write_json(run / 'EDGE_PROBE_CHECK.json', dict(
        supplied_script_rerun=True, statistics=summary,
        limitations=['240 observed M1 bars, not 240 elapsed minutes',
                     'Signals are idle candidates, not published alerts or an account backtest',
                     'Monthly bootstrap uses fixed 30-day epoch buckets, not calendar months',
                     'Trailing updates the stop after checking each bar; not a tick replay',
                     'Does not prove all possible future CHoCH filters have zero information']))

    manifest = dict(stage='M0', status='PASS', created_utc=datetime.now(timezone.utc).isoformat(),
                    plan_sha256=PLAN_HASH, protected_inputs=baseline_hashes,
                    input_parameters=len(rows), input_groups=len(groups),
                    build=dict(source=str(target.relative_to(ROOT)), source_sha256=sha(target),
                               binary=str(binary.relative_to(ROOT)), binary_sha256=sha(binary),
                               binary_bytes=binary.stat().st_size, errors=errors, warnings=warnings,
                               compiler_exit_code=process.returncode, command=command,
                               log_sha256=sha(log), elapsed_seconds=time.time() - started),
                    terminal_started=False, user_terminal_modified=False,
                    processes_before=before, processes_after=after,
                    original_source_and_binary_preserved=True,
                    edge_probe=summary,
                    runtime_versions=dict(python=sys.version, numpy=np.__version__),
                    files={p.name: sha(p) for p in run.iterdir() if p.is_file()})
    write_json(run / 'M0_MANIFEST.json', manifest)
    print(json.dumps(dict(status=manifest['status'], inputs=len(rows), groups=len(groups),
                         compiler_errors=errors, compiler_warnings=warnings,
                         edge_probe=summary), ensure_ascii=False))


if __name__ == '__main__':
    main()
