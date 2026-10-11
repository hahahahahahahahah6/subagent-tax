"""Per-turn re-entry billing ledger for subagent-tax.

The corrected billing model — the same framework as mcp-tax 0.3, after the
per-turn re-entry correction raised by dev.to reader MCPulse: tool schemas
and the rest of the fixed preamble re-enter the model context on EVERY API
call (turn), not once per session. Counting them once per session
underestimates the true context cost by a factor of `turns`.

The subagent side adds a second dimension: every Task() call spawns a
brand-new context, so the full preamble is re-paid on spawn — a real
amplifier. (Measured by dev.to reader aidiveyt: 2,631 subagent runs ate
48.1% of all tokens.) This ledger makes the subagent multiplier explicit.

Three orthogonal cost dimensions:
  - spawn: the full preamble re-paid once per Task() call (the multiplier),
    plus a fixed per-call spawn overhead (Task payload + result handling).
  - per-turn re-entry: the preamble re-injected into the window on every
    turn inside the subagent.
  - cache TTL miss: a fresh subagent starts with a cold cache, so the spawn
    turn never benefits from the cache hit rate; later turns do.

Prompt caching only reduces price, never window occupancy: cached tokens
still sit in the context window at full size. So `cumulative_window_tokens`
ignores the cache hit rate; only `billable_tokens` is discounted.

Turn counts inside a subagent are invisible in the parent transcript, so
`turns_per_call` is a heuristic (default 3); override with --turns-per-task.
Spawn overhead is likewise a heuristic; override with --spawn-overhead.
"""
from __future__ import annotations

#: Cached prompt reads are billed at roughly 10% of the base token price
#: (Anthropic-style pricing). Window occupancy is unaffected regardless.
CACHE_BILLABLE_FRACTION = 0.1

#: Heuristic default for turns inside one subagent call. The parent
#: transcript does not show the subagent's internal turns; measure or
#: guess yours with --turns-per-task.
DEFAULT_TURNS_PER_TASK = 3

#: Heuristic default per-call spawn overhead in tokens: the Task tool_use
#: payload (your prompt) plus the result handling. Override with
#: --spawn-overhead.
DEFAULT_SPAWN_OVERHEAD_TOKENS = 2_000


def build_ledger(rows, preamble_per_turn, turns_per_call=DEFAULT_TURNS_PER_TASK,
                 spawn_overhead=DEFAULT_SPAWN_OVERHEAD_TOKENS,
                 cache_hit_rate=0.0, price_per_mtok=3.0):
    """Build the per-turn re-entry billing ledger.

    rows: list of {"label": str, "calls": int} — usually one row per
        subagent_type, but any grouping works.
    preamble_per_turn: fixed preamble tokens re-injected every turn.
    turns_per_call: API calls (turns) inside one subagent, >= 1.
    spawn_overhead: fixed extra tokens per Task() call, >= 0.
    cache_hit_rate: fraction of later-turn preamble served from prompt
        cache, 0..1. The spawn turn is always cache-cold (TTL miss).

    Returns {"turns_per_call", "spawn_overhead_per_call", "cache_hit_rate",
    "price_per_mtok", "lines", "totals"}. Each line is an independent
    billing unit with an explicit `subagent_multiplier` column: how many
    fresh contexts this line spawned (each re-paying the full preamble).
    `old_model_tokens` keeps the v0.2 accounting (preamble x calls) for the
    correction comparison.
    """
    if not isinstance(turns_per_call, int) or turns_per_call < 1:
        raise ValueError("turns_per_call must be an integer >= 1")
    if spawn_overhead < 0:
        raise ValueError("spawn_overhead must be non-negative")
    if not 0.0 <= cache_hit_rate <= 1.0:
        raise ValueError("cache_hit_rate must be in [0, 1]")
    if preamble_per_turn < 0:
        raise ValueError("preamble_per_turn must be non-negative")
    if price_per_mtok < 0:
        raise ValueError("price_per_mtok must be non-negative")

    cached_price_factor = 1.0 - cache_hit_rate * (1.0 - CACHE_BILLABLE_FRACTION)
    later_turn_billable = preamble_per_turn * cached_price_factor

    lines = []
    for row in rows:
        calls = int(row.get("calls", 0))
        if calls < 0:
            raise ValueError("calls must be non-negative")
        # Every turn re-injects the whole preamble; the spawn itself pays
        # the preamble once plus the fixed spawn overhead.
        per_call_window = spawn_overhead + preamble_per_turn * turns_per_call
        window = per_call_window * calls
        # Cache TTL miss: the spawn turn starts cold in a brand-new context,
        # so it is billed at full price even when later turns hit the cache.
        spawn_turn_billable = spawn_overhead + preamble_per_turn
        billable_per_call = (spawn_turn_billable
                             + later_turn_billable * (turns_per_call - 1))
        billable = int(round(billable_per_call * calls))
        old_model = preamble_per_turn * calls
        lines.append({
            "label": str(row.get("label", "")),
            "calls": calls,
            # the explicit amplifier: each call is a fresh context
            "subagent_multiplier": calls,
            "preamble_tokens_per_turn": preamble_per_turn,
            "spawn_overhead_tokens_per_call": spawn_overhead,
            "turns_per_call": turns_per_call,
            "per_call_window_tokens": per_call_window,
            "cumulative_window_tokens": window,
            # caching never shrinks the window
            "cacheable_tokens": window,
            "billable_tokens": billable,
            "cost_usd": billable / 1e6 * price_per_mtok,
            # the v0.2 accounting, kept for the correction comparison
            "old_model_tokens": old_model,
            "correction_factor": (window / old_model) if old_model else 0.0,
        })

    def _sum(key):
        return sum(line[key] for line in lines)

    window_total = _sum("cumulative_window_tokens")
    old_total = _sum("old_model_tokens")
    totals = {
        "n_calls": _sum("calls"),
        "n_lines": len(lines),
        "preamble_tokens_per_turn": preamble_per_turn,
        "spawn_overhead_tokens_per_call": spawn_overhead,
        "turns_per_call": turns_per_call,
        # grand amplifier across all lines
        "subagent_multiplier": _sum("calls"),
        "cumulative_window_tokens": window_total,
        "cacheable_tokens": window_total,
        "billable_tokens": _sum("billable_tokens"),
        "cost_usd": _sum("billable_tokens") / 1e6 * price_per_mtok,
        "old_model_tokens": old_total,
        "correction_factor": (window_total / old_total) if old_total else 0.0,
    }
    return {
        "turns_per_call": turns_per_call,
        "spawn_overhead_tokens_per_call": spawn_overhead,
        "cache_hit_rate": cache_hit_rate,
        "price_per_mtok": price_per_mtok,
        "lines": lines,
        "totals": totals,
    }
