# subagent-tax

Estimate how much of your Claude Code bill is subagent preamble resends.

Every `Task()` (subagent) call re-sends a fixed preamble — the system prompt,
the full tool-schema definitions, `CLAUDE.md`, and skill listings — before the
subagent even reads your prompt. One measurement put that fixed preamble at
~51K tokens per call, with subagents eating 48% of the bill while producing
0.9% of the output (dev.to @ji_ai, *"Claude Code Subagents Were 48% of My
Bill. Their Output Was 0.9%"*).

`subagent-tax` scans your `~/.claude/projects` transcript history, counts
completed successful subagent invocations, multiplies by the preamble model,
and tells you —
in tokens and dollars — which parts of the preamble are worth trimming.

## Boundary with mcp-tax

`mcp-tax` audits the **total size** of your MCP server schemas (how much
context one audit costs). `subagent-tax` audits the **repeat cost**: how many
tokens get **re-sent on every single subagent call** because that preamble is
fixed. The two compose: run `mcp-tax audit --json > mcp.json`, then feed it to
`subagent-tax --mcp-tax-report mcp.json` and the per-server schema costs show
up as per-call resend costs with per-server trim suggestions.

## Install

```bash
pip install subagent-tax
```

Zero dependencies, stdlib only. Requires Python 3.9+.

## Usage

```bash
# scan all Claude Code transcripts
subagent-tax

# scan specific transcripts / dirs
subagent-tax ~/my-session.jsonl ~/.claude/projects/my-project

# calibrate with your real files instead of heuristics
subagent-tax --claude-md ~/myproject/CLAUDE.md --skills-dir ~/.claude/skills

# import per-server schema sizes from mcp-tax
mcp-tax audit --json > /tmp/mcp.json
subagent-tax --mcp-tax-report /tmp/mcp.json

# override any preamble component, set pricing, JSON output
subagent-tax --set system_prompt=15000 --price-input 3.00 --format json
```

Example output:

```
subagent-tax report
==================
Task (subagent) calls : 132 across 18 session(s)
By subagent_type     : Explore=90, Plan=31, (default)=11

Preamble model: tokens re-sent per Task call [heuristic]
  system prompt            20,000 tok   (default (heuristic))
  built-in tool schemas     8,000 tok   (default (heuristic))
  MCP tool schemas         16,000 tok   (measured: mcp-tax report /tmp/mcp.json)
  CLAUDE.md                 3,000 tok   (measured: /home/you/proj/CLAUDE.md)
  skill listings            4,000 tok   (measured: /home/you/.claude/skills)
  TOTAL per call           51,000 tok

Estimated waste: 132 calls x 51,000 tok = 6,732,000 tokens ~= $20.20
(input pricing $3.00/MTok; override with --price-input)

Cuttable contributions (tokens per Task call):
  1. system prompt                20,000 tok/call
  2. MCP server: playwright       10,000 tok/call
  3. built-in tool schemas         8,000 tok/call
  ...

Top trim suggestion:
  Slim down (custom system prompt) system prompt: saves ~20,000 tokens
  per Task call (~$7.92 at 132 observed calls)
```

## The preamble model

Components and defaults (tokens per `Task` call). The defaults sum to
**51,000**, the measured fixed preamble from the article linked above:

| component | default | override / measure with |
|---|---|---|
| system prompt | 20,000 | `--set system_prompt=N` |
| built-in tool schemas | 8,000 | `--set builtin_tool_schemas=N` |
| MCP tool schemas | 16,000 | `--mcp-tax-report` (per-server breakdown) |
| CLAUDE.md | 3,000 | `--claude-md PATH` (measured chars/4) |
| skill listings | 4,000 | `--skills-dir DIR` (per-skill breakdown) |

## Honest limitations

- **Token estimates are heuristic, not exact.** Without your real API request
  payloads we cannot count exact tokens; text is estimated at ~4 chars/token
  and component defaults are round placeholders. Measure your own setup with
  `--claude-md`, `--skills-dir`, `--mcp-tax-report`, or `--set`.
- **Dollar amounts use public pricing you supply.** The default `$3.00`/MTok
  input price is an example — verify current published Anthropic pricing and
  pass `--price-input`. Cached/discounted input tokens are not modeled.
- **Transcript coverage is local only.** It counts `Task` tool calls in local
  JSONL transcripts; subagents spawned via the API, deleted transcripts, or
  other harnesses are invisible to it.
- **"Waste" is a simplification.** Preamble tokens are genuinely billed, but
  some preamble (e.g. tool schemas the subagent actually uses) is working
  context, not pure waste. Treat the ranking as "where to look first", not a
  refund claim.

## License

MIT
