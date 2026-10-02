"""Tests for transcript parsing / Task call extraction."""
import os

import pytest

from subagent_tax.analyzer import (find_task_calls, scan, iter_transcripts,
                                   default_projects_dir)

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_finds_task_calls_in_session1():
    calls = find_task_calls(os.path.join(FIX, "session1.jsonl"))
    assert len(calls) == 2  # the Read tool_use and bad line are ignored


def test_fields_extracted():
    calls = find_task_calls(os.path.join(FIX, "session1.jsonl"))
    first = calls[0]
    assert first.subagent_type == "Explore"
    assert first.description == "Find auth refresh"
    assert "auth token is refreshed" in first.prompt_preview
    assert first.session_id == "sess-aaa"
    assert first.cwd == "/repo"
    assert first.timestamp == "2026-09-20T10:00:05Z"


def test_missing_subagent_type_defaults_empty():
    calls = find_task_calls(os.path.join(FIX, "session1.jsonl"))
    assert calls[1].subagent_type == ""
    assert calls[1].description == "Write tests"


def test_long_prompt_preview_truncated():
    calls = find_task_calls(os.path.join(FIX, "session2.jsonl"))
    assert len(calls) == 1
    assert calls[0].subagent_type == "Plan"
    assert calls[0].prompt_preview.endswith("...")
    assert len(calls[0].prompt_preview) == 203  # 200 + "..."


def test_summary_and_tool_result_lines_ignored():
    calls = find_task_calls(os.path.join(FIX, "session2.jsonl"))
    assert len(calls) == 1  # summary line + user tool_result add nothing


def test_malformed_file_returns_empty():
    assert find_task_calls("/nonexistent/path.jsonl") == []


def test_scan_explicit_dir():
    tpaths, calls = scan([FIX])
    assert len(tpaths) == 2
    assert len(calls) == 3


def test_scan_missing_projects_dir_warns_gracefully():
    tpaths, calls = scan([], projects_dir="/nonexistent-dir-xyz")
    assert tpaths == [] and calls == []


def test_default_projects_dir_shape():
    assert default_projects_dir().endswith(".claude/projects")


def test_iter_transcripts_dedupes():
    f = os.path.join(FIX, "session1.jsonl")
    assert list(iter_transcripts([f, f, FIX])).count(f) == 1
