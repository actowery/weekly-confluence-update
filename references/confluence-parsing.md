# Confluence ADF parsing

Why ADF, not markdown: ADF preserves `mention` node `id`s (Atlassian account IDs). Display names collide and punctuation varies. Always fetch and operate on ADF for assignment detection.

## Relevant node shapes

### Mention node
```json
{
  "type": "mention",
  "attrs": {
    "id": "712020:0000aaaa-bbbb-cccc-dddd-000000000000",
    "localId": "a5a6e0a6-4f74-437e-90be-08162c4e1393",
    "text": "@Alex Example"
  }
}
```
The `id` format varies across Atlassian accounts:
- 24-hex legacy: `000000000000000000000001` (24 hex chars, no prefix)
- Prefixed UUID: `712020:0000aaaa-bbbb-cccc-dddd-000000000000` (6-digit prefix, then UUID)
- Other prefixes: `557058:...`, `70121:...` (same shape, different prefix)

Match on `id` string equality only.

### Cell / paragraph structure
Weekly-report pages in the wild tend to be structured as one large 2-column table (`Category | Update`). Prompts like "@X @Y please provide weekly updates for: ..." sit inside the right-column cell of a row, followed by bullet lists of topics, followed by team-authored sub-sections (bolded team name + prose or bullets).

A section owned by a team is recognizable as:
```json
{"type":"paragraph","content":[
  {"type":"text","text":"Platform","marks":[{"type":"strong"}]}
]}
```
followed by `paragraph` or `bulletList` nodes until the next bold sub-heading or the cell ends.

## Section-mapping algorithm

`scripts/parse_page.py` implements this. Steps:

1. Walk the ADF tree. Track a path like `table[1]/row[3]/cell[1]/paragraph[2]` so every finding has a location.
2. For each `paragraph` that contains a `mention` node AND the phrase `"provide weekly updates"` (case-insensitive), record it as a **prompt paragraph**. The enclosing `tableCell` is an **assignment cell**. Capture:
   - the set of mentioned `account_id`s
   - the bullet list(s) that immediately follow, as the "topics requested"
3. For each `paragraph` in any cell whose sole content is a `strong`-marked text node matching a known team name (from `team.json`), record it as a **team-ownership block**. The block spans until the next team-ownership block or cell end.
4. For the **current user**:
   - Sections they're **explicitly assigned**: every assignment cell whose prompt paragraph mentions their `account_id`.
   - Sections **owned by their team**: every team-ownership block whose bolded name matches `team.json:team_name`.
5. Identify **global team-only rows** by matching left-column cell text against a small vocabulary: `{"Product Releases Completed", "Releases", "Challenges", "Organization", "Hiring", "Resignations", "Organization, Hiring, Resignations, etc"}` — substring match, case-insensitive.
6. Return a JSON map:
```json
{
  "page_title": "...",
  "date_range": {"start": "2026-04-13", "end": "2026-04-17"},
  "sections": [
    {
      "kind": "explicit_assignment",
      "path": "table[0]/row[4]/cell[1]",
      "prompt_text": "@Alex Example ... please provide weekly updates for:",
      "mentioned_account_ids": ["712020:0000aaaa-bbbb-cccc-dddd-000000000000", ...],
      "topics": ["PE Features", "Resiliency for CA & Walmart active active", ...],
      "existing_team_block": {"path": "...", "last_paragraph_index": N} | null
    },
    { "kind": "team_owned", "path": "...", "team_name": "Platform", ... },
    { "kind": "team_only_row", "path": "...", "row_label": "Challenges" }
  ],
  "skip_cells": ["table[0]/row[4]/cell[1] — other-team blocks", ...]
}
```

## Date extraction

The page title (not body) usually carries the range. Common formats to handle:
- `Weekly Report, 13 Apr - 17 Apr 2026 (Platform Automation)` — day-month pair with shared year
- `Weekly Report 2026-04-13 to 2026-04-17`
- `Weekly Update Apr 13, 2026`
- `Week of 2026-04-13`

`parse_page.py --extract-dates` uses regexes + `dateutil` to normalize to ISO `start`/`end`. If it can't, it exits non-zero with a message, and the skill must ask the user.

## Patch building

`parse_page.py --build-patch <drafts.json>` takes drafts keyed by section path:
```json
{
  "table[0]/row[4]/cell[1]": {
    "kind": "append_to_team_block",
    "team_name": "Platform",
    "paragraphs": [
      "API gateway migration \u2013 rate-limiter v2 on staging, load test clean (PLAT-1234).",
      "CVE batch \u2013 library-a, library-b patched; Mend fixes merged."
    ]
  }
}
```
and emits a full modified ADF document. It does not mutate the input. Reading it before invoking is a good idea so you understand the exact insertion semantics if something looks wrong in the preview.

## Common pitfalls

- **Duplicate mentions in a prompt**: real pages sometimes list the same person twice. Dedupe by `account_id`.
- **hardBreak inside paragraphs**: per-team counts (e.g. Mend row) use `hardBreak` nodes between teams rather than separate paragraphs. Don't parse "one paragraph per team" — use the text between hardBreaks.
- **Empty Update cells**: a cell may be blank this week. Adding a new team block is allowed; adding a new bulleted contribution to a global row is allowed.
- **`status` macro nodes** at the top of the page (`Not started`/`In Review`/etc.): never change these. They track doc-level completion workflow.
- **`inlineCard` / smart links**: preserve as-is when rebuilding — don't try to re-resolve URLs.
