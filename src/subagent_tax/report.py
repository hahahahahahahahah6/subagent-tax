"""Aggregation, cuttable-contribution ranking, and output rendering."""
from __future__ import annotations

import json
from collections import Counter

from . import ledger as _ledger_mod
from .model import LABELS


def _money(tokens, price_per_mtok):
    return tokens / 1e6 * price_per_mtok


def rank_contributions(model):
    """Rows of (label, tokens_per_call, kind, detail), sorted desc.

    Rows cover whole components plus per-MCP-server and per-skill
    breakdowns when measured, so the most expensive cuttable item
    (a server, a skill, a CLAUDE.md section) surfaces first.
    """
    rows = []
    for key, tokens in model.components.items():
        rows.append({
            "label": LABELS[key],
            "tokens_per_call": tokens,
            "kind": "component",
            "detail": model.sources.get(key, ""),
        })
    for name, tokens in model.per_mcp_server.items():
        rows.append({
            "label": "MCP server: %s" % name,
            "tokens_per_call": tokens,
            "kind": "mcp_server",
            "detail": "from mcp-tax report",
        })
    for name, tokens in model.per_skill.items():
        rows.append({
            "label": "skill: %s" % name,
            "tokens_per_call": tokens,
            "kind": "skill",
            "detail": "measured SKILL.md",
        })
    rows.sort(key=lambda r: r["tokens_per_call"], reverse=True)
    return rows


def trim_suggestion(row, n_calls, price_per_mtok):
    """One-line actionable suggestion for a ranked contribution row."""
    kind = row["kind"]
    label = row["label"]
    tok = row["tokens_per_call"]
    saved_usd = _money(tok * n_calls, price_per_mtok)
    if kind == "mcp_server":
        verb = "Disable/remove"
    elif kind == "skill":
        verb = "Trim/shorten"
    elif "CLAUDE.md" in label:
        verb = "Trim"
    elif "system prompt" in label:
        verb = "Slim down (custom system prompt)"
    else:
        verb = "Reduce"
    return ("%s %s: saves ~%s tokens per Task call "
            "(~$%.2f at %d observed calls)" % (
                verb, label, _fmt_int(tok), saved_usd, n_calls))


def aggregate(calls, model, price_per_mtok, top=5,
              turns_per_call=_ledger_mod.DEFAULT_TURNS_PER_TASK,
              spawn_overhead=_ledger_mod.DEFAULT_SPAWN_OVERHEAD_TOKENS,
              cache_hit_rate=0.0):
    n_calls = len(calls)
    per_call = model.total_per_call
    total_tokens = per_call * n_calls
    by_type = Counter(c.subagent_type or "(default)" for c in calls)
    rows = rank_contributions(model)
    suggestions = [trim_suggestion(r, n_calls, price_per_mtok)
                   for r in rows[:top] if n_calls and r["tokens_per_call"]]
    ledger_rows = [{"label": label, "calls": count}
                   for label, count in sorted(by_type.items())]
    ledger = _ledger_mod.build_ledger(
        ledger_rows, per_call, turns_per_call=turns_per_call,
        spawn_overhead=spawn_overhead, cache_hit_rate=cache_hit_rate,
        price_per_mtok=price_per_mtok)
    return {
        "n_calls": n_calls,
        "n_sessions": len({c.session_id for c in calls}),
        "per_call_tokens": per_call,
        "total_tokens": total_tokens,
        "cost_usd": _money(total_tokens, price_per_mtok),
        "price_per_mtok": price_per_mtok,
        "by_subagent_type": dict(by_type),
        "components": [
            {"name": k, "label": LABELS[k], "tokens": v,
             "source": model.sources.get(k, "")}
            for k, v in model.components.items()
        ],
        "ranking": rows,
        "suggestions": suggestions,
        "ledger": ledger,
    }


