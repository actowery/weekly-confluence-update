#!/usr/bin/env python3
"""
Build sanitized test fixtures for the skill's smoke test.

Emits:
  fixtures/empty-weekly.json    — new page, right cells blank (exercises new_team_block)
  fixtures/filled-weekly.json   — row 1 has existing Platform + CoreInfra blocks;
                                  row 2 targets a different team (exercises skip);
                                  challenges row has existing content
                                  (exercises append_to_team_block + team_only_row)
  fixtures/team-platform.json   — test team config matching the fictional roster

No real data. All names, IDs, and tenants are fictional.
"""

import json
from pathlib import Path

TEST_USER_ID = "test-user-001-alex-example"
OTHER_USER_ID = "test-user-002-jordan-sample"

HERE = Path(__file__).parent
FIX = HERE / "fixtures"


def text(s, marks=None):
    n = {"type": "text", "text": s}
    if marks:
        n["marks"] = marks
    return n


def strong(s):
    return text(s, [{"type": "strong"}])


def paragraph(*children):
    return {"type": "paragraph", "content": list(children)}


def mention(account_id, display):
    return {
        "type": "mention",
        "attrs": {"id": account_id, "localId": f"local-{account_id}", "text": f"@{display}"},
    }


def bullet_list(items):
    return {
        "type": "bulletList",
        "content": [
            {"type": "listItem", "content": [paragraph(text(t))]} for t in items
        ],
    }


def table_header(*children):
    return {"type": "tableHeader", "attrs": {"colspan": 1, "rowspan": 1}, "content": list(children)}


def table_cell(*children):
    return {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1}, "content": list(children)}


def table_row(*cells):
    return {"type": "tableRow", "content": list(cells)}


def make_empty():
    header_row = table_row(
        table_header(paragraph(strong("Category"))),
        table_header(paragraph(strong("Update"))),
    )

    prompt_row = table_row(
        table_header(
            paragraph(strong("Highlights & Product Capabilities:")),
            paragraph(
                mention(TEST_USER_ID, "Alex Example"),
                text(" "),
                mention(OTHER_USER_ID, "Jordan Sample"),
                text(" please provide weekly updates for the below:"),
            ),
            bullet_list(["API gateway migration", "Observability roadmap", "CVE remediation"]),
        ),
        table_cell(paragraph()),
    )

    challenges_row = table_row(
        table_header(paragraph(text("Challenges"))),
        table_cell(paragraph()),
    )

    releases_row = table_row(
        table_header(paragraph(text("Product Releases Completed"))),
        table_cell(paragraph()),
    )

    return {
        "id": "fixture-empty",
        "type": "page",
        "title": "Weekly Report, 01 Jun - 05 Jun 2026 (Platform BU)",
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "table", "attrs": {"layout": "center"},
                 "content": [header_row, prompt_row, challenges_row, releases_row]},
            ],
        },
    }


def make_filled():
    header_row = table_row(
        table_header(paragraph(strong("Category"))),
        table_header(paragraph(strong("Update"))),
    )

    # Row 1: prompt mentions test user; right cell has Platform + CoreInfra blocks already.
    prompt_row = table_row(
        table_header(
            paragraph(strong("Highlights & Product Capabilities:")),
            paragraph(
                mention(TEST_USER_ID, "Alex Example"),
                text(" please provide weekly updates for:"),
            ),
            bullet_list(["API gateway migration", "CVE remediation"]),
        ),
        table_cell(
            paragraph(strong("Platform")),
            paragraph(text("API gateway migration – rate-limiter v2 rolled to staging (PLAT-1234).")),
            paragraph(strong("CoreInfra")),
            paragraph(text("Kubernetes upgrade – node pool cordoned and drained (INFRA-99).")),
        ),
    )

    # Row 2: prompt targets someone else, no Platform block in update cell → must be skipped.
    other_team_row = table_row(
        table_header(
            paragraph(strong("Other Team Updates:")),
            paragraph(
                mention(OTHER_USER_ID, "Jordan Sample"),
                text(" please provide weekly updates for:"),
            ),
        ),
        table_cell(
            paragraph(strong("CoreInfra")),
            paragraph(text("Backup policy review in progress.")),
        ),
    )

    # Row 3: team-only Challenges row with some existing content.
    challenges_row = table_row(
        table_header(paragraph(text("Challenges"))),
        table_cell(
            paragraph(strong("CoreInfra:")),
            bullet_list(["Capacity pressure on west-2 cluster."]),
        ),
    )

    # Row 4: empty team-only releases row.
    releases_row = table_row(
        table_header(paragraph(text("Product Releases Completed"))),
        table_cell(paragraph()),
    )

    return {
        "id": "fixture-filled",
        "type": "page",
        "title": "Weekly Report, 01 Jun - 05 Jun 2026 (Platform BU)",
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "table", "attrs": {"layout": "center"},
                 "content": [header_row, prompt_row, other_team_row, challenges_row, releases_row]},
            ],
        },
    }


def make_team_config():
    return {
        "team_name": "Platform",
        "team_slug": "platform",
        "team_lead_account_id": TEST_USER_ID,
        "members": [
            {"display_name": "Alex Example", "atlassian_account_id": TEST_USER_ID,
             "slack_user_id": "U_TEST_ALEX", "email": "alex@example.test",
             "confidence": "confirmed", "signals": ["test_fixture"]},
        ],
        "jira_projects": ["PLAT"],
        "slack_channels": ["#platform"],
        "email_keywords": ["Platform"],
        "cached_at": "2026-06-01",
        "cache_source": "test_fixture",
    }


def main():
    FIX.mkdir(parents=True, exist_ok=True)
    (FIX / "empty-weekly.json").write_text(json.dumps(make_empty(), indent=2))
    (FIX / "filled-weekly.json").write_text(json.dumps(make_filled(), indent=2))
    (FIX / "team-platform.json").write_text(json.dumps(make_team_config(), indent=2))
    print(f"Wrote fixtures to {FIX}")


if __name__ == "__main__":
    main()
