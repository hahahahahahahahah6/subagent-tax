"""End-to-end CLI tests against fixture transcripts."""
import json
import os

import pytest

from subagent_tax.cli import main

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_cli_text(capsys):
    assert main([FIX]) == 0
    out = capsys.readouterr().out
    assert "Task (subagent) calls : 3" in out
    assert "153,000 tokens" in out


def test_cli_json(capsys):
    assert main([FIX, "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["n_calls"] == 3
    assert data["total_tokens"] == 153_000


def test_cli_set_override(capsys):
    assert main([FIX, "--set", "skills=0", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["per_call_tokens"] == 47_000


def test_cli_bad_set_exits():
    with pytest.raises(SystemExit):
        main([FIX, "--set", "bogus"])


def test_cli_empty_dir(capsys, tmp_path):
    assert main([str(tmp_path)]) == 0
    assert "No Task (subagent) calls found" in capsys.readouterr().out
