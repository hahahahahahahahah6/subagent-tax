"""Tests for the heuristic preamble cost model."""
import json
import os

import pytest

from subagent_tax.model import (PreambleModel, estimate_tokens,
                                DEFAULT_COMPONENTS)


def test_estimate_tokens_chars_over_four():
    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0


def test_defaults_sum_to_article_baseline():
    model = PreambleModel()
    assert model.total_per_call == 51_000
    assert set(model.components) == set(DEFAULT_COMPONENTS)


def test_set_override():
    model = PreambleModel(overrides={"skills": 123})
    assert model.components["skills"] == 123
    assert "override" in model.sources["skills"]
    assert model.total_per_call == 51_000 - 4_000 + 123


def test_unknown_component_raises():
    with pytest.raises(ValueError):
        PreambleModel(overrides={"nope": 1})


def test_claude_md_measured(tmp_path):
    p = tmp_path / "CLAUDE.md"
    p.write_text("x" * 8000)
    model = PreambleModel(claude_md_path=str(p))
    assert model.components["claude_md"] == 2000
    assert "measured" in model.sources["claude_md"]


def test_skills_dir_measured_per_skill(tmp_path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "SKILL.md").write_text("y" * 4000)
    (tmp_path / "beta").mkdir()
    (tmp_path / "beta" / "SKILL.md").write_text("z" * 1200)
    model = PreambleModel(skills_dir=str(tmp_path))
    assert model.per_skill == {"alpha": 1000, "beta": 300}
    assert model.components["skills"] == 1300


def test_mcp_tax_report_import(tmp_path):
    rows = [
        {"name": "playwright", "ok": True, "tool_count": 10,
         "schema_chars": 40000, "est_tokens": 10000},
        {"name": "broken", "ok": False, "error": "timeout"},
        {"name": "legacy", "ok": True, "tool_count": 2,
         "schema_chars": 8000},  # no est_tokens -> chars/4 fallback
    ]
    p = tmp_path / "mcp-tax.json"
    p.write_text(json.dumps(rows))
    model = PreambleModel(mcp_tax_report=str(p))
    assert model.per_mcp_server == {"playwright": 10000, "legacy": 2000}
    assert model.components["mcp_tool_schemas"] == 12000
    assert "broken" not in model.per_mcp_server


def test_mcp_tax_report_bad_file_raises(tmp_path):
    with pytest.raises(ValueError):
        PreambleModel(mcp_tax_report=str(tmp_path / "missing.json"))


def test_cost_per_call():
    model = PreambleModel()
    assert model.cost_per_call_usd(3.0) == pytest.approx(0.153)
