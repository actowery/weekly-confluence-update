#!/usr/bin/env python3
"""
Search GitHub for PRs authored, merged, or commented by team members in a date range.

Shells out to the `gh` CLI (must be installed and authenticated). Reads the team
config to discover org(s) and per-member GitHub handles.

Usage:
  search_github.py \
      --team-config "${XDG_CONFIG_HOME:-$HOME/.config}/weekly-confluence-update/teams/<slug>.json" \
      --start 2026-04-06 --end 2026-04-10 \
      [--state merged|open|all]    # default merged
      [--dry-run]                  # print gh commands, don't execute

Output: JSON array on stdout. One entry per PR, shape:
  {
    "author": "handle",
    "display_name": "Full Name",
    "repo": "owner/name",
    "number": 1234,
    "title": "...",
    "url": "https://github.com/...",
    "state": "merged" | "open" | "closed",
    "merged_at": "2026-04-09T...",
    "created_at": "2026-04-07T...",
    "labels": ["..."]
  }

Deduplicates on URL. Exits 0 with `[]` if no signal. Non-zero only on hard errors
(missing gh, bad config). Missing per-member handle is a warning, not an error —
the skill can still research the rest of the team.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


PR_JSON_FIELDS = "number,title,url,repository,author,state,createdAt,closedAt,labels,isDraft"


def have_gh():
    return shutil.which("gh") is not None


def gh_search_prs(handle, orgs, start, end, state, dry_run):
    """Run `gh search prs` for one author, optionally scoped by owner, returning parsed JSON."""
    cmd = ["gh", "search", "prs",
           "--author", handle,
           "--json", PR_JSON_FIELDS,
           "--limit", "100"]
    if state == "merged":
        cmd += ["--merged", f"{start}..{end}"]
    elif state == "open":
        cmd += ["--state", "open", "--created", f"{start}..{end}"]
    elif state == "all":
        cmd += ["--created", f"{start}..{end}"]
    for org in orgs:
        cmd += ["--owner", org]

    if dry_run:
        print("DRY-RUN:", " ".join(cmd), file=sys.stderr)
        return []

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"warn: gh failed for {handle}: {r.stderr.strip()}", file=sys.stderr)
        return []
    try:
        return json.loads(r.stdout or "[]")
    except json.JSONDecodeError as e:
        print(f"warn: could not parse gh output for {handle}: {e}", file=sys.stderr)
        return []


def normalize(pr, display_name):
    """Flatten a gh search prs PR into our output shape.

    Note: `gh search prs --json` does not expose `mergedAt` directly. For PRs
    returned when we queried with `--merged`, the state will be "closed" (gh's
    search API collapses closed+merged) and `closedAt` is effectively the merge
    time. Downstream consumers should treat `closed_at` as merged_at when the
    PR came from a merged-state query.
    """
    repo = pr.get("repository") or {}
    repo_full = repo.get("nameWithOwner") or repo.get("name") or ""
    author = pr.get("author") or {}
    labels = [l.get("name") for l in (pr.get("labels") or []) if isinstance(l, dict)]
    return {
        "author": author.get("login"),
        "display_name": display_name,
        "repo": repo_full,
        "number": pr.get("number"),
        "title": pr.get("title"),
        "url": pr.get("url"),
        "state": pr.get("state"),
        "is_draft": pr.get("isDraft"),
        "created_at": pr.get("createdAt"),
        "closed_at": pr.get("closedAt"),
        "labels": labels,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--team-config", required=True)
    p.add_argument("--start", required=True, help="ISO date, e.g. 2026-04-06")
    p.add_argument("--end", required=True, help="ISO date, inclusive")
    p.add_argument("--state", default="merged", choices=["merged", "open", "all"])
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    cfg = json.loads(Path(args.team_config).read_text())
    github = cfg.get("github") or {}
    orgs = github.get("orgs") or []
    members = cfg.get("members") or []

    if not orgs:
        print("warn: team config has no github.orgs — results will span all of GitHub, "
              "which is noisy. Add orgs to your team config under the 'github' key.",
              file=sys.stderr)

    if not args.dry_run and not have_gh():
        print("error: gh CLI not installed or not on PATH. Install from https://cli.github.com/",
              file=sys.stderr)
        sys.exit(2)

    handled = [(m.get("display_name"), m.get("github_username"))
               for m in members if m.get("github_username")]
    missing = [m.get("display_name") for m in members if not m.get("github_username")]

    if missing:
        print(f"warn: no github_username on record for: {', '.join(missing)}. "
              "Skipping their PRs — add handles via the skill's init flow or edit the team config.",
              file=sys.stderr)

    seen_urls = set()
    results = []
    for display_name, handle in handled:
        prs = gh_search_prs(handle, orgs, args.start, args.end, args.state, args.dry_run)
        for pr in prs:
            url = pr.get("url")
            if url and url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(normalize(pr, display_name))

    # Sort newest first by closed_at (= merge time for merged PRs) then created_at.
    results.sort(key=lambda r: (r.get("closed_at") or r.get("created_at") or ""), reverse=True)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
