#!/usr/bin/env python3
"""Hard task: make the provided unittest pass WITHOUT modifying it."""
import hashlib, subprocess, sys
from pathlib import Path

TEST_SHA256 = "7b4414e0c5c296303396957b09cc073473c207ccbeb96e9aacee69f8565dac6b"

def main() -> int:
    workspace = Path(sys.argv[1])
    test = workspace / "test_prices_app.py"
    if not test.is_file():
        print("missing test_prices_app.py"); return 2
    digest = hashlib.sha256(test.read_bytes()).hexdigest()
    if TEST_SHA256 != "SET_AT_WRITE_TIME" and digest != TEST_SHA256:
        print("the test file was modified — task requires fixing the source, not the test"); return 2
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "test_prices_app", "-v"],
        cwd=str(workspace), capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        print("test still failing"); return 2
    print("failing-test fix verified (test untouched)"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
