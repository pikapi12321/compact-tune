---
name: compact-tune
description: >
  Compute the context length at which compacting/summarizing an agent conversation is
  cheapest, from that agent's own transcript history plus the model's token prices.
  Reports an optimal trigger point, a tolerance band, a cost curve, and the overspend of
  the current setting. Use when the user asks when to compact, where to set an
  auto-compact threshold, why long contexts cost so much, how to cut token spend on long
  sessions, or invokes /compact-tune.
---

# compact-tune

Compaction is an inventory problem. Holding context costs money every call; compacting
costs a fixed fee once. The cheapest trigger point balances the two — a square-root
optimum, not "as late as possible".

```
f(L) = a(B+L)/2 + g(K + aL)/(L-B)        $/call when compacting at length L
L*   = B + sqrt( 2g(K + aB) / a )        the optimum
```

`a` effective $/token held per call · `B` context right after a compaction (system
prompt + tools + summary) · `g` tokens added per call · `K` fixed cost of one compaction
· `L` trigger length.

## Files

Paths below are relative to the skill root. When this skill was fetched from a URL rather
than installed, resolve them against
`https://raw.githubusercontent.com/pikapi12321/compact-tune/main/` and substitute the
temp path you downloaded the script to for `scripts/compact_tune.py`.

## Modes

- **default** — result only: parameters, optimum, band, curve, recommendation.
- **`--explain`** — additionally derive the formula against the user's real numbers.
  Read `reference/model.md` and walk it with their values substituted.

## Steps

### 1. Establish the model and its prices

Ask if unknown — pricing is the one input that cannot be inferred:

> Which model does this agent run on? I need its input and output token prices.

Then look up current prices from the vendor's own pricing page. Never quote prices from
memory; they change. `reference/prices.md` holds known values with an as-of date and the
canonical URLs — treat it as a starting point to verify, not a source of truth.

Two facts hold across nearly all vendors: **cache reads cost ~0.1x base input**, and the
**output:input ratio varies a lot** (3x to 5x is common, but check). If the model has no
prompt caching, pass `--prompt-mult 1.0`.

### 2. Measure parameters from history

```bash
python3 scripts/compact_tune.py sample --days 30 --out /tmp/params.json
```

Defaults to Claude Code transcripts (`~/.claude/projects/*/*.jsonl`), the one format
verified against real billing. For another agent, point at its JSONL and map the usage
fields:

```bash
python3 scripts/compact_tune.py sample --source generic \
  --root '~/.codex/sessions/**/*.jsonl' \
  --map input=usage.prompt_tokens,read=usage.cached_tokens,output=usage.completion_tokens,id=response_id
```

**No history, or sampling fails** — fall back to a preset and say so plainly:

> No transcript history found, so these numbers come from a measured coding-agent
> profile, not your own usage. Treat the optimum as a starting point.

Presets: `coding-heavy` · `coding-light` · `chat`.

### 3. Solve

```bash
python3 scripts/compact_tune.py solve --params /tmp/params.json \
  --price-in 5 --price-out 25 --model "Claude Opus 5" --window 300000
```

Use `--g-mode mean` (default) for mixed workloads; `--g-mode p75` when tool output
dominates. Add `--json` when you need the intermediate terms for `--explain`.

### 4. Report

Use this template. Keep the script's numbers verbatim; the prose is yours.

```
## Optimal compaction point: {L*} tokens

{one sentence: what this means for their setup and what it saves}

### Measured from your history
| parameter | value | note |
|---|---|---|
| growth per call | {g} | {p50/mean/p75 used} |
| base after compact | {B} | system prompt + tools + summary |
| cache hit rate | {hit} | effective input price ${a}/MTok |
| compaction cost | ${K} | summary output + re-caching it |
| current trigger | {cur} | {+X% over optimum} |

### Cost curve
{paste the script's curve block verbatim}

### Recommendation
- Set the trigger to **{L*}**. Anywhere in **{band_3pct}** is within 3%.
- {if current is far off: what it costs them per call and over the sampled period}
- Compacting early is punished harder than compacting late — when unsure, sit right of
  the optimum.
- Cost is not the only axis: {calls_per_cycle} calls per cycle means
  {compactions per 1000 calls} compactions, each one losing detail and costing wall time.
```

Always close with the non-cost tradeoff. A recommendation that only counts dollars is
incomplete.

## Judgment

- **Cache hit rate drives everything.** At 98% hits `a` is ~0.13x base input and the
  optimum lands near 2x the base size. With no caching `a` is 8x higher, holding
  dominates, and the optimum drops sharply. Check hit rate before anything else.
- **The curve is steep left, shallow right.** +3% costs a wide band above the optimum but
  a narrow one below. Round up.
- **If `L*` exceeds the context window**, the answer is "compact at the window" — the
  model is telling you holding is cheap relative to compacting for this workload.
- **Growth `g` is heavy-tailed.** Median and mean differ ~1.6x in real coding sessions.
  Report which one drove the answer.
- The script is read-only and never changes agent settings. Recommend; let the user act.
