# Output style

The weekly page is read fast by executives. Everyone writing into it adopts a terse house style. Match it — never be more verbose than the existing content, but don't undershoot either. Light bullets that just list workstream names ("Rollout — in progress") are worse than useless; they tell the reader nothing they couldn't already see on a board.

## Two shapes, picked by section kind

### Team-block sections → **paragraph-per-topic**

For `explicit_assignment_with_team_block`, `explicit_assignment_no_team_block`, and `team_owned` sections.

Shape:
```
**<TeamName>**

<Topic 1> – <dense multi-clause paragraph covering every active workstream under this topic, with inline tickets>

<Topic 2> – <same>

<Topic 3 lead-in sentence:>

<Follow-up paragraph with detail>
```

Each topic paragraph is 60–120 words. Cover every workstream under the topic, not just the most prominent. Clauses are separated by periods or semicolons, not commas. Jira/CVE/ticket keys go inline next to the clause that refers to them.

**Golden reference — this is the target (fictional team "Platform"):**
```
**Platform**

API gateway migration – rate-limiter v2 rolled to staging; load test at 2x peak completed
clean (PLAT-1234). Customer allow-list import tool merged and smoke-tested against the
Acme Corp tenant. Canary pending SRE sign-off; target production cutover next sprint.
Auth header rename still in flight behind a feature flag.

Observability – OTel SDK bumped across gateway, auth, and billing services; dashboards
regenerated (OBS-456). Log-retention policy change awaiting InfoSec review. PagerDuty
noise down 40% week-over-week after alert consolidation landed.

Two CVEs resolved this week:

CVE-2025-XXXX (library-a) — patched across three services; Mend confirms clean.
CVE-2025-YYYY (library-b) tracked separately under SEC-789 — dependency upgrade PR
opened, awaiting CI.
```

Note the structural features to replicate:
- Bold team name as its own paragraph.
- One topic per paragraph with `<Topic> – ` prefix (en-dash, not hyphen).
- A "lead-in + detail" pattern when one topic has multiple distinct items (e.g. "Two CVEs resolved this week:" then a paragraph naming them).
- Ticket keys woven into prose, not parenthesized at the end of everything.
- Status words (`in progress`, `blocked`, `in flight`, `resolved`, `merged`) appear naturally inside clauses, not as separate tags.

**Anti-pattern — do not emit this:**
```
**Platform**
- API gateway migration – in progress.
- Observability – ongoing.
- CVEs – resolved.
```
Three bullets tell the reader nothing. The real audience wants density: what's blocked, what's in flight, which tickets, what customer, what's the status. If you have only three one-liners, keep researching — Slack and Jira probably have more signal that's worth surfacing.

### Team-only rows → **flat bullets**

For `team_only_row` sections (Product Releases Completed, Challenges, Organization / Hiring / Resignations).

Shape:
```
**<TeamName>:**
- <single-line bullet>
- <single-line bullet>
```

One line per bullet, 10–25 words. Keep to 1–3 bullets. If nothing happened, contribute nothing — empty is fine, fillers like "no updates" are noise.

**Examples:**
- `CI flakiness across Platform pipelines; multiple reruns needed this week.` (Challenges)
- `Gateway v2.3.0 released to production (PLAT-1200).` (Product Releases Completed)
- `Hired Senior SRE starting 2026-05-05.` (Organization / Hiring)

## Shared guardrails

- **Use en-dash (–), not hyphen (-),** between subject and prose. Matches page convention.
- **Every clause traces to a source.** Jira key, Slack link, or email subject. No invention — if research is thin, say so rather than fill with vague language.
- **No hedging.** Drop "we think", "probably", "hopefully". If unsure, omit.
- **Customer names** only when already public on the page or named in escalations you're summarizing. Never introduce a new customer name on your own initiative.
- **No emojis** unless the surrounding section uses them consistently.
- **No fancy markdown.** The only ADF marks used are `strong` (for the team name + occasional status words) and inline `link` (rarely — prefer plain Jira keys). No tables, headings, blockquotes, or panels inside appended content.
- **Topic scoping.** For an `explicit_assignment_*` section, cover only the topics the prompt enumerated. For a `team_owned` block, cover the team's work thematically aligned to the cell's category (delivery/security/etc.).
- **Releases mean shipped, not planned.** Only list things under Product Releases Completed if the version actually hit GA / tagged / landed in users' hands during the window.
- **Challenges mean this-week blockers**, not chronic gripes.
