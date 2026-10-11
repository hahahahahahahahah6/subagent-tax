"""subagent-tax CLI: estimate subagent preamble resend cost from transcripts."""
from __future__ import annotations

import argparse
import math
import sys

from . import __version__
from .analyzer import scan, default_projects_dir
from .ledger import (DEFAULT_TURNS_PER_TASK, DEFAULT_SPAWN_OVERHEAD_TOKENS)
from .model import (PreambleModel, DEFAULT_COMPONENTS,
                    DEFAULT_PRICE_INPUT_PER_MTOK)
from .report import aggregate, render_text, render_json


def _parse_set(pairs):
    overrides = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit("error: --set expects name=tokens, got %r" % pair)
        name, _, value = pair.partition("=")
        name = name.strip()
        if name not in DEFAULT_COMPONENTS:
            raise SystemExit("error: unknown component %r (known: %s)" % (
                name, ", ".join(sorted(DEFAULT_COMPONENTS))))
        try:
            overrides[name] = int(value)
        except ValueError:
            raise SystemExit("error: --set %s needs an integer, got %r"
                             % (name, value))
        if overrides[name] < 0:
            raise SystemExit("error: --set %s must be non-negative" % name)
    return overrides


def _nonnegative_float(value):
    try:
        result = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number")
    if not math.isfinite(result) or result < 0:
        raise argparse.ArgumentTypeError("must be non-negative and finite")
    return result


def _nonnegative_int(value):
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer")
    if result < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return result


def build_parser():
    p = argparse.ArgumentParser(
        prog="subagent-tax",
        description="Estimate how many tokens (and dollars) Claude Code "
                    "subagent calls waste re-sending the fixed preamble.")
    p.add_argument("paths", nargs="*", metavar="TRANSCRIPT",
                   help="transcript .jsonl file(s) or director(ies); "
                        "default: scan ~/.claude/projects")
    p.add_argument("--projects-dir", default=None,
                   help="Claude Code projects dir (default: %s)"
                   % default_projects_dir())
    p.add_argument("--mcp-tax-report", default=None, metavar="JSON",
                   help="mcp-tax audit --json output: per-server schema "
                        "tokens become the MCP preamble component")
    p.add_argument("--claude-md", default=None, metavar="PATH",
                   help="measure your CLAUDE.md instead of the heuristic")
    p.add_argument("--skills-dir", default=None, metavar="DIR",
                   help="measure SKILL.md files under DIR for the skills "
                        "component (per-skill ranking included)")
    p.add_argument("--set", action="append", default=[],
                   metavar="name=tokens",
                   help="override a preamble component "
                        "(%s); repeatable" % ", ".join(
                            sorted(DEFAULT_COMPONENTS)))
    p.add_argument("--price-input", type=_nonnegative_float,
                   default=DEFAULT_PRICE_INPUT_PER_MTOK, metavar="USD",
                   help="input price USD per MTok (default %.2f; verify "
                        "current published pricing)"
                   % DEFAULT_PRICE_INPUT_PER_MTOK)
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.add_argument("--top", type=_nonnegative_int, default=5,
                   help="ranked contributions to show (default 5)")
    p.add_argument("--turns-per-task", type=_nonnegative_int,
                   default=DEFAULT_TURNS_PER_TASK, metavar="N",
                   help="heuristic API turns inside each subagent call "
                        "(default %d; parent transcripts do not show "
                        "internal turns)" % DEFAULT_TURNS_PER_TASK)
    p.add_argument("--spawn-overhead", type=_nonnegative_int,
                   default=DEFAULT_SPAWN_OVERHEAD_TOKENS, metavar="TOKENS",
                   help="fixed token overhead per Task() call: the Task "
                        "payload plus result handling (default %d, "
                        "heuristic)" % DEFAULT_SPAWN_OVERHEAD_TOKENS)
    p.add_argument("--cache-hit-rate", type=_nonnegative_float, default=0.0,
                   metavar="F",
                   help="fraction of later-turn preamble served from prompt "
                        "cache, 0..1 (default 0.0; the spawn turn is always "
                        "cache-cold)")
    p.add_argument("--version", action="version",
                   version="subagent-tax " + __version__)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        model = PreambleModel(
            overrides=_parse_set(args.set),
            claude_md_path=args.claude_md,
            skills_dir=args.skills_dir,
            mcp_tax_report=args.mcp_tax_report,
        )
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    tpaths, calls = scan(args.paths, projects_dir=args.projects_dir)
    if not tpaths:
        print("warning: no transcript files found", file=sys.stderr)
    try:
        agg = aggregate(calls, model, args.price_input, top=args.top,
                        turns_per_call=args.turns_per_task,
                        spawn_overhead=args.spawn_overhead,
                        cache_hit_rate=args.cache_hit_rate)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    if args.format == "json":
        sys.stdout.write(render_json(agg))
    else:
        sys.stdout.write(render_text(agg, calls, model, top=args.top))
    return 0
