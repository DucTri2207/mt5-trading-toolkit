import os
import sys
import tempfile
from pathlib import Path

# Isolated store for tests (must be set before quantmt5 is imported).
_TMP = Path(tempfile.mkdtemp(prefix="quantmt5_test_store_"))
os.environ["QUANTMT5_STORE"] = str(_TMP)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def store_dir():
    return _TMP


@pytest.fixture(scope="session")
def xau():
    from quantmt5.detectors import load_symbol
    return load_symbol("XAUUSD")


@pytest.fixture(scope="session")
def xau_catalog(xau):
    from quantmt5.detectors import detect_all
    return detect_all(xau)
