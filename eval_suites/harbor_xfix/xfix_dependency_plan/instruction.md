Fix the dependency planner run with `python3 run_plan.py jobs.json`.

The input is a JSON array of objects with a unique string `name` and a
`depends_on` array of job names. A dependency means that the named dependency
must appear earlier in the output. Return a valid dependency order for every
job. Whenever several jobs are ready, choose the lexicographically smallest
job name. Include jobs in disconnected components too.

If any dependency names a job that is not present, print exactly
`{"error":"missing_dependency"}` and exit with status 2. Otherwise, if any
cycle exists anywhere in the graph, print exactly `{"error":"cycle"}` and
exit with status 2. Do not print a partial order for an error. For a valid
graph, print only one JSON array of job names and exit with status 0. Do not
modify `jobs.json`.
