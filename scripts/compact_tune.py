#!/usr/bin/env python3
"""compact-tune: find the context length at which compacting is cheapest.

Two subcommands:
  sample  - measure growth rate, base size and cache mix from real agent transcripts
  solve   - given those parameters plus model prices, compute the optimal trigger point

Pure stdlib. No network. Read-only on transcripts.
"""
import argparse, glob, json, math, os, statistics, sys, time
from collections import Counter

# ---------------------------------------------------------------- presets

# Empirical fallbacks. Provenance: 40,155 Claude Code API calls across 66
# sessions, September 2026, Opus-class model, heavy tool use.
PRESETS = {
    "coding-heavy": dict(g_p50=765, g_mean=1260, g_p75=1440, g_p90=2504,
                         base=55000, summary=21748, prompt_mult=0.128,
                         write_mult=2.0, note="tool-heavy coding agent"),
    "coding-light": dict(g_p50=500, g_mean=800, g_p75=1000, g_p90=1800,
                         base=35000, summary=15000, prompt_mult=0.15,
                         write_mult=1.25, note="mostly edits, few large tool reads"),
    "chat":         dict(g_p50=350, g_mean=550, g_p75=700, g_p90=1200,
                         base=12000, summary=8000, prompt_mult=0.20,
                         write_mult=1.25, note="conversational, little tool output"),
}

# Cache multipliers relative to base input price. Near-universal across vendors
# that offer prompt caching: read is ~0.1x. Write multiplier varies (1.25x short
# TTL, 2x long TTL); some vendors charge 0 for writes.
READ_MULT = 0.1


def dig(obj, path):
    for k in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def pct(xs, p):
    if not xs:
        return 0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * (len(xs) - 1)))]


# ---------------------------------------------------------------- sampling

class Call:
    __slots__ = ("ctx", "plain", "w_short", "w_long", "read", "out", "rid", "fresh")

    def __init__(self, plain, w_short, w_long, read, out, rid):
        self.plain, self.w_short, self.w_long = plain, w_short, w_long
        self.read, self.out, self.rid = read, out, rid
        self.ctx = plain + w_short + w_long + read
        self.fresh = False  # first call of a cycle (session start or post-compact)


def parse_claude_code(path):
    """Claude Code / OpenClaw JSONL transcripts. Verified format."""
    seq = []
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return seq
    for ln in lines:
        if '"usage"' not in ln and "compact_boundary" not in ln:
            continue
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get("isSidechain"):
            continue
        if d.get("subtype") == "compact_boundary":
            m = d.get("compactMetadata") or {}
            seq.append(("C", m.get("preTokens"), m.get("postTokens")))
        elif d.get("type") == "assistant":
            u = dig(d, "message.usage")
            if not u:
                continue
            cc = u.get("cache_creation") or {}
            seq.append(("A", Call(
                u.get("input_tokens", 0) or 0,
                cc.get("ephemeral_5m_input_tokens", 0) or 0,
                cc.get("ephemeral_1h_input_tokens", 0) or 0,
                u.get("cache_read_input_tokens", 0) or 0,
                u.get("output_tokens", 0) or 0,
                d.get("requestId") or dig(d, "message.id"),
            ), None))
    return seq


def parse_generic(path, fmap):
    """Any JSONL where each line may carry a usage record, via --map dotted paths."""
    seq = []
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return seq
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        raw = {k: dig(d, p) for k, p in fmap.items()}
        if raw.get("read") is None and raw.get("input") is None:
            continue
        seq.append(("A", Call(
            raw.get("input") or 0, raw.get("write_short") or 0,
            raw.get("write_long") or 0, raw.get("read") or 0,
            raw.get("output") or 0, raw.get("id"),
        ), None))
    return seq


