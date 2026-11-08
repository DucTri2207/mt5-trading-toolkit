import os
import sys
import shutil
import hashlib
import subprocess
import re

# Ensure Windows stdout handles utf-8 characters properly
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

def compute_sha256(filepath: str) -> str:
    """Computes SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower()

def main():
    print("=" * 70)
    print("[BUILD & SYNC] METAEDITOR 64-BIT CLI BUILD & MT5 TERMINAL SYNC")
    print("=" * 70)

    ws_dir = r"d:\trading thử lần cuối cuối"
    metaeditor = r"C:\Program Files\MetaTrader 5\metaeditor64.exe"
    mt5_ind_dir = r"C:\Users\ductr\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Indicators"

    mq5_filename = "duc_tri_can_ho_tro.mq5"
    ex5_filename = "duc_tri_can_ho_tro.ex5"

    src_mq5 = os.path.join(ws_dir, mq5_filename)
    src_ex5 = os.path.join(ws_dir, ex5_filename)
    log_file = os.path.join(ws_dir, "compile_log.log")

    dst_mq5 = os.path.join(mt5_ind_dir, mq5_filename)
    dst_ex5 = os.path.join(mt5_ind_dir, ex5_filename)

    # 1. Verification of paths
    if not os.path.exists(metaeditor):
        print(f"[ERROR] MetaEditor binary not found at '{metaeditor}'")
        return 1
    if not os.path.exists(src_mq5):
        print(f"[ERROR] Source MQ5 not found at '{src_mq5}'")
        return 1
    if not os.path.exists(mt5_ind_dir):
        print(f"[ERROR] MT5 Indicators target folder not found at '{mt5_ind_dir}'")
        return 1

    # Remove stale compile log and old ex5 to prevent false-positives
    if os.path.exists(log_file):
        try:
            os.remove(log_file)
        except Exception:
            try:
                with open(log_file, "w", encoding="utf-16le") as f:
                    pass
            except Exception:
                pass

    if os.path.exists(src_ex5):
        try:
            os.remove(src_ex5)
        except Exception:
            pass

    # 2. Execute MetaEditor CLI
    cmd = f'"{metaeditor}" /compile:"{src_mq5}" /log:"{log_file}"'
    print(f"\n[1/4] Executing MetaEditor 64-bit CLI:\nCommand: {cmd}")
    
    proc = subprocess.run(cmd, shell=True)
    print(f"CLI Return Code: {proc.returncode} (Note: MetaEditor returns 1 or 0)")

    # 3. Parse log file (UTF-16LE with BOM)
    print("\n[2/4] Parsing compilation log for 0 errors, 0 warnings...")
    if not os.path.exists(log_file):
        print(f"[ERROR] Compilation log was not generated at '{log_file}'")
        return 1

    with open(log_file, "r", encoding="utf-16le", errors="ignore") as f:
        log_content = f.read()

    print("--- MetaEditor Log Tail ---")
    lines = [l.strip() for l in log_content.splitlines() if l.strip()]
    for l in lines[-6:]:
        print(f"  {l}")

    # Assert 0 errors, 0 warnings
    match = re.search(r"Result:\s*0\s*errors,\s*0\s*warnings", log_content)
    if not match:
        print("\n[FAILED] COMPILATION FAILED: Log did not contain 'Result: 0 errors, 0 warnings'")
        return 1
    print("[PASSED] COMPILATION PASSED: Exactly 0 errors, 0 warnings verified!")

    # Verify binary generation
    if not os.path.exists(src_ex5):
        print(f"[ERROR] Binary EX5 was not generated at '{src_ex5}'")
        return 1
    ex5_size = os.path.getsize(src_ex5)
    print(f"[PASSED] Generated EX5 binary: {ex5_size} bytes")

    # 4. Synchronize MQ5 and EX5 to MT5 Terminal Indicators
    print(f"\n[3/4] Synchronizing artifacts to MT5 Terminal:\nTarget: {mt5_ind_dir}")
    shutil.copy2(src_mq5, dst_mq5)
    shutil.copy2(src_ex5, dst_ex5)
    print(f"  * Copied {mq5_filename} -> MT5")
    print(f"  * Copied {ex5_filename} -> MT5")

    # 5. Compute and assert SHA-256 hashes
    print("\n[4/4] Cryptographic SHA-256 Checksum Verification Gate:")
    mq5_ws_hash  = compute_sha256(src_mq5)
    mq5_mt5_hash = compute_sha256(dst_mq5)

    ex5_ws_hash  = compute_sha256(src_ex5)
    ex5_mt5_hash = compute_sha256(dst_ex5)

    print(f"  MQ5 Workspace SHA-256: {mq5_ws_hash}")
    print(f"  MQ5 Terminal  SHA-256: {mq5_mt5_hash}")
    if mq5_ws_hash != mq5_mt5_hash:
        print("  [ERROR] MQ5 SHA-256 mismatch!")
        return 1
    print("  [MATCH] MQ5 SHA-256 100% MATCH!")

    print(f"  EX5 Workspace SHA-256: {ex5_ws_hash}")
    print(f"  EX5 Terminal  SHA-256: {ex5_mt5_hash}")
    if ex5_ws_hash != ex5_mt5_hash:
        print("  [ERROR] EX5 SHA-256 mismatch!")
        return 1
    print("  [MATCH] EX5 SHA-256 100% MATCH!")

    print("\n" + "=" * 70)
    print("[SUCCESS] BUILD & SYNC COMPLETE: 0 ERRORS, 0 WARNINGS, 100% CRYPTOGRAPHIC MATCH")
    print("=" * 70)
    return 0

if __name__ == "__main__":
    sys.exit(main())
