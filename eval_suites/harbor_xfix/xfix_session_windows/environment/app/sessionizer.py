from datetime import datetime, timedelta


def _parse(ts):
    # The current implementation treats the displayed clock time as UTC.
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)


def summarize(events):
    grouped = {}
    for event in events:
        grouped.setdefault(event["user"], []).append(event)

    sessions = []
    for user, user_events in grouped.items():
        ordered = sorted(user_events, key=lambda event: event["ts"])
        current = None
        for event in ordered:
            when = _parse(event["ts"])
            if current is None or when - current["last"] >= timedelta(minutes=30):
                current = {"user": user, "start": when, "end": when, "events": 1, "last": when}
                sessions.append(current)
            else:
                current["end"] = when
                current["last"] = when
                current["events"] += 1

    for session in sessions:
        session.pop("last")
        session["start"] = session["start"].strftime("%Y-%m-%dT%H:%M:%SZ")
        session["end"] = session["end"].strftime("%Y-%m-%dT%H:%M:%SZ")
    return sorted(sessions, key=lambda session: (session["user"], session["start"]))
