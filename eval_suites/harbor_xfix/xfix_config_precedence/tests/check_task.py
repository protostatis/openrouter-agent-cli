import json
import os
import subprocess
import sys


BASE_ENV = os.environ.copy()
for key in ("APP_ENDPOINT", "APP_WORKERS", "APP_DEBUG", "APP_RETRIES"):
    BASE_ENV.pop(key, None)


def run(args=(), env_values=None):
    env = BASE_ENV.copy()
    if env_values:
        env.update(env_values)
    return subprocess.run(
        ["python3", "run_config.py", *args],
        cwd="/app",
        env=env,
        capture_output=True,
        text=True,
    )


def expect(args, env_values, expected):
    proc = run(args, env_values)
    if proc.returncode != 0:
        print("crashed:", proc.stderr.strip()[-200:])
        sys.exit(2)
    try:
        actual = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print("invalid JSON:", exc)
        sys.exit(2)
    if actual != expected:
        print("wrong config:", actual, "expected:", expected)
        sys.exit(2)


expect(
    (),
    {},
    {"endpoint": "https://file.example", "workers": 8, "debug": True, "retries": 2},
)
expect(
    (),
    {
        "APP_ENDPOINT": "https://env.example",
        "APP_WORKERS": "12",
        "APP_DEBUG": "false",
        "APP_RETRIES": "0",
    },
    {"endpoint": "https://env.example", "workers": 12, "debug": False, "retries": 0},
)
expect(
    ("--endpoint=https://cli.example", "--workers=16", "--debug=no", "--retries=0"),
    {
        "APP_ENDPOINT": "https://env.example",
        "APP_WORKERS": "12",
        "APP_DEBUG": "true",
        "APP_RETRIES": "4",
    },
    {"endpoint": "https://cli.example", "workers": 16, "debug": False, "retries": 0},
)

for args, env_values in (
    (("--workers=0",), {}),
    ((), {"APP_DEBUG": "maybe"}),
    (("--unknown=value",), {}),
):
    proc = run(args, env_values)
    if proc.returncode != 2 or proc.stdout:
        print("invalid input was accepted:", args, env_values, proc.returncode, proc.stdout)
        sys.exit(2)
print("verified")
