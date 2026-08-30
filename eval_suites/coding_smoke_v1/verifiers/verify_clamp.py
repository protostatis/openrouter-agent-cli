#!/usr/bin/env python3
"""Verifier for the clamp task. argv[1] = agent workspace. 0=pass, 2=fail."""
import sys
from pathlib import Path

def main() -> int:
    workspace = Path(sys.argv[1])
    src = workspace / "clamp.py"
    test = workspace / "test_clamp.py"
    if not src.is_file():
        print("missing clamp.py"); return 2
    proc = subprocess_ok(workspace)
    if not proc:
        print("clamp() behavior wrong"); return 2
    if not test.is_file():
        print("missing test_clamp.py"); return 2
    content = test.read_text(encoding="utf-8")
    if "clamp(5, 1, 3) == 3" not in content or "clamp(0, 1, 3) == 1" not in content:
        print("test_clamp.py missing required assertions"); return 2
    print("clamp verified"); return 0

def subprocess_ok(workspace: Path) -> bool:
    import subprocess
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s'); from clamp import clamp; "
         "assert clamp(5, 1, 3) == 3; assert clamp(0, 1, 3) == 1; "
         "assert clamp(2, 1, 3) == 2" % workspace],
        capture_output=True, text=True, timeout=20,
    )
    return proc.returncode == 0

if __name__ == "__main__":
    raise SystemExit(main())
