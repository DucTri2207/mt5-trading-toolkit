"""Real CLI/session/collector/report/retirement integration; synthetic evidence only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from quantmt5.util import PROJECT_DIR, sha256_file


def test_real_session_finish_and_fresh_generation(tmp_path):
    # Freeze this test's engine hash while agents or developers edit the working copy.
    engine = tmp_path / "engine"
    shutil.copytree(PROJECT_DIR / "quantmt5", engine / "quantmt5", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(PROJECT_DIR / "config", engine / "config")
    shutil.copy2(PROJECT_DIR / "run_quant.py", engine / "run_quant.py")
    fixture = PROJECT_DIR / "tests" / "fixtures" / "b6c_fixture.py"
    root = tmp_path / "operations"
    root.mkdir()
    env = dict(os.environ, QUANTMT5_ALLOW_SYNTHETIC_FIXTURE="1", QUANTMT5_FIXTURE_VARIANT="default",
               QUANTMT5_FIXTURE_TICK_START="2025-01-15T14:00:00Z", QUANTMT5_STORE=str(tmp_path / "isolated_store"))
    env.pop("QUANTMT5_CONFIG_DIR", None)
    env.pop("QUANTMT5_WORKSPACE", None)
    env.pop("QUANTMT5_ALLOW_TEST_HOOKS", None)
    env.pop("QUANTMT5_TEST_CRASH_POINT", None)

    def cli(action, *args):
        process = subprocess.run([sys.executable, "-X", "utf8", "-I", str(engine / "run_quant.py"),
                                  "session", action, "--root", str(root), "--name", "evening", *map(str, args)],
                                 env=env, capture_output=True, cwd=root, timeout=180, stdin=subprocess.DEVNULL)
        stdout = process.stdout.decode("utf-8", "replace")
        try:
            result = json.loads(stdout)
        except ValueError:
            raise AssertionError((process.returncode, stdout, process.stderr.decode("utf-8", "replace")))
        return result

    initial = cli("init", "--terminal-path", "C:/SYNTH MT5", "--mode", "SYNTHETIC_FIXTURE",
                  "--symbols", "XAUUSD", "--synthetic-fixture", fixture, "--cycle-timeout", "120")
    assert initial["status"] == "OK", initial
    first = cli("once", "--end", "2025-01-15T15:30:00Z")
    assert first["data"]["status"] in ("OK", "PARTIAL"), first
    token = first["data"]["finish_token"]
    assert token["status"] == "REPORT_COMMITTED"
    assert token["local_day"] == "2025-01-15"
    session = root / "sessions" / "evening"
    snapshot_path = session / "data" / "store" / "snapshots" / f"{token['snapshot_id']}.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    pin = snapshot["tick_versions"]["XAUUSD"]
    assert pin["tick_generation_id"] == token["generation_id"]
    candidate = snapshot["candidates"][0]
    tick_dir = Path(pin["chunk_dir"])
    tick_files = [p for p in tick_dir.rglob("*") if p.is_file()]
    assert tick_files
    tick_bytes = sum(p.stat().st_size for p in tick_files)
    preserved = [snapshot_path, session / "session.json", session / "identity_pin.json",
                 *[Path(first["data"]["report"][key]) for key in ("report_md", "report_json")],
                 *list((session / "data" / "raw").glob("*/XAUUSD/bars/*/*.npz")),
                 *list((session / "data" / "bundles").rglob("*.json"))]
    hashes = {p: sha256_file(p) for p in preserved}
    replay_args = ["--", "replay", "--snapshot", token["snapshot_id"], "--candidate", candidate["candidate_id"], "--symbol", "XAUUSD"]
    replay_before = cli("exec", *replay_args)
    assert "TICK_DATA_PURGED_BY_RETENTION" not in json.dumps(replay_before)

    def finish(old_token):
        return cli("finish", "--expected-cycle", old_token["cycle_id"], "--expected-generation", old_token["generation_id"],
                   "--expected-snapshot", old_token["snapshot_id"])

    closed = finish(token)
    assert closed["data"]["status"] == "CLOSED", closed
    assert closed["data"]["removed_files"] == len(tick_files)
    assert closed["data"]["removed_bytes"] == tick_bytes
    assert closed["data"]["raw_tick_replay_available"] is False
    assert not list(tick_dir.iterdir())
    assert all(sha256_file(p) == digest for p, digest in hashes.items())
    report = json.loads(Path(first["data"]["report"]["report_json"]).read_text(encoding="utf-8"))
    assert report
    retired = cli("exec", *replay_args)
    assert "TICK_DATA_PURGED_BY_RETENTION" in json.dumps(retired), retired
    assert finish(token)["data"]["already_closed"] is True

    second = cli("once", "--end", "2025-01-15T15:50:00Z")
    assert second["data"]["status"] in ("OK", "PARTIAL"), second
    token2 = second["data"]["finish_token"]
    assert token2["generation_id"] != token["generation_id"]
    assert token2["status"] == "REPORT_COMMITTED"
    assert list(tick_dir.glob("*.npz"))
    checkpoint = json.loads((tick_dir / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["tick_generation_id"] == token2["generation_id"]
    assert finish(token)["data"]["reason"] == "STALE_FINALIZATION_REQUEST"
    assert list(tick_dir.glob("*.npz"))
    retired_again = cli("exec", *replay_args)
    assert "TICK_DATA_PURGED_BY_RETENTION" in json.dumps(retired_again), retired_again
