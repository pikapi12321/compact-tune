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

## Usage

You only need this answer once, so there is nothing to install. Paste this to your agent:

> Read https://github.com/pikapi12321/compact-tune — fetch `SKILL.md` and everything under
> `reference/`, download `scripts/compact_tune.py` into a temp directory, then follow
> SKILL.md to work out where I should be compacting my context.

Your agent takes it from there: it asks which model you run on, looks up current token
prices, samples your own transcripts, and reports the optimal trigger point.

Nothing is installed and nothing persists. The script lands in a temp directory, reads
your transcripts without writing to them, and never touches your agent's settings.

Works on Claude Code transcripts out of the box, on any other agent that logs per-call
token usage, and — with measured fallback profiles — on no history at all.

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

## "But long tasks need long context"

This is the usual objection to a tool that says compact at 107k instead of 267k, and it
rests on a conflation worth separating:

**Long-horizon work needs persistent state. That is not the same as a long context
window.** The two got equated because the window is where state lived by default. Window
size is a number on a spec sheet; effective length has to be measured.

The measurements are unusually consistent:

| finding | source |
|---|---|
| Models advertising 128k hold up to roughly **32k** before falling below baseline. At 128k, multi-key retrieval scores 20% and common-word extraction 0.8%. | [RULER](https://arxiv.org/abs/2404.06654) |
| **18 of 18** frontier models degrade monotonically with input length — including on trivial text replication, with task difficulty held constant. One semantically similar distractor is enough to measurably lower accuracy. | [Context Rot](https://www.trychroma.com/research/context-rot) |
| Structured memory scores **61.2%** against a full-context baseline's **55.0%**, using 95% fewer tokens per query. A 20B model with external memory beats its own full-context baseline by **44.6 points**. | [MAGMA](https://arxiv.org/pdf/2601.03236), [Hindsight](https://arxiv.org/pdf/2512.12818) |
| Summary artifacts averaging **217 tokens** beat full **25,634-token** trajectories on task resolution. | [SWE Context Bench](https://arxiv.org/abs/2602.08316) |
| Production agents rewrite the plan file to the *end* of context every turn, deliberately pushing the goal back into recent attention and out of the middle. | [Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) |

### The strongest objection, and why it agrees

On BrowseComp, **token usage alone explains 80% of performance variance**, and a
multi-agent system beat single-agent Claude Opus 4 by 90.2% while burning ~15x the tokens
([Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)). Spending
tokens buys capability. That is real and it is not a small effect.

But look at where those tokens went: across many short, focused subagent contexts, not
down one long window. That sharpens the thesis instead of refuting it.

> Total tokens spent buys capability. Context length spends them badly.

### Where this genuinely breaks

Externalization is a skill, not a free win.

- **Compaction only helps when the right thing survives it.** Indiscriminate compaction and
  free retrieval bring limited gains and can hurt outright
  ([SWE Context Bench](https://arxiv.org/abs/2602.08316)).
- **Splitting context fragments decisions.** Dispersed decision-making is a documented
  failure mode — agents play telephone with whatever nobody wrote down
  ([Cognition](https://cognition.com/blog/dont-build-multi-agents)).
- **Open deliberation resists externalization.** Much of the value in a long design
  discussion sits in the rejected branches and the reasons for rejecting them — precisely
  what a summarizer drops while dutifully keeping the conclusion. Write those down as you
  go, or keep the context.

So the rule is not "short context good". It is: **anything you would be sad to lose
should exist outside the context window.** Once that holds, the cheapest trigger point and
the most accurate one are the same number — which is not how cost optimization usually
goes.

## Method

Full derivation, assumptions and validation in [`reference/model.md`](reference/model.md).

## License

MIT
