# Uncover: Simple Proposal

**Status:** Concept proposal
**Date:** 2026-08-23

## 1. Product Thesis

Uncover gives software agents a local-first service that turns live-web questions into bounded, source-grounded, machine-actionable answers—without requiring a full browser on the default path.

The internet is the changing knowledge corpus. `pyunbrowser`/Unbrowser is the live discovery layer. The agent plans the investigation, evaluates evidence, and decides what to do next.

Uncover is not another generic deep-research report generator.

## 2. The Problem

Agents often need current information before making a decision, but they have three weak options:

- rely on stale model knowledge;
- call a search API and perform all evidence handling themselves; or
- call a deep-research API and receive a polished report whose claims may still be weakly supported.

The local CLI already demonstrates a useful pattern: the agent can form queries, discover live pages, navigate sources, and continue reasoning. The missing product boundary is a predictable evidence contract that another agent can call and inspect.

Our Tavily smoke test confirms that research APIs are useful, but also exposes the gap: Tavily returned a conventional cited report with several questionable claims and mixed-quality sources. Citation presence is not enough.

## 3. Target User and Job

**Primary caller:** another software agent.

**Job:** “Before I answer or act, investigate this question, challenge the obvious interpretation, find relevant supporting and opposing evidence, and tell me what remains uncertain.”

Humans are reviewers of the evidence, not the initial interface target.

## 4. Proposed MVP

### Input

- question;
- optional draft answer or claims;
- decision context and constraints;
- effort, time, or cost budget;
- optional trusted, required, or excluded domains.

### Workflow

1. Plan a bounded set of searches and sub-questions.
2. Discover, fetch, and extract current sources through Unbrowser.
3. Deduplicate and rank sources by relevance, authority, diversity, and freshness.
4. Extract evidence and check whether sources actually support the claims.
5. Identify contradictions, missing evidence, and unresolved uncertainty.
6. Return structured results so the calling agent can decide or act.

### Output

- direct conclusion or recommendation;
- supporting, contradicting, qualifying, and unresolved findings;
- claim-level citations and evidence excerpts;
- source metadata and quality warnings;
- missing evidence and uncertainty;
- suggested claims to add, weaken, or remove;
- execution trace: queries, pages considered, exclusions, latency, and cost;
- Markdown rendering for human inspection.

## 5. Product Surface

Use one canonical boundary:

```text
Agent or CLI client
        ↓
HTTP/OpenAPI Uncover service
        ↓
Bounded research orchestrator
        ↓
Unbrowser live discovery
        ↓
Evidence records and claim checks
        ↓
Structured result
```

Initial interface:

```http
POST /v1/uncover
GET  /v1/uncover/{job_id}
```

The POST operation should support asynchronous execution for longer research tasks. The existing CLI becomes a thin reference client, debugging interface, and integration harness—not a separate product contract.

Add an MCP adapter early around the same operations. Defer A2A until there is demonstrated demand.

## 6. Why Browserless Discovery Matters

Browserless-by-default operation is an important platform advantage:

- smaller and simpler deployments;
- faster cold starts;
- lower memory usage;
- fewer browser-process and sandboxing concerns;
- easier operation in restricted or unprivileged environments;
- simpler horizontal scaling.

This is not, by itself, a defensible product moat. Other providers may also hide browserless infrastructure, and some authenticated or heavily client-rendered sites may still require escalation. The product should claim **browserless by default**, not “never needs a browser.”

## 7. Explicit Non-Goals

The MVP will not:

- maintain a proprietary index of the entire web;
- promise complete web coverage;
- support login flows or authenticated browsing;
- expose broad autonomous web actions;
- provide shell access from the research service;
- require Chromium as a default dependency;
- claim that citations guarantee correctness;
- implement A2A before the core workflow is validated.

## 8. Security Boundaries

- Treat all web content as untrusted data and possible prompt injection.
- Keep SSRF protections, including redirect and response-limit validation, in the discovery layer.
- Do not allow web content to gain tool, shell, or policy authority.
- Run the service unprivileged with restricted filesystem access.
- Keep model and web requests explicit; “local-first” does not mean all data stays local.
- Keep browser escalation, if later added, isolated and optional.

## 9. Validation Plan

Before production implementation, create a blinded benchmark of approximately 30–50 current, multi-source agent decision tasks.

Compare:

- current local CLI baseline;
- Tavily Research;
- You.com Research;
- OpenAI Deep Research or equivalent available baseline.

Primary metric: whether a downstream agent completes the decision task correctly.

Secondary metrics:

- citation entailment and coverage;
- source authority and diversity;
- freshness and browserless page coverage;
- latency, cost, and failure rate.

### Continue if

Uncover materially improves downstream task success, or reaches comparable quality with a clearly better local-control, deployment, or cost profile.

### Stop or narrow scope if

- two tuning rounds produce no meaningful advantage;
- output quality remains citation-heavy but weakly supported;
- browser fallback is required too frequently; or
- agents do not use the evidence to make better decisions.

## 10. Immediate Next Step

Define the benchmark task set and scoring rubric. Do not begin production implementation until the benchmark can falsify the hypothesis that Uncover adds value beyond a capable agent plus an existing research API.
