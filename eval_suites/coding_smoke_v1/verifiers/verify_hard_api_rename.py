#!/usr/bin/env python3
"""Hard task: rename save_note -> write_note everywhere, including the caller
README does not mention."""
import subprocess, sys
from pathlib import Path

def main() -> int:
    workspace = Path(sys.argv[1])
    if not (workspace / "storage.py").is_file():
        print("missing storage.py"); return 2
    stale = []
    for py in workspace.glob("*.py"):
        if "save_note" in py.read_text(encoding="utf-8"):
            stale.append(py.name)
    if stale:
        print(f"stale save_note references remain in: {', '.join(stale)}"); return 2
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s'); "
         "from storage import write_note; "
         "import app, archive; "
         "assert hasattr(archive, 'save_note') is False" % workspace],
        capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        print("modules broken after rename"); return 2
    print("api rename verified (hidden caller updated)"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
