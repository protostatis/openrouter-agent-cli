import json
import os

from cli import parse_cli


DEFAULTS = json.load(open("defaults.json"))


def _coerce(name, value):
    if name == "endpoint":
        value = str(value)
        if not value:
            raise ValueError("endpoint must be non-empty")
        return value
    if name in {"workers", "retries"}:
        number = int(value)
        upper = 64 if name == "workers" else 10
        lower = 1 if name == "workers" else 0
        if not lower <= number <= upper:
            raise ValueError(f"invalid {name}")
        return number
    if name == "debug":
        return bool(value)
    raise ValueError("unknown key")


def load_config(argv=None):
    result = dict(DEFAULTS)
    result.update(json.load(open("config.json")))

    env_values = {}
    for name in result:
        env_name = "APP_" + name.upper()
        if env_name in os.environ:
            env_values[name] = os.environ[env_name]
    cli_values = parse_cli(argv or [])

    # Environment variables currently override command-line flags.
    for source in (cli_values, env_values):
        for name, value in source.items():
            if value:
                result[name] = _coerce(name, value)
    return {name: _coerce(name, value) for name, value in result.items()}
