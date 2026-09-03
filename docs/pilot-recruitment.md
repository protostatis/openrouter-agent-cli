# Pilot Recruitment Materials

**Status:** drafts for the pilot defined in `docs/pilot-protocol.md`
(signed off 2026-09-03). The operator sends these; the assistant wrote the
wording. Replace the bracketed placeholders before sending.

## Direct invitation (for about ten developers)

Subject: want to try a terminal coding agent with a hard "done" check?

Hi [name],

I've been building a small terminal coding agent (openrouter-agent-cli) that
runs against any OpenRouter model and has an unusual rule: before it says
"done," it runs a command you choose — your acceptance check — and reports the
outcome honestly as verified, failed, or not verified. If the check fails it
gets one repair attempt, never an infinite loop.

I'm running a short pilot and would like to watch you use it for one or two
real tasks on your own repository, about 30–60 minutes each. You pick the task
and the acceptance command; I observe and take notes, I don't steer. You keep
whatever it produces. This is product feedback for me, not a benchmark.

Setup is one command: `pip install openrouter-agent-cli`. You need an
OpenRouter API key if you don't already have one (free tiers exist).

Want to try it? If yes, I'll send a two-minute setup note and we book a slot.

One honest disclosure: the tool runs shell commands on your machine behind
permission prompts — treat it like any agent you let run locally.

## Public demonstration — short (X / Bluesky / Mastodon)

Terminal coding agent that refuses to claim "done" without proof. You give it a
task and an acceptance command; it runs your check before accepting its own
answer, reports verified / failed / not-verified, allows one repair, never
loops. Any OpenRouter model, honest cache accounting, `pip install
openrouter-agent-cli`. Running a user pilot — DM me to try it on a real repo.

## Public demonstration — longer (dev forum, newsletter, or blog)

A terminal agent for OpenRouter models with a completion rule most agents
don't have: it will not claim the work is done until a command you choose
actually passes. You define done with an acceptance command (for example,
`pytest tests/test_auth.py`); the tool runs it at the completion boundary and
reports one of three honest states — verified, failed, or not verified. A
failing check earns exactly one additional model response, then it stops with the evidence
instead of looping.

It also keeps cache and context claims honest: it reports provider cache
counters only when the provider actually exposes them.

It is released on PyPI (`pip install openrouter-agent-cli`), works with any
OpenRouter model, and I am running a short observed pilot: three developers,
six real tasks on their own repositories. If you want early influence on the
roadmap and a tool that will actually tell you when it's done, this is the
time to try it.

## Setup note (sent after someone accepts)

```bash
pip install openrouter-agent-cli
export OPENROUTER_API_KEY=sk-or-...
openrouter-agent --workdir ~/your-repo \
  --task "describe the task" \
  --verify-command "the acceptance command"
```

Or start it and use the slash commands at runtime: `/task`, `/verify`,
`/check`, `/status`. The self-test (`openrouter-agent-self-test`) runs without
an API key if you want to see the machinery first.