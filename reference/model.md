# Derivation

Walk this with the user's own numbers substituted. Every symbol is measurable.

## Symbols

| symbol | meaning | source |
|---|---|---|
| `B` | context right after a compaction: system prompt + tool schemas + injected files + summary | measured, `base` |
| `g` | tokens added per API call (one call, not one user turn — every tool round trip is a call) | measured, `g_*` |
| `L` | trigger length: compact when context reaches this | the unknown |
| `a` | effective $ per token of context, per call | `price_in x prompt_mult` |
| `K` | fixed cost of one compaction | derived below |

`prompt_mult` is the measured blend of how prompt tokens are actually billed:

```
prompt_mult = (plain x 1.0 + write_short x 1.25 + write_long x 2.0 + read x 0.1) / total
```

At a 98% cache hit rate this lands near 0.13 — context is billed at roughly an eighth of
the sticker input price. That single number moves the answer more than any other.

## One cycle

A cycle runs from one compaction to the next. Context starts at `B`, grows by `g` each
call, ends at `L`. So the cycle is

```
N = (L - B) / g   calls
```

**Holding cost.** Every call re-reads the entire current context. Call `k` costs
`a(B + kg)`. Summing an arithmetic series is `count x average`:

```
a x N x (B + L)/2
```

**Compaction cost.** Once per cycle:

- read the full context one last time — `aL`
- emit the summary — `S x price_out`
- write the new summary into the cache so the next cycle gets hits — `S x price_in x write_mult`

```
K = S x (price_out + price_in x write_mult)
```

The cache-write half is easy to miss and often roughly doubles `K`.

## Per-call cost

```
cycle total = a x N x (B+L)/2 + aL + K

f(L) = a(B+L)/2 + (K + aL)/N
     = a(B+L)/2 + g(K + aL)/(L - B)
       ~~~~~~~~~~   ~~~~~~~~~~~~~~~~
       holding        amortized compaction
```

Holding rises linearly in `L`: a longer leash means a heavier average context on every
call. Amortization falls in `L`: more calls per cycle spread the fixed fee thinner. The
optimum is where their slopes cancel.

Note what drops out: writing the `g` new tokens to cache each call costs the same
regardless of `L`, so it never enters the derivative. Same for normal reply output.

## Optimum

```
d/dL [ (K + aL)/(L - B) ] = [ a(L-B) - (K + aL) ] / (L-B)^2
                          = -(K + aB) / (L-B)^2
```

The `aL` in the numerator cancels, leaving `aB`. So

```
f'(L) = a/2 - g(K + aB)/(L - B)^2 = 0

L* = B + sqrt( 2g(K + aB) / a )
```

Same shape as the economic order quantity formula: fixed cost `K` per order, holding
cost `a` per unit per period. Hence the square root — doubling the growth rate moves the
optimum by only ~1.4x.

## Assumptions

Name these when the answer is close to a decision boundary.

- `g` is treated as constant; in reality it is heavy-tailed (one large file read can add
  50k in a single call).
- Cache hit rate is treated as constant. Long idle gaps expire the cache and multiply `a`
  by up to 8x, which pulls the optimum sharply left.
- Summary size `S` is treated as constant.
- The summary is assumed to fully replace the dropped context — pure money, no quality
  term. More compactions means more information loss. The model cannot price that.
- Batch discounts, off-peak tiers and per-request overheads are ignored.

## Validation

Against a 40,155-call Claude Code corpus (Opus 5, September 2026), the model predicted
$0.1036 of prompt cost per call at the observed 267k trigger. Actual billed prompt cost
was $0.0993 per call — 4% error.
