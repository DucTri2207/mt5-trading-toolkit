"""Compile V4 sources only inside the M0 portable and collect actual diagnostics."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def compile_source(portable, source, log):
    binary = source.with_suffix('.ex5')
    if log.exists():
        raise FileExistsError(log)
    started = time.time()
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    command = f'"{portable / "MetaEditor64.exe"}" /portable /compile:"{source}" /log:"{log}"'
    proc = subprocess.run(command, cwd=portable, startupinfo=startup, timeout=90)
    raw = log.read_bytes()
    text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    match = re.search(r'Result:\s*(\d+) errors,\s*(\d+) warnings', text)
    ok = match and match.groups() == ('0', '0') and binary.exists() and binary.stat().st_mtime >= started - 2
    result = dict(command=command, returncode=proc.returncode, source_sha256=sha(source),
                  log_sha256=sha(log), errors=int(match[1]) if match else None,
                  warnings=int(match[2]) if match else None, passed=bool(ok),
                  binary_sha256=sha(binary) if ok else None)
    if not ok:
        for line in text.splitlines():
            if "error" in line.lower() or "warning" in line.lower():
                print(line.encode("ascii", "backslashreplace").decode("ascii"))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', required=True)
    p.add_argument('--label', required=True)
    a = p.parse_args()
    run = ROOT / a.run
    portable = run / 'portable_terminal'
    assert portable.is_dir()
    shutil.copytree(ROOT / 'can_ho_tro_v4/MQL5', portable / 'MQL5', dirs_exist_ok=True)
    source = portable / 'MQL5/Indicators/duc_tri_can_ho_tro_v4.mq5'
    result = compile_source(portable, source, run / f'COMPILE_M1_{a.label}.log')
    (run / f'BUILD_M1_{a.label}.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    if result['passed']:
        shutil.copy2(source.with_suffix('.ex5'), ROOT / 'can_ho_tro_v4/MQL5/Indicators/duc_tri_can_ho_tro_v4.ex5')
    print(json.dumps(result))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
