"""Compile and synchronize the scalp indicator after a source change."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time


ROOT = r"D:\trading thử lần cuối cuối"
MT5_ROOT = r"C:\Users\ductr\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075"
METAEDITOR = r"C:\Program Files\MetaTrader 5\MetaEditor64.exe"
NAME = "duc_tri_can_ho_tro_scalp"
SRC = os.path.join(ROOT, NAME + ".mq5")
TARGET = os.path.join(MT5_ROOT, "MQL5", "Indicators", NAME + ".mq5")
EX5 = os.path.join(ROOT, NAME + ".ex5")
TARGET_EX5 = os.path.join(MT5_ROOT, "MQL5", "Indicators", NAME + ".ex5")
LOG = os.path.join(ROOT, "reports", "scalp_compile_distance_20261024.log")


def sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    shutil.copy2(SRC, TARGET)
    for p in (LOG, EX5):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    # MetaEditor expects the portable switch and a command-line string with
    # quoted paths.  It can return before writing the log, so poll briefly.
    cmd = f'"{METAEDITOR}" /portable /compile:"{TARGET}" /log:"{LOG}"'
    proc = subprocess.run(cmd, shell=True, cwd=os.path.dirname(METAEDITOR))
    for _ in range(50):
        if os.path.exists(LOG):
            break
        time.sleep(0.2)
    if not os.path.exists(LOG):
        print("compile log missing; return code", proc.returncode)
        return 1
    text = open(LOG, encoding="utf-16le", errors="ignore").read()
    print(text)
    if "Result: 0 errors, 0 warnings" not in text:
        return 1
    if not os.path.exists(TARGET_EX5):
        print("compiled EX5 missing")
        return 1
    shutil.copy2(TARGET_EX5, EX5)
    shutil.copy2(EX5, TARGET_EX5)
    print("workspace mq5 sha", sha(SRC))
    print("terminal mq5 sha", sha(TARGET))
    print("workspace ex5 sha", sha(EX5))
    print("terminal ex5 sha", sha(TARGET_EX5))
    if sha(SRC) != sha(TARGET) or sha(EX5) != sha(TARGET_EX5):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
