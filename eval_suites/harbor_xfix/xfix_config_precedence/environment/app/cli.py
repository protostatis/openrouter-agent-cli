def parse_cli(argv):
    values = {}
    for arg in argv:
        if not arg.startswith("--") or "=" not in arg:
            raise ValueError("invalid flag")
        name, value = arg[2:].split("=", 1)
        if name not in {"endpoint", "workers", "debug", "retries"}:
            raise ValueError("unknown flag")
        if name == "debug":
            values[name] = bool(value)
        else:
            values[name] = value
    return values
