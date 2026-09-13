# Model prices

**Verify before use.** These are snapshots, not truth. Vendors change prices and add
tiers. Fetch the vendor page, then fill in what you found.

Prices are USD per million tokens.

## As of 2026-09

| model | input | output | cache read | cache write | source |
|---|---|---|---|---|---|
| Claude Opus 5 | 5.00 | 25.00 | 0.50 | 6.25 (5m) / 10.00 (1h) | platform.claude.com/docs/en/about-claude/pricing |

## Canonical pricing pages

- Anthropic — https://platform.claude.com/docs/en/about-claude/pricing
- OpenAI — https://openai.com/api/pricing
- Google Gemini — https://ai.google.dev/pricing
- DeepSeek — https://api-docs.deepseek.com/quick_start/pricing
- xAI — https://docs.x.ai/docs/models
- Moonshot Kimi — https://platform.moonshot.cn/docs/pricing
- Zhipu GLM — https://open.bigmodel.cn/pricing

## What actually matters to the calculation

1. **Cache read multiplier.** Almost universally `0.1x` input. This is the dominant
   input to the answer.
2. **Cache write multiplier.** `1.25x` for short TTL, `2x` for long TTL at Anthropic;
   some vendors charge nothing for writes. Pass `--write-mult 0` in that case.
3. **Output:input ratio.** Varies widely — 3x to 5x is common but not a rule. It sets the
   fixed compaction cost `K`, so get it right rather than assuming.
4. **No prompt caching at all.** Pass `--prompt-mult 1.0`. Holding becomes 8-10x more
   expensive and the optimal trigger drops a long way.
