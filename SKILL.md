---
name: weekly-confluence-update
description: Draft the current user's weekly status update into a Confluence weekly-report page by researching their Jira, Slack, and Outlook activity, then render a local HTML preview and only publish back to Confluence after the user approves. Use this skill whenever the user mentions weekly updates, weekly status reports, weekly reports, a Confluence weekly page, "fill in my weekly," "draft my status," platform/engineering weekly roll-ups, or pastes a Confluence URL that looks like a recurring weekly report — even if they don't explicitly say "skill" or "draft." Also use when a manager asks for help summarizing their team's week from Jira/Slack/email.
---

# Weekly Confluence Update

This skill takes a Confluence weekly-report page URL, figures out which sections on it are assigned to the current authenticated user and their team, researches what happened that week across Jira / Slack / Outlook, drafts terse, append-only updates in-place, shows a local HTML preview, and only publishes after explicit approval.

The people using this skill are engineering managers filling out a shared weekly roll-up page that many leads write into. The document is **shared** — the skill must touch only the user's own content, never overwrite anyone else's, and never restructure the page.

## Invocation

Users invoke this skill with a Confluence page URL and a team name:
```
<confluence-page-url> <team-name>
```
e.g. `https://<your-tenant>.atlassian.net/wiki/spaces/<space>/pages/<id>/... Platform`

The team name is required — it's the label that will appear as the bolded heading in the user's team block on the page. Do not try to guess it from context.

If the invocation is `init <team-name>` (or anything clearly asking to set up / add members / edit the roster for a team), jump to Phase 0 below instead of the normal workflow.

## What this skill does and does not do (blast radius at a glance)

| Action | Scope | When |
|---|---|---|
| Call `updateConfluencePage` (publish to live page) | Remote write | Phase 8, ONLY after explicit `approve` |
| Write `config/teams/<slug>.json` | Local write | Phase 0 init or Phase 1b roster confirm — path announced first |
| Write `/tmp/weekly-preview-*.html`, `modified.json`, drafts JSON, `.cache/` | Local writes | Phases 4, 6, 7 |
| Read page/issues/messages/email via MCP | Remote reads only | Phases 1, 1b, 4 |
| Run `open <path>` to launch browser | Local | Phase 7 |
| Send messages, comment on tickets, post to Slack/email | **Never** | — |
| Delete Confluence content, change status macros, reorder page | **Never** | — |

If you see the skill about to do anything outside this table, stop it. That's a bug.

## Prerequisites

The invoking environment must have these MCP servers connected:
- Atlassian (Confluence + Jira) — for page read/write and Jira search
- Slack — for `slack_search_public` (and `slack_search_public_and_private` if available)
- Outlook / M365 — for `outlook_email_search`

**Team roster is auto-discovered, not hand-maintained.** On first run for a given team, the skill infers members by inspecting prior weekly pages in the same Confluence space (whoever has been authoring `**<TeamName>**` blocks IS the team) and cross-checks with Slack channel membership and Jira recent co-assignees. It presents the inferred roster to the user for one-time confirmation, then caches it at `config/teams/<team-name>.json`. Subsequent runs reuse the cache. See Phase 1b for the discovery procedure.

## Workflow

Work through these phases sequentially. Do not skip phases; each one depends on artifacts from the previous.

### Phase 0 — Init / edit the team roster (only if the user asked to)

Trigger: user says `init <team-name>`, `add <name> to <team>`, `remove <name> from <team>`, "set up my team", or similar intent.

Goal: produce or update `config/teams/<team-slug>.json` without the user ever opening the file.

**Side effects in this phase:**
- Reads: `atlassianUserInfo`, `lookupJiraAccountId`, `slack_search_users`
- Writes locally: `config/teams/<team-slug>.json` (announce the exact path before writing)
- Writes remotely: none

Procedure:

