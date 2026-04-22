# Data sources

Three systems feed each draft: Jira, Slack, Outlook. Search them in parallel once the date range and the per-section topics are known.

## Team roster cache — `config/teams/<team-slug>.json`

Per-team file, lowercased team name with spaces replaced by hyphens (`Platform` → `platform.json`, `DevOps Tools` → `devops-tools.json`). This file is **auto-produced by Phase 0 init or Phase 1b discovery**, confirmed by the user, and cached for subsequent runs. It is not meant to be hand-authored — if you're tempted to, re-run init instead.

Schema:
```json
{
  "team_name": "Platform",
  "team_slug": "platform",
  "team_lead_account_id": "712020:...",
  "team_lead_slack_id": "U01...",
  "members": [
    {
      "display_name": "Alex Example",
      "atlassian_account_id": "712020:abcd...",
      "slack_user_id": "U01AB2CD3EF",
      "email": "alex.example@company.com",
      "confidence": "confirmed",
      "signals": ["user_confirmed"]
    }
  ],
  "jira_projects": ["PLAT", "API"],
  "slack_channels": ["#platform", "#platform-standup"],
  "email_keywords": ["Platform", "API gateway", "Observability"],
  "topic_map": {
    "API gateway migration": {"labels": ["api-gw"], "epic": "PLAT-1234"}
  },
  "page_layout": {
    "team_only_row_labels": ["product releases completed", "releases", "challenges", "organization", "hiring", "resignations"],
    "prompt_phrase_regex": "provide weekly updates"
  },
  "cached_at": "YYYY-MM-DD",
  "cache_source": "user_confirmed"
}
```

The `page_layout` block lets teams whose Confluence template uses different row names (e.g. "Blockers" instead of "Challenges", "Shipped" instead of "Product Releases Completed") or a different prompt phrasing ("please share updates on...") override what the parser looks for. If omitted, defaults are used.

`signals` captures how each member was discovered, so on a subsequent discovery pass you can see whether signals strengthened or weakened. `confidence` is one of `confirmed` (user said yes), `inferred_high` (all three signals agreed and user hasn't reviewed yet), `inferred_low`. The skill only publishes using `confirmed` members for team-only-row scoping.

Why this isn't inferred fully automatically on every run: inference is noisy (former members still show up in Slack channels, co-assignees include cross-team partners), and the weekly run happens fast. A cached roster that the user confirmed once beats re-inferring every Monday. The user can run a "refresh team" flow if their team composition changes.

## Jira

### User's own work
```sql
assignee = currentUser()
AND updated >= "<start>"
AND updated <= "<end>"
ORDER BY updated DESC
```

### Team's work (for releases / challenges / team-ownership blocks)
Build an `assignee in (...)` clause from `members[].atlassian_account_id`. Use `reporter in (...)` as a secondary query — some teams file issues for other teams.

### Completed releases only (for the "Product Releases Completed" row)
```sql
project in (<team_projects>)
AND fixVersion in releasedVersions()
AND fixVersion changed to "Released" during ("<start>", "<end>")
```
If that JQL is rejected, fall back to:
```sql
project in (<team_projects>)
AND status = Done
AND resolved >= "<start>"
AND resolved <= "<end>"
AND labels = release
```

### Scoped searches per topic
When a section's prompt lists specific topics (e.g. "API gateway migration", "Observability roadmap"), run additional targeted queries:
```sql
(text ~ "<topic>" OR labels = "<topic-slug>" OR epic link = "<epic-key>")
AND updated >= "<start>" AND updated <= "<end>"
AND assignee in (<team>)
```
Ask the user once per new topic which epic/label maps to it; cache in `config/team.json` under a `topic_map` key so future runs skip the question.

Pagination: the MCP returns capped page sizes. If `nextPageToken` is present, paginate until exhausted for the date window — don't stop at the first page.

## Slack

Prefer `slack_search_public`. Use `slack_search_public_and_private` only if the user explicitly authorizes private-channel search for this run.

### The user's own messages
```
from:<@SLACK_USER_ID> after:<YYYY-MM-DD> before:<YYYY-MM-DD>
```

### Team signals
Per channel in `team.slack_channels`:
```
in:#<channel> after:<YYYY-MM-DD> before:<YYYY-MM-DD>
```
Then filter client-side for status verbs: `released|shipped|merged|blocked|escalat|failed|rolled back|CVE-|on track|at risk|delayed`.

### Escalations
```
(escalat OR incident OR outage OR rollback) after:<YYYY-MM-DD> before:<YYYY-MM-DD>
```
Limit to team channels to avoid org-wide noise.

## Outlook

`outlook_email_search` with a `query` containing keywords from the section's topics + `email_keywords` from team config + a received-date clause if supported, otherwise filter client-side.

Useful subject patterns to surface: `"[RELEASE]"`, `"Post-mortem"`, `"Escalation"`, customer names from prior weeks. Skip newsletters and auto-digests.

## Parallelization & caching

These queries are independent. Fire them in a single batched message.

Cache raw responses under `.cache/<pageId>/<YYYY-MM-DD>/` keyed by `<source>-<queryhash>.json`. On rerun (same page, same week), reuse the cache. The cache is disposable — delete the whole folder after a successful publish.

## Attribution and dedup

Every bullet in the final draft must trace to at least one source. Keep a lightweight mapping during drafting:
```
"API gateway migration \u2013 rate-limiter v2 rolled to staging" \u2190 [JIRA PLAT-1234, SLACK #platform 2026-04-15T14:22]
```
Don't render the mapping in the preview, but keep it in memory in case the user asks "where did this bullet come from?" after seeing the preview.

Dedup: the same event often shows up in all three systems (a merge lands \u2192 CI notifies Slack \u2192 a release email goes out). Collapse to a single bullet; the Jira key is the canonical identifier.
