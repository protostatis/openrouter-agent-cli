Fix the configuration loader used by `python3 run_config.py`.

The sources are applied in this exact order, with later sources overriding
earlier sources: `defaults.json`, then `config.json`, then environment
variables, then command-line flags. The environment names are
`APP_ENDPOINT`, `APP_WORKERS`, `APP_DEBUG`, and `APP_RETRIES`. The command-line
flags are `--endpoint=VALUE`, `--workers=VALUE`, `--debug=VALUE`, and
`--retries=VALUE`.

The final JSON must contain exactly `endpoint`, `workers`, `debug`, and
`retries`. `endpoint` is a non-empty string, `workers` is an integer from 1
through 64, `debug` accepts `true`, `false`, `1`, `0`, `yes`, or `no`
(case-insensitive), and `retries` is an integer from 0 through 10. JSON
booleans are also valid for `debug`. The value `false` and the number `0` are
valid values and must not be discarded as if they were absent.

For valid input, print only the final JSON object. For an unknown flag or an
invalid value, print no normal output and exit with status 2. Do not modify
`defaults.json` or `config.json`.
