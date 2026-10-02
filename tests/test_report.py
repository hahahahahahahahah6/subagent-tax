"""Tests for aggregation, ranking, suggestions, and rendering."""
import json

import pytest

from subagent_tax.analyzer import TaskCall, find_task_calls
from subagent_tax.model import PreambleModel
from subagent_tax.report import (aggregate, rank_contributions,
                                 trim_suggestion, render_text, render_json)
import os

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _calls():
    out = []
    for fn in ("session1.jsonl", "session2.jsonl"):
        out.extend(find_task_calls(os.path.join(FIX, fn)))
    return out


def test_aggregation_math():
    agg = aggregate(_calls(), PreambleModel(), 3.0)
    assert agg["n_calls"] == 3
    assert agg["n_sessions"] == 2
    assert agg["per_call_tokens"] == 51_000
    assert agg["total_tokens"] == 153_000
    assert agg["cost_usd"] == pytest.approx(0.459)


def test_by_subagent_type_counts():
    agg = aggregate(_calls(), PreambleModel(), 3.0)
    assert agg["by_subagent_type"] == {"Explore": 1, "Plan": 1,
                                      "(default)": 1}


def test_ranking_sorted_desc():
    rows = rank_contributions(PreambleModel())
    toks = [r["tokens_per_call"] for r in rows]
    assert toks == sorted(toks, reverse=True)
    assert rows[0]["label"] == "system prompt"


def test_ranking_includes_measured_rows(tmp_path):
    (tmp_path / "s1").mkdir()
    (tmp_path / "s1" / "SKILL.md").write_text("q" * 400000)  # 100k tokens
    model = PreambleModel(skills_dir=str(tmp_path))
    rows = rank_contributions(model)
    labels = [r["label"] for r in rows[:3]]
    assert "skill: s1" in labels  # per-skill breakdown surfaces at the top


def test_trim_suggestion_content():
    agg = aggregate(_calls(), PreambleModel(), 3.0)
    top = agg["suggestions"][0]
    assert "system prompt" in top
    assert "20,000 tokens per Task call" in top
    assert "$" in top


def test_text_render_sections():
    out = render_text(aggregate(_calls(), PreambleModel(), 3.0),
                      _calls(), PreambleModel())
    for needle in ("subagent-tax report", "Task (subagent) calls : 3",
                   "TOTAL per call", "Estimated waste",
                   "Cuttable contributions", "Top trim suggestion",
                   "Honest limitations"):
        assert needle in out, needle


def test_text_render_empty():
    out = render_text(aggregate([], PreambleModel(), 3.0), [],
                      PreambleModel())
    assert "No Task (subagent) calls found" in out


def test_json_render_parses():
    data = json.loads(render_json(aggregate(_calls(), PreambleModel(), 3.0)))
    assert data["n_calls"] == 3
    assert len(data["ranking"]) >= 5
    assert data["suggestions"]
