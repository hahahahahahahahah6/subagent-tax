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

## Billing model: per-turn re-entry (v0.3)

The old model (v0.2 and earlier) billed the preamble **once per `Task()`
call**: 51K tokens in, done. That undercounts, twice:

1. **Per-turn re-entry.** The fixed preamble is not paid once per call — it
   re-enters the model context on **every API call (turn)** inside the
   subagent, the same correction mcp-tax 0.3 made for MCP schemas (thanks to
   dev.to reader **MCPulse** for pressing on this). A 51K preamble in a
   3-turn subagent is a 153K tax, not a 51K tax.
2. **The subagent multiplier.** Every `Task()` call spawns a brand-new
   context, so the full preamble is re-paid on spawn — a true amplifier.
   Measured in the wild by dev.to reader **aidiveyt**: 2,631 subagent runs
   ate **48.1%** of all tokens.

The report now ends with a **per-turn re-entry ledger**: one billing line per
`subagent_type`, with an explicit `subagent_multiplier` column (how many
fresh contexts each type spawned), per-call spawn overhead (`--spawn-overhead`,
default 2,000 heuristic tokens for the Task payload + result handling), and
per-turn preamble re-injection (`--turns-per-task`, default 3, heuristic —
parent transcripts don't show a subagent's internal turns).

**Cache TTL miss:** a fresh subagent starts with a cold cache, so the spawn
turn is always billed at full price even when later turns hit the prompt
cache (`--cache-hit-rate`, default 0.0). And as in mcp-tax 0.3, caching only
lowers the *price*, never the window occupancy — the ledger keeps
`billable_tokens` and `cumulative_window_tokens` as separate columns.

The old spawn-only number is kept in the JSON output as `old_model_tokens`
so you can see exactly how much it undercounted.

## Boundary with mcp-tax

`mcp-tax` audits the **total size** of your MCP server schemas (how much
context one audit costs) and, since v0.3, bills them **per turn** with a
per-server ledger. `subagent-tax` shares that exact billing framework but
focuses on the **subagent side**: the multiplier (every `Task()` re-pays the
full preamble on spawn), the per-call spawn overhead, and the cache TTL miss
at spawn — none of which exist in the MCP-server world. The two compose: run
`mcp-tax audit --json > mcp.json`, then feed it to
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

# tune the corrected billing model
subagent-tax --turns-per-task 5 --spawn-overhead 1500 --cache-hit-rate 0.5
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

Per-turn re-entry ledger (corrected billing model, same framework as mcp-tax 0.3)
  turns per Task call: 3 (heuristic; --turns-per-task) | spawn overhead: 2,000 tok/call | cache hit rate: 0% (spawn turn always cold)

  subagent_type     calls multiplier per-call tok   window tok billable tok
  Explore              90         90      155,000   13,950,000   13,950,000
  Plan                 31         31      155,000    4,805,000    4,805,000
  (default)            11         11      155,000    1,705,000    1,705,000
  TOTAL                                                20,460,000   20,460,000  ~= $61.38

  Old model (v0.2, spawn-only) counted 6,732,000 tokens; corrected ledger counts
  20,460,000 — the old model undercounted by a factor of 3.0x.
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
- **Ledger turn counts and spawn overhead are heuristic.** Parent
  transcripts don't show a subagent's internal turns, so
  `--turns-per-task` (default 3) is a placeholder: measure or guess yours.
  `--spawn-overhead` (default 2,000 tokens) likewise approximates the Task
  payload plus result handling, not exact bytes.
- **"Waste" is a simplification.** Preamble tokens are genuinely billed, but
  some preamble (e.g. tool schemas the subagent actually uses) is working
  context, not pure waste. Treat the ranking as "where to look first", not a
  refund claim.

## License

MIT
