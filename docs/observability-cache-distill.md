# Observability and KV-Cache Prediction

**Status:** distilled 2026-09-03 from the observability/cache work by an
advisor review of the session. Plain language; numbers explained.

## 1. What the observability work established

We built a capture proxy that records the complete decoded request and response
body for every model call. It decompresses gzip responses and reads streamed
Server-Sent Events so it can recover the provider's final usage counters.

This provides direct evidence of what each coding-agent harness sends to the
model: system instructions, conversation messages, tool definitions, and model
responses. It is stronger evidence than configuration files because it records
the request that actually crossed the network.

The first comparison exposed an unfair test condition. OpenCode inherited the
operator's global instructions, skills, and Model Context Protocol tools. This
expanded its tool list from 10 tools to 66 and increased each request from about
35 KB to as much as 97 KB. Isolated configuration directories removed that
outside configuration.

With isolated configurations:

- Our harness exposed 7 tools and sent requests of about 5–21 KB.
- OpenCode exposed 10 tools and sent requests of about 35–41 KB.
- Pi exposed 4 tools and sent requests of about 6–15 KB.
- Before isolation, OpenCode sent about 82–97 KB per request with 66 tools.

The captures also revealed the real verification instructions:

- OpenCode explicitly says to run tests or checks when relevant and feasible.
  This is guidance, not a requirement, so the model can still finish without
  checking its work.
- Pi has no explicit verification instruction and exposes four tools.
- Our harness exposes seven tools and leaves trustworthy verification to an
  external acceptance check rather than the model's own judgment.

Provider-reported token accounting now works for all three harnesses. The
capture proxy reads ordinary JSON usage data and the final usage record from
streamed responses.

In the clean four-task baseline:

- Pi used about 13,000–21,000 tokens and was consistently the cheapest.
- OpenCode used about 18,000–65,000 tokens and varied the most.
- Our harness used about 14,000–15,000 tokens on the local repair tasks and
  about 46,600 tokens on the web task.
- These were single attempts, so they show direction rather than reliable pass
  rates. Repeated runs are still required.

Sources: `docs/cross-harness-notes.md`, `scripts/capture_proxy.py`,
`scripts/compare_harnesses.py`, and `scripts/isolated_harnesses.sh`.

## 2. Cache-hit predictor concept

A key-value cache, or KV cache, lets a model provider reuse computation for an
unchanged beginning of a request. The harness cannot inspect the provider's
cache before sending, but it can measure whether its own request has a reusable
beginning.

`CacheAwareContext` already records:

- the number of unchanged messages at the beginning of consecutive requests;
- a rough token count for that stable beginning;
- a fingerprint identifying that exact sequence of messages;
- the provider's last reported cached-token count, but only when the response
  explicitly contains one; and
- a reset when conversation history is compacted into a summary.

The predictor could report one of three states:

- **Expected hit:** a sufficiently large prefix is unchanged, its fingerprint
  matches recent requests, and this route recently reported cached tokens.
- **Expected miss:** compaction or an early message change replaced the prefix,
  or the reusable prefix is below the provider's known minimum.
- **Unknown:** the provider does not report cache data, the route changed, the
  previous request is too old, or there is not enough evidence.

A later version could report a probability. That number must be measured from
past results. For example, requests assigned a 70% chance should receive
provider-reported cached tokens about 70% of the time.

The predictor must run before the request. Currently, `observe_request` is
called after the response arrives, so the present implementation measures and
reports facts but does not yet make a before-send prediction.

It should also represent the exact stable request prefix, not only messages.
Tool definitions are a large and usually stable part of coding-agent requests.
Ignoring them would especially misrepresent OpenCode's 35–97 KB requests.

Each prediction should later be compared with:

- whether the provider reported any cached tokens;
- cached tokens divided by total prompt tokens; and
- how many predicted reusable tokens became actual cached tokens.

Those results would test whether the prediction is useful rather than merely
plausible.

The predictor could inform two decisions:

1. **Append or compact:** continue appending when a valuable stable prefix is
   likely to remain cached; compact when context cost or limits outweigh the
   expected cache benefit.
2. **Compare harnesses:** report the proportion of each request that remained
   stable, the proportion actually cached, and the cost when reuse failed.

A larger stable prefix creates more potential savings, but it also costs more
when the provider misses. OpenCode's larger requests therefore make cache
behavior more important, not automatically better.

Sources: `openrouter_agent_cli/cache.py`, `openrouter_agent_cli/cli.py`, and
`docs/long-running-coding-session.md`.

## 3. How capture and prediction fit together

The capture proxy supplies the missing ground truth. Before each model call,
the harness can record its prediction and stable-prefix measurements. After the
call, the proxy captures the provider's actual cached-token counter when one is
present.

Joining these two records creates a test dataset:

- inputs: stable-prefix size and fingerprint, request size, model, provider,
  elapsed time, compaction state, and tool-definition stability;
- prediction: expected hit, expected miss, or unknown;
- result: reported cached tokens and total prompt tokens.

This allows the predictor to be checked separately for each provider and model.
It also turns cache friendliness into a measurable harness comparison rather
than an assumption based only on request size.

## 4. Open questions and prioritized next steps

1. Define a cache hit precisely: any cached token, a minimum cached-token count,
   or a minimum percentage of the prompt.
2. Move stable-prefix measurement to before the request while keeping provider
   cache counters as an after-response observation.
3. Fingerprint the exact serialized cache-relevant prefix, including stable
   tool definitions and system instructions.
4. Add a shared request identifier so predictions and captured responses can be
   joined without relying only on timing.
5. Establish separate rules for each provider and model because cache thresholds,
   routing, and lifetime may differ.
6. Run repeated append-only and post-compaction sessions to collect both hits
   and misses.
7. Measure prediction accuracy and whether reported probabilities match actual
   outcomes.
8. Only then test a compact-now policy against a fixed policy for total cost,
   latency, task success, and lost context.
9. Add cache friendliness to cross-harness reports without treating large
   stable prefixes as inherently good.
10. Protect capture logs: they contain complete prompts, source material, and
    responses, so access, retention, and deletion rules are required.

## Watch-outs

- `CacheAwareContext` currently estimates message tokens using roughly four
  characters per token; that is adequate for a signal, not exact billing.
- Provider routing, cache lifetime, minimum prefix length, and server load
  remain hidden. Therefore "expected hit" must never be presented as
  guaranteed.
- The capture proxy records sensitive full bodies. It is suitable for
  controlled experiments, not unrestricted production logging.
- Git solves prompt version history, but it does not provide runtime cache
  outcomes. The predictor uses network observations rather than replacing Git.