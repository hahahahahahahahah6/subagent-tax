"""Extract Task (subagent) tool calls from Claude Code transcript JSONL.

Transcript layout (verified against session-handover's parser):
  ~/.claude/projects/<slug>/<session-id>.jsonl
  lines: {"type": "assistant"|"user"|"summary", "message": {...},
          "timestamp": "...", "sessionId": "...", "cwd": "..."}
  assistant content blocks include:
    {"type": "tool_use", "name": "Task", "input": {"subagent_type": ...,
     "description": ..., "prompt": ...}}

Parsing is defensive: bad lines are skipped, a parse never raises on
real-world input.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class TaskCall:
    """One subagent invocation (one Task tool_use block)."""
    timestamp: str = ""
    session_id: str = ""
    cwd: str = ""
    subagent_type: str = ""
    description: str = ""
    prompt_preview: str = ""
    transcript_path: str = ""


def _iter_jsonl(path):
    """Yield parsed JSON objects from a .jsonl file, skipping bad lines."""
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                yield obj


def _collapse(text, limit=200):
    text = " ".join(str(text).split())
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _text(value):
    """Return scalar transcript metadata as text; reject containers."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def find_task_calls(path):
    """Return Task calls that have a matching successful tool result."""
    candidates = {}
    successful_ids = set()
    for obj in _iter_jsonl(path):
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", obj.get("type", ""))
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        if role == "user":
            for block in content:
                if (isinstance(block, dict) and
                        block.get("type") == "tool_result" and
                        block.get("is_error") is not True):
                    tool_id = block.get("tool_use_id")
                    if isinstance(tool_id, str):
                        successful_ids.add(tool_id)
            continue
        if role != "assistant":
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            if block.get("name") != "Task":
                continue
            tool_id = block.get("id")
            if not isinstance(tool_id, str) or not tool_id:
                continue
            inp = block.get("input") or {}
            if not isinstance(inp, dict):
                inp = {}
            session_id = _text(obj.get("sessionId"))
            if not session_id:
                continue
            candidates[tool_id] = TaskCall(
                timestamp=_text(obj.get("timestamp")),
                session_id=session_id,
                cwd=_text(obj.get("cwd")),
                subagent_type=_text(inp.get("subagent_type")),
                description=_text(inp.get("description")),
                prompt_preview=_collapse(inp.get("prompt", "")),
                transcript_path=path,
            )
    return [call for tool_id, call in candidates.items()
            if tool_id in successful_ids]


def iter_transcripts(paths):
    """Yield transcript paths from explicit files and/or directories."""
    seen = set()
    for path in paths:
        path = os.path.normcase(os.path.realpath(os.path.abspath(path)))
        if os.path.isfile(path) and path.endswith(".jsonl"):
            if path not in seen:
                seen.add(path)
                yield path
        elif os.path.isdir(path):
            for root, _dirs, files in os.walk(path):
                for fn in files:
                    if fn.endswith(".jsonl"):
                        full = os.path.join(root, fn)
                        if full not in seen:
                            seen.add(full)
                            yield full


def default_projects_dir():
    return os.path.expanduser("~/.claude/projects")


def scan(paths, projects_dir=None):
    """Return (transcript_paths, all TaskCalls) for the given inputs.

    With no explicit paths, scans the Claude Code projects directory.
    """
    if not paths:
        roots = [projects_dir or default_projects_dir()]
    else:
        roots = list(paths)
    tpaths = sorted(iter_transcripts(roots))
    calls = []
    for tp in tpaths:
        calls.extend(find_task_calls(tp))
    return tpaths, calls
