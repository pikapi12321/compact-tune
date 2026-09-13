# compact-tune

An agent skill that answers one question with arithmetic instead of folklore:

> At what context length should this conversation be compacted so it costs the least?

The usual guesses — "as late as possible", "whenever the window fills" — are both wrong
for most setups. Compaction is an inventory problem. Carrying context costs money on
every single API call; compacting costs a fixed fee once. The cheapest trigger balances
them, and it lands at a square root:

```
L* = B + sqrt( 2g(K + aB) / a )
```

On a real 40,000-call coding corpus (Claude Opus 5, 98.5% cache hit rate), the optimum
came out at **107k tokens** while the agent was actually compacting at **267k** — a 55%
overspend on context, worth roughly $1,400 per month at that volume.

## What it does

1. Asks which model you run on and looks up current token prices.
2. Samples your agent's own transcripts for growth rate, base context size, summary size
   and cache hit rate.
3. Solves for the optimal trigger, a ±3% tolerance band, and a cost curve.
4. Reports the overspend of your current setting, plus the quality tradeoff that money
   alone does not capture.

Read-only. It never touches your agent's settings.

## Install

Copy `compact-tune/` into your agent's skills directory:

- Claude Code — `~/.claude/skills/`
- Other agents — wherever that agent loads skills from

Then ask it: *"when should I be compacting?"*

## Standalone use

The script runs on its own, no agent required. Python 3.9+, stdlib only.

```bash
# measure your history
python3 scripts/compact_tune.py sample --days 30 --out params.json

# solve
python3 scripts/compact_tune.py solve --params params.json \
    --price-in 5 --price-out 25 --model "Claude Opus 5" --window 300000
```

```
  OPTIMAL TRIGGER        107,055 tok
  cost at optimum        $0.0680 /call   (45 calls/cycle)
  within +3%              91,055 - 129,555
  CURRENT TRIGGER        267,440 tok  -> $0.1053/call  (+54.8%)

  cost curve ($/call, lower is better)
      63,000  ########################## $0.1174  +72.6%
      81,000  #################          $0.0750  +10.3%
     107,055  ###############            $0.0680   +0.0%  <- optimum
     134,000  ################           $0.0708   +4.0%
     171,000  #################          $0.0787  +15.7%
     236,000  #####################      $0.0962  +41.4%
     267,440  #######################    $0.1053  +54.8%  <- current
```

No history? Use a measured profile instead:

```bash
python3 scripts/compact_tune.py solve --preset coding-heavy --price-in 3 --price-out 15
```

## Other agents

Claude Code transcripts work out of the box and are the format validated against real
billing. Any other agent that logs JSONL with per-call token usage works through the
generic adapter:

```bash
python3 scripts/compact_tune.py sample --source generic \
  --root '~/.someagent/sessions/**/*.jsonl' \
  --map input=usage.prompt_tokens,read=usage.cached_tokens,output=usage.completion_tokens
```

Field names are dotted paths into each JSON line. Recognized keys: `input`, `read`,
`write_short`, `write_long`, `output`, `id`.

Adapters for more agents are welcome — see `parse_claude_code` for the shape.

## Three results that surprise people

**A high cache hit rate argues for compacting *earlier*, not later.** Cheap reads do not
make a long context free; they make the fixed compaction fee relatively expensive to
avoid, and holding still scales linearly with length.

**Compacting early is punished much harder than compacting late.** The curve is steep on
the left and shallow on the right. When the parameters are uncertain, sit above the
optimum.

**At a very late trigger, almost none of the cost is compaction.** In the corpus above,
95% of the spend was re-reading a bloated context, and 5% was the compaction itself.
Optimizing the summarizer is the wrong lever.

## Method

Full derivation, assumptions and validation in [`reference/model.md`](reference/model.md).

## License

MIT