def render_ledger(agg):
    """Render the per-turn re-entry billing ledger as text lines."""
    ledger = agg["ledger"]
    totals = ledger["totals"]
    L = []
    L.append("Per-turn re-entry ledger (corrected billing model, "
             "same framework as mcp-tax 0.3)")
    L.append("  turns per Task call: %d (heuristic; --turns-per-task) | "
             "spawn overhead: %s tok/call | cache hit rate: %g%% "
             "(spawn turn always cold)" % (
                 ledger["turns_per_call"],
                 _fmt_int(ledger["spawn_overhead_tokens_per_call"]),
                 ledger["cache_hit_rate"] * 100))
    L.append("")
    L.append("  %-16s %6s %10s %12s %12s %12s" % (
        "subagent_type", "calls", "multiplier", "per-call tok",
        "window tok", "billable tok"))
    for line in ledger["lines"]:
        L.append("  %-16s %6d %10d %12s %12s %12s" % (
            line["label"][:16], line["calls"], line["subagent_multiplier"],
            _fmt_int(line["per_call_window_tokens"]),
            _fmt_int(line["cumulative_window_tokens"]),
            _fmt_int(line["billable_tokens"])))
    L.append("  %-16s %6s %10s %12s %12s %12s  ~= $%.2f" % (
        "TOTAL", "", "", "",
        _fmt_int(totals["cumulative_window_tokens"]),
        _fmt_int(totals["billable_tokens"]), totals["cost_usd"]))
    L.append("")
    L.append("  Old model (v0.2, spawn-only) counted %s tokens; corrected "
             "ledger counts %s —" % (
                 _fmt_int(totals["old_model_tokens"]),
                 _fmt_int(totals["cumulative_window_tokens"])))
    L.append("  the old model undercounted by a factor of %.1fx." % (
        totals["correction_factor"],))
    return L


def _fmt_int(n):
    return "{:,}".format(int(n))


def render_text(agg, calls, model, top=5):
    L = []
    L.append("subagent-tax report")
    L.append("==================")
    if not agg["n_calls"]:
        L.append("No Task (subagent) calls found in the scanned transcripts.")
        return "\n".join(L) + "\n"
    L.append("Task (subagent) calls : %d across %d session(s)" % (
        agg["n_calls"], agg["n_sessions"]))
    if agg["by_subagent_type"]:
        L.append("By subagent_type     : " + ", ".join(
            "%s=%d" % kv for kv in sorted(agg["by_subagent_type"].items())))
    L.append("")
    L.append("Preamble model: tokens re-sent per Task call [heuristic]")
    for comp in agg["components"]:
        L.append("  %-22s %10s tok   (%s)" % (
            comp["label"], _fmt_int(comp["tokens"]), comp["source"]))
    L.append("  %-22s %10s tok" % ("TOTAL per call",
                                   _fmt_int(agg["per_call_tokens"])))
    L.append("")
    L.append("Estimated waste: %d calls x %s tok = %s tokens ~= $%.2f" % (
        agg["n_calls"], _fmt_int(agg["per_call_tokens"]),
        _fmt_int(agg["total_tokens"]), agg["cost_usd"]))
    L.append("(input pricing $%.2f/MTok; override with --price-input)" % (
        agg["price_per_mtok"],))
    L.append("")
    L.append("Cuttable contributions (tokens per Task call):")
    for i, row in enumerate(agg["ranking"][:top], 1):
        L.append("  %d. %-28s %10s tok/call" % (
            i, row["label"][:28], _fmt_int(row["tokens_per_call"])))
    if agg["suggestions"]:
        L.append("")
        L.append("Top trim suggestion:")
        L.append("  " + agg["suggestions"][0])
    L.append("")
    L.extend(render_ledger(agg))
    L.append("")
    L.append("Note: token counts are heuristic (~4 chars/token), not exact;")
    L.append("see README 'Honest limitations'.")
    return "\n".join(L) + "\n"


def render_json(agg):
    return json.dumps(agg, indent=2, sort_keys=True) + "\n"