def sample(args):
    fmap = None
    if args.source == "generic":
        if not args.map:
            sys.exit("generic source needs --map, e.g. "
                     "--map input=usage.prompt_tokens,read=usage.cached_tokens,output=usage.completion_tokens")
        fmap = dict(kv.split("=", 1) for kv in args.map.split(","))

    roots = args.root or (["~/.claude/projects/*/*.jsonl"] if args.source == "claude-code" else [])
    files = []
    cutoff = time.time() - args.days * 86400
    for pat in roots:
        for f in glob.glob(os.path.expanduser(pat), recursive=True):
            if os.path.getsize(f) >= args.min_size and os.path.getmtime(f) >= cutoff:
                files.append(f)
    if not files:
        return None, "no transcripts matched"

    gs, bases, summaries, pre_ctx, drop_reason = [], [], [], [], Counter()
    tot = Counter()
    n_calls = n_compact = 0

    for f in files:
        seq = parse_claude_code(f) if args.source == "claude-code" else parse_generic(f, fmap)
        # collapse retries / streaming duplicates sharing one request id
        flat, prev_id = [], object()
        for kind, a, b in seq:
            if kind == "A":
                if a.rid is not None and a.rid == prev_id:
                    if a.ctx > flat[-1][1].ctx:
                        flat[-1] = (kind, a, b)
                    continue
                prev_id = a.rid
            else:
                prev_id = object()
            flat.append((kind, a, b))
        if not flat:
            continue

        prev = None
        first_of_cycle = True
        for kind, a, b in flat:
            if kind == "C":
                n_compact += 1
                if a:
                    pre_ctx.append(a)
                if b:
                    summaries.append(b)
                prev, first_of_cycle = None, True
                continue
            n_calls += 1
            if first_of_cycle:
                a.fresh = True
                bases.append(a.ctx)
                first_of_cycle = False
            else:
                # steady-state calls only: cache writes at a cycle boundary are a
                # one-off compaction cost, not part of the per-call holding price
                tot["plain"] += a.plain
                tot["w_short"] += a.w_short
                tot["w_long"] += a.w_long
                tot["read"] += a.read
                tot["out"] += a.out
                d = a.ctx - prev.ctx
                if 0 < d < args.max_delta:
                    gs.append(d)
                elif d <= 0:
                    drop_reason["non-increasing"] += 1
                else:
                    drop_reason["outlier"] += 1
            prev = a

    if not gs:
        return None, f"parsed {n_calls} calls but found no usable growth deltas"

    ctx_tot = tot["plain"] + tot["w_short"] + tot["w_long"] + tot["read"]
    prompt_mult = (tot["plain"] + tot["w_short"] * 1.25 + tot["w_long"] * 2.0
                   + tot["read"] * READ_MULT) / ctx_tot
    wl, ws = tot["w_long"], tot["w_short"]
    write_mult = 2.0 if wl > ws else 1.25

    base = pct(bases, 0.5)
    summary = pct(summaries, 0.5) if summaries else max(0, base - pct(bases, 0.05))

    return dict(
        source=args.source, files=len(files), calls=n_calls, compactions=n_compact,
        g_p25=pct(gs, .25), g_p50=pct(gs, .5), g_mean=round(statistics.mean(gs)),
        g_p75=pct(gs, .75), g_p90=pct(gs, .9),
        base=base, summary=summary,
        current_trigger=pct(pre_ctx, 0.5) if pre_ctx else None,
        prompt_mult=round(prompt_mult, 4),
        cache_hit=round(tot["read"] / ctx_tot, 4),
        write_mult=write_mult,
        dropped=dict(drop_reason),
    ), None


# ---------------------------------------------------------------- solving

def cost_per_call(L, B, a, g, K):
    """Amortized $/call when compacting at context length L.

    a(B+L)/2        holding: average context re-read every call
    g(K + aL)/(L-B) compaction fixed cost spread over (L-B)/g calls
    """
    return a * (B + L) / 2 + g * (K + a * L) / (L - B)


def bar(v, vmax, width=26):
    return "#" * max(1, round(width * v / vmax))


