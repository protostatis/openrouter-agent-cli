Fix the session report produced by `python3 run_sessions.py events.jsonl`.

The input is JSONL. Each line has a `user` string and an ISO-8601 `ts`
timestamp that may include `Z` or a numeric UTC offset. Do not modify
`events.jsonl` or `run_sessions.py`.

Implement these rules:

- Parse timestamps as instants and normalize them to UTC; do not discard an
  offset.
- Group events by user and order each user's events by their UTC timestamp,
  regardless of input order.
- The first event starts a session. Start a new session only when the gap from
  the previous event is greater than 30 minutes. A gap of exactly 30 minutes
  stays in the same session.
- Print one JSON object per session with exactly these keys: `user`, `start`,
  `end`, and `events`. Format `start` and `end` as UTC
  `YYYY-MM-DDTHH:MM:SSZ` strings.
- Print sessions ordered by `user`, then by UTC `start`. Do not print other
  output.

The bug may span more than one application file.
