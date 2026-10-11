"""Tests for the per-turn re-entry billing ledger (subagent multiplier,
spawn overhead, cache TTL miss)."""
import json
import os

import pytest

from subagent_tax.analyzer import find_task_calls
from subagent_tax.cli import main
from subagent_tax.ledger import (
    build_ledger, CACHE_BILLABLE_FRACTION,
    DEFAULT_TURNS_PER_TASK, DEFAULT_SPAWN_OVERHEAD_TOKENS,
)
from subagent_tax.model import PreambleModel
from subagent_tax.report import aggregate, render_text, render_json

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
PREAMBLE = 51_000


def _calls():
    out = []
    for fn in ("session1.jsonl", "session2.jsonl"):
        out.extend(find_task_calls(os.path.join(FIX, fn)))
    return out


def test_per_turn_reentry_math():
    led = build_ledger([{"label": "Explore", "calls": 2}], PREAMBLE,
                       turns_per_call=3, spawn_overhead=2_000,
                       cache_hit_rate=0.0)
    line = led["lines"][0]
    # each call: spawn overhead + preamble on spawn + on every internal turn
    assert line["per_call_window_tokens"] == 2_000 + PREAMBLE * 3
    assert line["cumulative_window_tokens"] == (2_000 + PREAMBLE * 3) * 2


def test_subagent_multiplier_column():
    led = build_ledger([{"label": "Explore", "calls": 4},
                        {"label": "Plan", "calls": 1}], PREAMBLE)
    by_label = {l["label"]: l for l in led["lines"]}
    assert by_label["Explore"]["subagent_multiplier"] == 4
    assert by_label["Plan"]["subagent_multiplier"] == 1
    assert led["totals"]["subagent_multiplier"] == 5


def test_spawn_overhead_zero():
    led = build_ledger([{"label": "Explore", "calls": 1}], PREAMBLE,
                       turns_per_call=1, spawn_overhead=0)
    assert led["lines"][0]["per_call_window_tokens"] == PREAMBLE


def test_cache_cold_spawn_turn():
    # With a 100% hit rate the spawn turn is still billed at full price:
    # a fresh subagent context is a cache TTL miss on turn 1.
    led = build_ledger([{"label": "Explore", "calls": 1}], PREAMBLE,
                       turns_per_call=3, spawn_overhead=2_000,
                       cache_hit_rate=1.0)
    line = led["lines"][0]
    spawn_turn = 2_000 + PREAMBLE
    later = PREAMBLE * 2 * CACHE_BILLABLE_FRACTION
    assert line["billable_tokens"] == int(round(spawn_turn + later))
    assert line["billable_tokens"] < line["cumulative_window_tokens"]


def test_cache_never_shrinks_window():
    led = build_ledger([{"label": "Explore", "calls": 2}], PREAMBLE,
                       turns_per_call=4, spawn_overhead=2_000,
                       cache_hit_rate=0.9)
    assert led["totals"]["cacheable_tokens"] == \
        led["totals"]["cumulative_window_tokens"]
    line = led["lines"][0]
    assert line["cacheable_tokens"] == line["cumulative_window_tokens"]


def test_old_model_comparison():
    led = build_ledger([{"label": "Explore", "calls": 2}], PREAMBLE,
                       turns_per_call=3, spawn_overhead=2_000)
    line = led["lines"][0]
    # v0.2 counted only preamble x calls (spawn-only, once per call)
    assert line["old_model_tokens"] == PREAMBLE * 2
    assert line["cumulative_window_tokens"] > line["old_model_tokens"]
    assert line["correction_factor"] == pytest.approx(
        (2_000 + PREAMBLE * 3) * 2 / (PREAMBLE * 2))


def test_validation_errors():
    with pytest.raises(ValueError):
        build_ledger([], PREAMBLE, turns_per_call=0)
    with pytest.raises(ValueError):
        build_ledger([], PREAMBLE, turns_per_call=-2)
    with pytest.raises(ValueError):
        build_ledger([], PREAMBLE, cache_hit_rate=1.5)
    with pytest.raises(ValueError):
        build_ledger([], PREAMBLE, cache_hit_rate=-0.1)
    with pytest.raises(ValueError):
        build_ledger([], PREAMBLE, spawn_overhead=-1)


def test_aggregation_keeps_old_keys_and_adds_ledger():
    agg = aggregate(_calls(), PreambleModel(), 3.0)
    # legacy spawn-only accounting is unchanged
    assert agg["n_calls"] == 3
    assert agg["total_tokens"] == 153_000
    assert agg["cost_usd"] == pytest.approx(0.459)
    # new ledger is present with explicit multiplier
    ledger = agg["ledger"]
    assert ledger["turns_per_call"] == DEFAULT_TURNS_PER_TASK
    assert ledger["totals"]["subagent_multiplier"] == 3
    assert len(ledger["lines"]) == 3  # Explore, Plan, (default)
    assert ledger["totals"]["cumulative_window_tokens"] > \
        ledger["totals"]["old_model_tokens"]


def test_cli_ledger_flags(capsys):
    assert main([FIX, "--turns-per-task", "2", "--spawn-overhead", "1000",
                 "--cache-hit-rate", "0.5"]) == 0
    out = capsys.readouterr().out
    assert "Per-turn re-entry ledger" in out
    assert "multiplier" in out
    assert "undercounted by a factor of" in out


def test_cli_json_contains_ledger(capsys):
    assert main([FIX, "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    ledger = data["ledger"]
    assert ledger["totals"]["n_calls"] == 3
    for line in ledger["lines"]:
        assert "subagent_multiplier" in line
        assert line["subagent_multiplier"] == line["calls"]


def test_cli_rejects_bad_ledger_values(capsys):
    assert main([FIX, "--turns-per-task", "0"]) == 2
    assert "turns_per_call" in capsys.readouterr().err
    assert main([FIX, "--cache-hit-rate", "2"]) == 2
    with pytest.raises(SystemExit):  # argparse rejects negative int
        main([FIX, "--spawn-overhead", "-1"])


def test_text_render_includes_ledger_section():
    out = render_text(aggregate(_calls(), PreambleModel(), 3.0),
                      _calls(), PreambleModel())
    assert "Per-turn re-entry ledger" in out
    assert "Old model (v0.2, spawn-only)" in out
    assert "multiplier" in out


def test_defaults_are_documented():
    assert DEFAULT_TURNS_PER_TASK >= 1
    assert DEFAULT_SPAWN_OVERHEAD_TOKENS >= 0
    assert 0.0 < CACHE_BILLABLE_FRACTION < 1.0
