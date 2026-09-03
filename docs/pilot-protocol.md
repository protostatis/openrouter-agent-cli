# Pilot Protocol — Does the Product Have a User?

**Status:** written 2026-09-03. This is the current milestone defined in
`docs/roadmap.md`. It is a product test, not an evaluation experiment:
pilot results stay out of the frozen evaluation records and are never pooled
with experiment outcomes.

## The decision being made

Continue as a developer product, narrow the project to an evaluation/research
tool, or enter maintenance.

## The target user

Developers who want to try several OpenRouter models on bounded repository
tasks while keeping explicit acceptance evidence — a command that must pass
before the agent's answer is accepted.

## What a session is

One real bounded task on the user's own repository, with an acceptance command
the user chooses. We observe and record; we do not steer the work. For each
session, record:

- time from install to first useful result;
- how many approvals were asked and granted;
- how the user reviewed the changes (this is a key probe for diff review);
- the final state: verified, failed, or not verified;
- how a failure or a blocked step was recovered;
- what the user says they would use the tool for next; and
- whether the user would choose this tool or an alternative for the same task.

## Sessions

Six observed sessions with three non-author users, two tasks each. If only
single-task users are available, six different users each doing one task is
acceptable — say which was used. The author's own sessions do not count toward
the decision; they only find obvious friction before recruiting.

## Alternatives we compare against

Aider (configured with OpenRouter), Claude Code, and Codex. The comparison is
not feature counts; the question is: given this task, which tool would this
user choose, and why.

## Continuation thresholds

Continue product investment only if all of these hold:

- at least two users complete a genuinely useful task that the acceptance
  command verified;
- at least two users can explain correctly what verified, failed, and
  not-verified mean;
- at least two users return for a second task without being asked; and
- the session logs name a repeated friction point clearly enough to choose the
  next smallest improvement.

## Stop conditions

- No user returns for a second task, or every user would choose an
  alternative without personal help: stop building features and make the
  narrow-or-maintain decision.
- Three willing users cannot be found after about ten direct invitations and
  two public demonstrations: treat demand and positioning, not missing
  features, as the problem.

## Time-box and order

1. Release hygiene, capped at two focused days: register the PyPI trusted
   publisher, publish v0.2.1 release notes, replace the pre-public checklist
   with a repeatable one.
2. Sign off this protocol.
3. Recruit three non-author users.
4. Run the six sessions and write the session logs.
5. Write the dated decision: continue, narrow, or stop.

Pilot budget: 2–3 elapsed weeks, 4–6 focused operator days.

## What we produce

- this signed-off protocol;
- six session logs; and
- a dated decision document referencing the logs and the continuation
  thresholds above.