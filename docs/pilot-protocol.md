# Pilot Protocol — Does the Product Have a User?

**Status:** written and signed off 2026-09-03; **deferred** the same day by
the operator pending a product-polish pass (see `docs/roadmap.md` evidence
log). Not recruiting until the polish milestone passes; the commitments below
stand unchanged.

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

## What to watch for in sessions

From the demo review (2026-09-03). Watch for these during the observed
sessions:

1. Whether users can choose a meaningful acceptance command without coaching.
2. Whether users understand that "verified" means "relative to the command
   they chose," not "the whole task is correct."
3. Whether the acceptance boundary changes an outcome or merely repeats a test
   the users already run themselves.
4. Whether users actually use `/diff` to review changes, and whether
   pre-existing changes in their repository confuse them.
5. What users do after a failed or not-verified result.
6. Whether one additional model response (the single repair) feels sufficient
   or arbitrarily restrictive.
7. Whether the permission prompts and host-shell execution undermine trust.
8. Whether model choice through OpenRouter matters enough to outweigh the
   alternatives (Aider, Claude Code, Codex).
9. Whether users return for a second task without being prompted.

Do not over-teach participants with a persuasive demo: give standardized
command-level onboarding, then observe. Otherwise the comprehension threshold
measures recall of the demo rather than whether the product communicates its
states naturally.

## Sign-off record

Signed off 2026-09-03 by the operator. The full twelve-item list was presented
in the roadmap discussion; it is condensed here so a future reader can find
the commitments without that context:

1. The next 2–3 weeks belong to this pilot. The larger verifier experiment,
   containerized execution, diff review, cache work, and any v0.3.0 feature
   release are deferred until the pilot gate is decided.
2. No version bump until the pilot gate passes.
3. The target user is fixed: developers who want to try several OpenRouter
   models on bounded repository tasks while keeping explicit acceptance
   evidence.
4. Comparison set: Aider (with OpenRouter), Claude Code, and Codex.
5. "Narrow to an evaluation tool" is a legitimate, equal-weight outcome.
6. Pilot results are product evidence, never experiment data; they stay out
   of the evaluation records and frozen-run governance.
7. Budget: 2–3 elapsed weeks, 4–6 focused operator days; release hygiene
   capped at 2 days.
8. Continue product investment only if all four thresholds hold: at least 2
   of 3 users complete a genuinely useful verified task; at least 2 explain
   the three states correctly; at least 2 return for a second task unasked;
   and the logs name a repeated friction point.
9. Stop building features if no user returns for a second task or every user
   would choose an alternative without personal help.
10. Treat demand and positioning, not features, as the problem if three
    willing users cannot be found after about ten direct invitations and two
    public demonstrations.
11. Author dogfood sessions do not count toward the decision.
12. The operator does the recruiting; the assistant drafts the invitation and
    demonstration wording.