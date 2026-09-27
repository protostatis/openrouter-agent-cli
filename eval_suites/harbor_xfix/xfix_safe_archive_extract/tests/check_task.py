import os
import stat
import subprocess
import sys
import tempfile
import zipfile


def make_zip(directory, members):
    path = os.path.join(directory, "archive.zip")
    with zipfile.ZipFile(path, "w") as archive:
        for name, data, mode in members:
            info = zipfile.ZipInfo(name)
            if mode is not None:
                info.external_attr = (mode | 0o777) << 16
            archive.writestr(info, data)
    return path


def run(members, expected_output, expected_code=0):
    with tempfile.TemporaryDirectory() as directory:
        archive = make_zip(directory, members)
        destination = os.path.join(directory, "out")
        before = set(os.listdir(directory))
        proc = subprocess.run(
            ["python3", "run_extract.py", archive, destination],
            cwd="/app",
            capture_output=True,
            text=True,
        )
        if proc.returncode != expected_code or proc.stdout.strip() != expected_output:
            print("wrong extractor result:", proc.returncode, repr(proc.stdout), repr(proc.stderr))
            sys.exit(2)
        return directory, destination, before, proc


with tempfile.TemporaryDirectory() as directory:
    archive = make_zip(
        directory,
        [("docs/", b"", None), ("docs/readme.txt", b"hello", None), ("empty/", b"", None)],
    )
    destination = os.path.join(directory, "out")
    proc = subprocess.run(
        ["python3", "run_extract.py", archive, destination],
        cwd="/app",
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or proc.stdout.strip() != "extracted 1 files":
        print("valid archive failed:", proc.returncode, proc.stdout, proc.stderr)
        sys.exit(2)
    if open(os.path.join(destination, "docs", "readme.txt")).read() != "hello":
        print("valid file was not extracted")
        sys.exit(2)


def expect_rejected(members, reason):
    with tempfile.TemporaryDirectory() as directory:
        archive = make_zip(directory, members)
        destination = os.path.join(directory, "out")
        before = set(os.listdir(directory))
        proc = subprocess.run(
            ["python3", "run_extract.py", archive, destination],
            cwd="/app",
            capture_output=True,
            text=True,
        )
        if proc.returncode != 2 or proc.stdout.strip() != f"error:{reason}":
            print("wrong rejection:", proc.returncode, repr(proc.stdout), repr(proc.stderr))
            sys.exit(2)
        if os.path.exists(destination) or set(os.listdir(directory)) != before:
            print("rejected archive changed the destination")
            sys.exit(2)


expect_rejected([("/absolute.txt", b"x", None)], "absolute_path")
expect_rejected([("safe/../escape.txt", b"x", None)], "path_traversal")
expect_rejected([("link", b"target", stat.S_IFLNK)], "symlink")
expect_rejected([("a//b.txt", b"one", None), ("a/b.txt", b"two", None)], "duplicate_path")
expect_rejected([("file", b"x", None), ("file/child.txt", b"y", None)], "path_conflict")
expect_rejected([("dir/", b"", None), ("dir", b"x", None)], "path_conflict")
print("verified")