def solve(args):
    p = {}
    if args.params:
        p = json.load(open(os.path.expanduser(args.params)))
    elif args.preset:
        p = dict(PRESETS[args.preset])

    g = args.g or p.get({"p50": "g_p50", "mean": "g_mean", "p75": "g_p75",
                         "p90": "g_p90"}[args.g_mode])
    B = args.base or p.get("base")
    S = args.summary if args.summary is not None else p.get("summary")
    mult = args.prompt_mult or p.get("prompt_mult")
    wmult = args.write_mult if args.write_mult is not None else p.get("write_mult", 1.25)
    cur = args.current or p.get("current_trigger")
    if None in (g, B, S, mult):
        sys.exit("missing parameters: need --params or --preset, or all of "
                 "--g --base --summary --prompt-mult")

    pin, pout = args.price_in / 1e6, args.price_out / 1e6
    a = pin * mult                      # $/token held, per call
    K = S * pout + S * pin * wmult      # one compaction: emit summary + re-cache it

    Lstar = B + math.sqrt(2 * g * (K + a * B) / a)
    capped = False
    if args.window and Lstar > args.window:
        Lstar, capped = float(args.window), True
    best = cost_per_call(Lstar, B, a, g, K)

    def band(tol):
        lo = hi = Lstar
        step = max(500, (Lstar - B) / 200)
        x = Lstar
        while x > B + step and cost_per_call(x, B, a, g, K) <= best * (1 + tol):
            lo = x; x -= step
        x = Lstar
        lim = args.window or Lstar * 6
        while x < lim and cost_per_call(x, B, a, g, K) <= best * (1 + tol):
            hi = x; x += step
        return lo, hi

    b3, b10 = band(0.03), band(0.10)

    ceiling = args.window or Lstar * 3.4
    cand = {round(x / 1000) * 1000 for x in (
        B * 1.25, B * 1.6, Lstar * 0.6, Lstar * 0.8, Lstar, Lstar * 1.25,
        Lstar * 1.6, Lstar * 2.2, Lstar * 3.2)}
    anchors = {round(Lstar)} | ({round(cur)} if cur else set())
    if args.window:
        anchors.add(args.window)
    pts = []
    for L in sorted(cand | anchors):
        if not B * 1.1 < L <= ceiling:
            continue
        if pts and L - pts[-1] < 0.06 * Lstar and L not in anchors:
            continue
        if pts and L in anchors and L - pts[-1] < 0.06 * Lstar:
            pts.pop()
        pts.append(L)
    curve = [dict(L=int(L), cost=cost_per_call(L, B, a, g, K)) for L in pts]
    vmax = max(c["cost"] for c in curve)

    out = dict(
        inputs=dict(g=g, base=B, summary=S, prompt_mult=mult, write_mult=wmult,
                    price_in=args.price_in, price_out=args.price_out,
                    window=args.window, current_trigger=cur, model=args.model),
        derived=dict(a_per_mtok=a * 1e6, K=K, a=a),
        optimum=dict(L=int(Lstar), cost_per_call=best, window_capped=capped,
                     calls_per_cycle=(Lstar - B) / g,
                     holding_term=a * (B + Lstar) / 2,
                     amortized_term=g * (K + a * Lstar) / (Lstar - B)),
        band_3pct=[int(b3[0]), int(b3[1])],
        band_10pct=[int(b10[0]), int(b10[1])],
        curve=curve,
    )
    if cur:
        cc = cost_per_call(float(cur), B, a, g, K)
        out["current"] = dict(L=int(cur), cost_per_call=cc,
                              overspend_pct=(cc / best - 1) * 100,
                              calls_per_cycle=(cur - B) / g)

    if args.json:
        print(json.dumps(out, indent=2))
        return

    w = f"{args.model or 'model'} @ ${args.price_in}/${args.price_out} per MTok"
    print(f"== compact-tune :: {w} ==\n")
    print(f"  growth g            {g:>10,} tok/call")
    print(f"  base after compact  {B:>10,} tok")
    print(f"  summary size        {S:>10,} tok")
    print(f"  prompt multiplier   {mult:>10.3f}  (effective ${a*1e6:.3f}/MTok)")
    print(f"  compaction cost K   {'$%.3f' % K:>10}")
    print()
    print(f"  OPTIMAL TRIGGER     {int(Lstar):>10,} tok"
          f"{'  (capped at window)' if capped else ''}")
    print(f"  cost at optimum     {'$%.4f' % best:>10} /call"
          f"   ({out['optimum']['calls_per_cycle']:.0f} calls/cycle)")
    print(f"  within +3%          {b3[0]:>10,.0f} - {b3[1]:,.0f}")
    print(f"  within +10%         {b10[0]:>10,.0f} - {b10[1]:,.0f}")
    if cur:
        print(f"  CURRENT TRIGGER     {int(cur):>10,} tok  "
              f"-> ${out['current']['cost_per_call']:.4f}/call  "
              f"({out['current']['overspend_pct']:+.1f}%)")
    print("\n  cost curve ($/call, lower is better)")
    for c in curve:
        tag = ""
        if abs(c["L"] - Lstar) < 1500:
            tag = "  <- optimum"
        elif cur and abs(c["L"] - cur) < 1500:
            tag = "  <- current"
        print(f"    {c['L']:>8,}  {bar(c['cost'], vmax):<26} ${c['cost']:.4f} "
              f"{c['cost']/best-1:+7.1%}{tag}")


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(prog="compact_tune")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sample", help="measure parameters from agent transcripts")
    s.add_argument("--source", default="claude-code", choices=["claude-code", "generic"])
    s.add_argument("--root", action="append", help="glob for transcript files (repeatable)")
    s.add_argument("--map", help="generic source field map, dotted paths: "
                                 "input=,read=,write_short=,write_long=,output=,id=")
    s.add_argument("--days", type=int, default=30)
    s.add_argument("--min-size", type=int, default=300_000)
    s.add_argument("--max-delta", type=int, default=150_000,
                   help="discard growth deltas above this as parse artifacts")
    s.add_argument("--out", help="write params JSON here")

    v = sub.add_parser("solve", help="compute the optimal compaction point")
    v.add_argument("--params", help="params JSON from `sample`")
    v.add_argument("--preset", choices=list(PRESETS))
    v.add_argument("--price-in", type=float, required=True, help="$ per MTok, uncached input")
    v.add_argument("--price-out", type=float, required=True, help="$ per MTok, output")
    v.add_argument("--model", help="label for the report")
    v.add_argument("--window", type=int, help="context window cap in tokens")
    v.add_argument("--g", type=int); v.add_argument("--base", type=int)
    v.add_argument("--summary", type=int); v.add_argument("--prompt-mult", type=float)
    v.add_argument("--write-mult", type=float)
    v.add_argument("--current", type=int, help="current trigger point, for comparison")
    v.add_argument("--g-mode", default="mean", choices=["p50", "mean", "p75", "p90"])
    v.add_argument("--json", action="store_true")

    args = ap.parse_args()
    if args.cmd == "sample":
        res, err = sample(args)
        if err:
            sys.exit(f"sample failed: {err}")
        txt = json.dumps(res, indent=2)
        if args.out:
            open(os.path.expanduser(args.out), "w").write(txt)
            print(f"wrote {args.out}")
        print(txt)
    else:
        solve(args)


if __name__ == "__main__":
    main()
