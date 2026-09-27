def plan(jobs):
    names = {job["name"] for job in jobs}
    remaining = {job["name"]: set(job["depends_on"]) for job in jobs}
    ready = {name for name, dependencies in remaining.items() if not dependencies}
    output = []
    while ready:
        name = max(ready)
        ready.remove(name)
        output.append(name)
        for other, dependencies in remaining.items():
            dependencies.discard(name)
            if not dependencies and other not in output:
                ready.add(other)
    return output
