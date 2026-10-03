"""Heuristic preamble cost model for subagent (Task tool) invocations.

Every Task() call re-sends a fixed preamble: the system prompt, the full
tool-schema definitions, CLAUDE.md, and skill listings. None of that is
visible in the transcript, so this module estimates it with a transparent,
overridable component model.

All token numbers here are HEURISTIC approximations (chars/4), not exact
counts. See README "Honest limitations".
"""
from __future__ import annotations

import json
import math
import os
import warnings

CHARS_PER_TOKEN = 4  #: rough heuristic for English prose / JSON schemas

#: Example default input price, USD per million tokens. Verify against
#: current published Anthropic pricing; override with --price-input.
DEFAULT_PRICE_INPUT_PER_MTOK = 3.00

#: Default component sizes in tokens. They intentionally sum to 51_000, the
#: fixed preamble per Task() call measured in
#: "Claude Code Subagents Were 48% of My Bill. Their Output Was 0.9%"
#: (dev.to @ji_ai). Each value is a heuristic placeholder: measure your own
#: setup with --claude-md / --skills-dir / --mcp-tax-report or override any
#: component with --set name=tokens.
DEFAULT_COMPONENTS = {
    "system_prompt": 20_000,
    "builtin_tool_schemas": 8_000,
    "mcp_tool_schemas": 16_000,
    "claude_md": 3_000,
    "skills": 4_000,
}

#: Human-readable labels for the components.
LABELS = {
    "system_prompt": "system prompt",
    "builtin_tool_schemas": "built-in tool schemas",
    "mcp_tool_schemas": "MCP tool schemas",
    "claude_md": "CLAUDE.md",
    "skills": "skill listings",
}


def estimate_tokens(text):
    """Heuristic token estimate for a string: ~4 chars per token."""
    if not text:
        return 0
    return max(0, int(len(text) / CHARS_PER_TOKEN))


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError as exc:
        warnings.warn("cannot read metric input %r: %s; ignoring it" %
                      (path, exc), RuntimeWarning, stacklevel=2)
        return None


def _nonnegative_int(value, field):
    """Coerce a report value to a finite, non-negative integer."""
    if isinstance(value, bool):
        raise ValueError("%s must be a non-negative finite number" % field)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a non-negative finite number" % field)
    if not math.isfinite(number) or number < 0:
        raise ValueError("%s must be a non-negative finite number" % field)
    return int(number)


class PreambleModel:
    """Per-Task-call fixed preamble, broken into named components."""

    def __init__(self, overrides=None, claude_md_path=None,
                 skills_dir=None, mcp_tax_report=None):
        self.components = dict(DEFAULT_COMPONENTS)
        self.sources = {k: "default (heuristic)" for k in self.components}
        #: per MCP server token costs, when a mcp-tax report is imported
        self.per_mcp_server = {}
        #: per skill token costs, when a skills dir is measured
        self.per_skill = {}

        for key, value in (overrides or {}).items():
            if key not in self.components:
                raise ValueError("unknown component %r (known: %s)"
                                 % (key, ", ".join(sorted(self.components))))
            self.components[key] = _nonnegative_int(value, key)
            self.sources[key] = "override --set"

        if claude_md_path:
            text = _read_text(claude_md_path)
            if text is not None:
                self.components["claude_md"] = estimate_tokens(text)
                self.sources["claude_md"] = "measured: %s" % claude_md_path

        if skills_dir:
            measured_skills = _measure_skills(skills_dir)
            if measured_skills is not None:
                self.per_skill = measured_skills
                self.components["skills"] = sum(self.per_skill.values())
                self.sources["skills"] = "measured: %s" % skills_dir

        if mcp_tax_report:
            self.per_mcp_server = _import_mcp_tax(mcp_tax_report)
            self.components["mcp_tool_schemas"] = sum(
                self.per_mcp_server.values())
            self.sources["mcp_tool_schemas"] = \
                "measured: mcp-tax report %s" % mcp_tax_report

    @property
    def total_per_call(self):
        """Estimated fixed preamble tokens resent by every Task call."""
        return sum(self.components.values())

    def cost_per_call_usd(self, price_per_mtok):
        return self.total_per_call / 1e6 * price_per_mtok


def _measure_skills(skills_dir):
    """Map skill name -> heuristic tokens from each SKILL.md found."""
    if not os.path.isdir(skills_dir):
        warnings.warn("cannot read metric input %r: not a directory; "
                      "ignoring it" % skills_dir, RuntimeWarning,
                      stacklevel=2)
        return None
    found = {}
    for root, _dirs, files in os.walk(skills_dir):
        for fn in files:
            if fn == "SKILL.md":
                name = os.path.basename(root)
                text = _read_text(os.path.join(root, fn))
                if text is not None:
                    found[name] = found.get(name, 0) + estimate_tokens(text)
    return found


def _import_mcp_tax(report_path):
    """Import per-server est_tokens from `mcp-tax audit --json` output.

    Boundary with mcp-tax: mcp-tax audits live MCP schema totals; this
    function just consumes its numbers as the "MCP tool schemas" preamble
    component that gets re-sent on every subagent call.
    """
    try:
        with open(report_path, "r", encoding="utf-8") as fh:
            rows = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ValueError("cannot read mcp-tax report %r: %s"
                         % (report_path, exc))
    if isinstance(rows, dict):  # tolerate {"servers": [...]} wrappers
        rows = rows.get("servers")
    if not isinstance(rows, list):
        raise ValueError("invalid mcp-tax report %r: expected a list of "
                         "servers" % report_path)
    out = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("ok", True):
            continue
        name = row.get("name", "unknown")
        if not isinstance(name, (str, int, float, bool)):
            name = "unknown"
        name = str(name)
        tokens = row.get("est_tokens")
        try:
            if tokens is None:  # fall back to chars/4 like mcp-tax does
                chars = _nonnegative_int(row.get("schema_chars", 0),
                                         "schema_chars")
                tokens = int(chars / CHARS_PER_TOKEN)
            else:
                tokens = _nonnegative_int(tokens, "est_tokens")
        except ValueError as exc:
            warnings.warn("ignoring invalid mcp-tax row for %r: %s" %
                          (name, exc), RuntimeWarning, stacklevel=2)
            continue
        out[name] = out.get(name, 0) + tokens
    return out
