import sys
import zipfile

from extract_archive import extract


try:
    count = extract(sys.argv[1], sys.argv[2])
except (ValueError, zipfile.BadZipFile) as exc:
    print(f"error:{exc}")
    raise SystemExit(2)
print(f"extracted {count} files")
