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

## Usage

You only need this answer once, so there is nothing to install. Paste this to your agent:

> Read https://github.com/pikapi12321/compact-tune — fetch `SKILL.md` and everything under
> `reference/`, download `scripts/compact_tune.py` into a temp directory, then follow
> SKILL.md to work out where I should be compacting my context.

Your agent takes it from there: it asks which model you run on, looks up current token
prices, samples your own transcripts, and reports the optimal trigger point.

Nothing is installed and nothing persists. The script lands in a temp directory, reads
your transcripts without writing to them, and never touches your agent's settings.

Claude Code transcripts are read out of the box and are the format validated against real
billing. Any other agent that logs per-call token usage as JSONL works too — your agent
will figure out the field mapping from SKILL.md. No usage history at all is fine: it falls
back to measured workload profiles and tells you it did.

## What you get back

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

Plus the parameters it measured, a recommendation, and the quality tradeoff that money
alone does not capture — a tighter trigger means more compactions, and each one loses
detail.

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