1. Resolve the active tenant. Call `atlassianUserInfo` once (you'll need it anyway). Extract the tenant hostname from a URL the user gives you, or ask.
2. Load any existing `config/teams/<slug>.json`. If present, show the current roster to the user:
   ```
   Current <Team> roster:
     1. Alex Example — alex.example@company.com
     2. Jordan Sample — jordan.sample@company.com
   Reply with edits: "add <name>", "remove <name>", "done", or just list the new full roster.
   ```
3. If the user provides names (bare list, or `add: X, Y, Z`), resolve each in parallel:
   - `lookupJiraAccountId` with the name (returns `accountId`, `email`)
   - `slack_search_users` with the name (returns `user_id`, `email`)
4. When the Jira lookup returns multiple matches (very common for first names), disambiguate by email match with the Slack result, or by showing the top 3 and asking the user.
5. For each member, capture `{display_name, atlassian_account_id, slack_user_id, email, confidence: "confirmed", signals: ["user_confirmed"]}`.
6. If the team is brand-new and `jira_projects` / `slack_channels` / `email_keywords` aren't yet known, ask once, conversationally:
   ```
   What Jira project keys should I search for <Team>'s work? (comma-separated, e.g. PLAT, API)
   Any team Slack channels? (e.g. #platform, #platform-standup)
   Any keywords that identify <Team> work in email subjects? (e.g. API gateway, Platform)
   ```
   All three are optional; empty answers are fine.
7. Write `config/teams/<team-slug>.json` (lowercase, spaces → hyphens) following the schema in `references/data-sources.md`. Preserve any `topic_map` or `page_layout` from the existing file.
8. Report a one-line summary:
   ```
   Saved config/teams/<slug>.json — N members, Jira projects: [...], Slack channels: [...].
   You can now run the skill normally with any weekly-report URL.
   ```
9. If the user didn't ask you to run the weekly update too, stop here. Otherwise continue to Phase 1 with the team they just set up.

Do not invent team members. Do not populate Jira projects from your own guesses — ask or leave empty.

### Phase 1 — Identify the user and the page

**Side effects:** read-only Atlassian calls (`atlassianUserInfo`, `getConfluencePage`, `getAccessibleAtlassianResources`). No writes anywhere.

1. Call `atlassianUserInfo` once. Record `account_id`, `name`, and `email`. This is the ground truth for "the current user" — do NOT rely on display-name matching, which breaks on punctuation, middle initials, and duplicate names.
2. Resolve `cloudId` from the page URL hostname (e.g. `<tenant>.atlassian.net` — pass the hostname as `cloudId`; if that fails, call `getAccessibleAtlassianResources`).
3. Extract `pageId` from the URL (the numeric ID after `/pages/`).
4. Fetch the page with `contentFormat: "adf"` — never markdown. ADF preserves mention `id`s, which is how we identify assignments.
5. If the ADF response is large (common for weekly pages), it will be saved to a file. Pass the file path to `scripts/parse_page.py` rather than loading into context.

### Phase 1b — Discover or load the team roster

**Side effects:** read-only calls (`getConfluencePage`, `getConfluencePageDescendants`, `slack_search_channels`, `searchJiraIssuesUsingJql`, `lookupJiraAccountId`). May write `config/teams/<team-slug>.json` locally only after user confirms the inferred roster — announce the path first.

Look for `config/teams/<team-name-lowercase>.json` under the skill directory. If it exists, load it and skip to Phase 2. Otherwise, discover the team:

1. **Parent-space sweep.** Get the parent page with `getConfluencePage` and list its descendants via `getConfluencePageDescendants` (limit to recent pages, typically titled `Weekly Report...`). Read the 3–5 most recent prior weekly pages in ADF.
2. **Mine prior team blocks.** In each prior page, locate `**<TeamName>**` blocks in the same row as the current page's Highlights-equivalent row. Extract mentions that occur in that block's vicinity (the paragraphs up to the next strong-only heading) and any author attributions.
3. **Slack cross-check.** `slack_search_channels` for channels whose name contains the team slug. For top matches, list their members via Slack, filtered to humans.
4. **Jira cross-check.** `searchJiraIssuesUsingJql` for `assignee in membersOf("<group>") OR component = "<TeamName>"` — if that JQL errors, fall back to recent issues authored or updated by the user and look at frequent co-assignees.
5. **Merge and deduplicate.** Union the three signal sets. Resolve Atlassian account IDs via `lookupJiraAccountId`. Present the candidate roster to the user inline:

   ```
   Inferred <Team> roster (confirm/edit):
     - Alex Example  <atlassian: 712020:abc..., slack: U01...>  [signals: confluence prior, slack, jira]
     - Jordan Sample <atlassian: 712020:xyz..., slack: ?>        [signals: confluence prior]
     - ...
   Remove anyone who isn't on your team, or name anyone missing. Reply "confirm" to cache.
   ```
6. **Cache on confirm.** After approval, write `config/teams/<team-slug>.json` following the schema in `references/data-sources.md`. Do not overwrite an existing cache without prompting.

If signals are weak (e.g. new team, no prior pages), ask the user for the roster directly rather than publishing guesses. Don't fabricate team membership.

### Phase 2 — Map sections and find the user's assignments

**Side effects:** local script execution only (`scripts/parse_page.py sections`). No network calls, no writes.

Run `scripts/parse_page.py sections <adf-file> --user-id <account_id> --team-config config/teams/<team-slug>.json`. It emits a JSON structural map — see `references/confluence-parsing.md` for the full schema.

Output section `kind` values and how to handle each:

1. **`explicit_assignment_with_team_block`** — the user is @-mentioned in a prompt paragraph in this row AND a team block (e.g. bolded `**<TeamName>**`) already exists in the row's update cell. Append bullets after that existing team block.
2. **`explicit_assignment_no_team_block`** — the user is @-mentioned but their team has no block yet in the update cell. Create one: `**<TeamName>**` paragraph + bullet list, appended at the end of the update cell.
3. **`team_owned`** — the user is NOT @-mentioned in the row's prompt, but their team has a block in the update cell. Append bullets to the team block. Common case: a row targeting other team leads where the user's team still has its own sub-section.
4. **`team_only_row`** — global rows like Product Releases Completed / Challenges / Organization/Hiring/Resignations. Append a `**<TeamName>:**` paragraph + bullets at the end of the update cell, scoped strictly to the user's team.

Rows in `skipped_rows` are intentionally not written to — they're @-mentioned prompts for other teams with no matching team block for the user.

Present the section map to the user before researching. One-line per section:
`[<kind>] <row_label> → <action>`. Ask them to confirm or correct before spending tokens on research.

### Phase 3 — Determine date range

**Side effects:** local script execution only.

The date range comes from the page title (e.g. `Weekly Report, 13 Apr - 17 Apr 2026`). Parse it with `scripts/parse_page.py --extract-dates`.

If the title has no parseable range, ask the user for start and end dates before continuing — do not guess.

### Phase 4 — Research the week

**Side effects:** read-only external searches (`searchJiraIssuesUsingJql`, `slack_search_public`, `outlook_email_search`). Writes a local research cache under `.cache/<pageId>/<YYYY-MM-DD>/` so re-runs skip the API calls. Nothing published anywhere.

For each section the user owns, gather evidence from Jira, Slack, and Outlook for the date range, scoped to the topics requested in that section's prompt (or to the team's work if it's a team-ownership block). Full query patterns live in `references/data-sources.md`. Summary:

- **Jira**: `assignee in (currentUser(), <team account_ids>) AND updated >= "<start>" AND updated <= "<end>"`. For the "Product Releases Completed" row, query `fixVersion released during ("<start>","<end>") AND project in (<team projects>)`.
- **Slack**: search `from:@<user>` in team channels for the window, and search the team channels for status-style keywords (`released`, `merged`, `blocked`, `escalation`, `CVE-`).
- **Outlook**: search for sent/received mail in the window with subjects containing topic keywords from the section's prompt and customer names.

Do these searches in parallel — they're independent and the window is fixed. Cache raw results under `.cache/<pageId>/<YYYY-MM-DD>/` as JSON so re-runs don't re-query.

### Phase 5 — Draft updates

**Side effects:** none — this phase is pure reasoning over cached research.

Two distinct output shapes depending on section kind — see `references/output-style.md` for detailed examples:

- **Team-block sections** (`explicit_assignment_*`, `team_owned`): write **paragraph-per-topic**, not bullets. Each topic is a subject phrase, an en-dash, then one dense paragraph (60–120 words) with multiple status clauses covering every active workstream under that topic. Think 2–5 paragraphs per team block. Jira/CVE/ticket keys inline.
- **Team-only rows** (Challenges / Org / Hiring): flat bullets, 1–3 per row, only if there's something to report. Skip the row entirely if nothing.

Every sentence must trace to a Jira ticket, Slack message, or email. No invention. Match the page's existing status vocabulary — scan neighboring sections for the words it uses (`In Progress`, `Blocked`, `On Track`, `Delayed`, `Done`) and stay consistent.

### Phase 6 — Build the modified ADF

**Side effects:** writes two local files — the drafts JSON and the modified ADF JSON (paths announced before writing). No network calls. The original cached ADF is not mutated.

Write a drafts file keyed by the `update_cell_path` of each section, then run:
```
scripts/parse_page.py build-patch <original-adf-file> --drafts <drafts.json> > modified.json
```

Drafts file shape:
```json
{
  "<update_cell_path>": {
    "kind": "append_to_team_block" | "new_team_block" | "team_only_row_contribution",
    "team_block_path": "<only for append_to_team_block>",
    "team_name": "Platform",
    "paragraphs": [
      "API gateway migration \u2013 new rate-limiter rolled to staging; load test at 2x peak completed clean. Customer allow-list import tool merged (PLAT-1234). Canary still pending SRE sign-off; target production cutover next sprint.",
      "Observability \u2013 OTel SDK bump landed across two services; dashboards regenerated (OBS-456). Log-retention policy change awaiting InfoSec review.",
      "Two CVEs resolved this week:",
      "CVE-2025-XXXX (library-a) \u2014 patched across three services; Mend confirms clean. CVE-2025-YYYY (library-b) tracked separately under SEC-789."
    ],
    "bullets": ["... only for team_only_row_contribution ..."]
  }
}
```
Use `paragraphs` for team-block sections. Use `bullets` for `team_only_row_contribution`. Never mix both on one section.

The script does not mutate the input. Every node it inserts gets a sentinel attr `_skillAdded: true` so the preview can highlight added content and so the publish step can distinguish additions from pre-existing content. Do not attempt to hand-craft ADF — use the helper.

Never create new table rows or cells. Never reorder existing content. Never change `status` macros.

### Phase 7 — Render preview

**Side effects:** writes `/tmp/weekly-preview-<pageId>.html` locally and runs `open <path>` to launch the default browser. No network calls, no Confluence writes.

Run `scripts/render_preview.py <modified-adf.json> --title "<page title>" --out /tmp/weekly-preview-<pageId>.html`. It produces a standalone HTML file that renders the modified page with **your additions highlighted in yellow**, so the user can see exactly what's being added. Open it with `open <path>` on macOS.

Tell the user: "Preview opened at `<path>`. Review the yellow-highlighted additions. Reply `approve`, `edit <section>: <change>`, or `cancel`."

### Phase 8 — Publish on approval

**Side effects — this is the only phase that mutates anything outside the local workspace:**
- Calls `updateConfluencePage` on the live Confluence page — this overwrites the current page body with the modified ADF and bumps the version.
- Deletes the local `.cache/<pageId>/` directory after a successful publish.
- Never runs unless the user replies with explicit approval. Surface the target URL before calling.

Only after the user replies with an unambiguous approval (e.g. "approve", "looks good, publish", "ship it"):

1. Strip the `_skillAdded` sentinels so Confluence doesn't reject unknown attrs:
   ```
   scripts/parse_page.py strip-sentinels modified.json > publish.json
   ```
2. Call `updateConfluencePage` with the content of `publish.json` as the body. Pass the page's current `version.number + 1` as the new version.
3. Echo the page URL back to the user and delete the `.cache/` directory.

Rules:
- Never publish on implicit cues like "thanks" or "ok".
- On "edit <section>: <change>", re-draft only that section, rerun build-patch + render, re-ask for approval.
- On "cancel", delete the preview file and stop.

## Safety rules

- **Append-only.** Never delete or modify content authored by other people. If in doubt, don't write.
- **Never fabricate.** Each bullet must cite a ticket, message, or email (at minimum by Jira key or clear attribution). If research comes up empty for a section, say so in the preview and let the user fill it in manually — do not invent filler.
- **Team scope.** Releases and challenges must be the user's team's, not anyone else's. Cross-check every release against `config/team.json` project/repo ownership before including it.
- **Private Slack.** Only search private channels if explicitly authorized for this run. Default to `slack_search_public` only.
- **No new structure.** Do not add headings, panels, tables, or rows. Append inside existing cells only.

## Files in this skill

- `references/confluence-parsing.md` — ADF shape, mention node structure, the section-mapping algorithm
- `references/data-sources.md` — Jira JQL, Slack, Outlook query patterns and the `team.json` schema
- `references/output-style.md` — Terse clause style, bolded status words, Jira-key inlining
- `scripts/parse_page.py` — ADF parser, section mapper, date extractor, patch builder
- `scripts/render_preview.py` — Modified-ADF → standalone HTML with diff highlighting
- `config/team.example.json` — Template for the user's team roster
